"""
SAPO → Staging Sync Service
Chỉ ghi vào STAGING table. An toàn tuyệt đối — không đụng DH/SX.
Workflow v5 sẽ xử lý staging → DH/SX.
"""
import json, logging, os, time, requests
from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sapo_staging_sync")

# ─── CONFIG (env vars) ─────────────────────────
LARK_APP_ID = os.environ["LARK_APP_ID"]
LARK_APP_SECRET = os.environ["LARK_APP_SECRET"]
BASE_TOKEN = os.environ["BASE_TOKEN"]
STAGING_TABLE = "tbloP45vaT4I2mwF"
SAPO_STORE = os.environ["SAPO_STORE"]
SAPO_KEY = os.environ["SAPO_KEY"]
SAPO_SECRET = os.environ["SAPO_SECRET"]
SYNC_INTERVAL_HOURS = int(os.environ.get("SYNC_INTERVAL_HOURS", "6"))
LARK_HOST = "https://open.larksuite.com"
# ───────────────────────────────────────────────

# ─── Lark Client (chỉ ghi staging) ────────────
class LarkClient:
    def __init__(self):
        self.token = None; self.token_expire = 0
    def _ensure_token(self):
        if self.token and time.time() < self.token_expire - 60: return self.token
        r = requests.post(f"{LARK_HOST}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}, timeout=10).json()
        if r.get("code") != 0: raise RuntimeError(f"Lark auth fail: {r}")
        self.token = r["tenant_access_token"]
        self.token_expire = time.time() + r.get("expire", 7200)
        return self.token
    def _headers(self):
        return {"Authorization": f"Bearer {self._ensure_token()}"}
    def create_staging_record(self, fields):
        """Ghi 1 record vào staging. Đây là thao tác duy nhất lên Lark."""
        url = f"{LARK_HOST}/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{STAGING_TABLE}/records"
        r = requests.post(url, headers=self._headers(), json={"fields": fields}, timeout=30)
        return r.json().get("code") == 0

lark = LarkClient()

# ─── SAPO API ─────────────────────────────────
def sapo_get(path):
    r = requests.get(f"https://{SAPO_STORE}/admin/{path}", auth=(SAPO_KEY, SAPO_SECRET), timeout=30)
    return r.json() if r.status_code == 200 else {}

# ─── Sync: SAPO → Staging ────────────────────
def run_sync():
    log.info("=== Sync started ===")
    try:
        since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 7 * 86400))
        data = sapo_get(f"orders.json?created_at_min={since}&limit=250")
        orders = data.get("orders", [])
        page = 1
        while data.get("orders") and len(data.get("orders", [])) == 250:
            page += 1
            data = sapo_get(f"orders.json?created_at_min={since}&limit=250&page={page}")
            orders += data.get("orders", [])
        log.info(f"{len(orders)} orders to process")

        count = 0
        for o in orders:
            on = "#" + str(o["order_number"])
            c = o.get("customer") or {}
            ship = o.get("shipping_address") or {}
            bill = o.get("billing_address") or {}
            name = ((c.get("last_name") or "") + " " + (c.get("first_name") or "")).strip()
            phone = str(o.get("phone") or c.get("phone") or ship.get("phone") or bill.get("phone") or "")
            addr = ", ".join(filter(None, [ship.get(k,"") for k in ["address1","ward","district","city","province"]]))
            total = float(o.get("total_price",0))
            fs = o.get("financial_status","")
            sts = o.get("status","")
            dep = 0
            for tx in o.get("transactions") or []:
                if tx.get("kind") in ("sale","capture") and tx.get("status") == "success":
                    dep += float(tx.get("amount",0))
            if dep == 0 and fs == "paid": dep = total
            ts = o.get("created_at","")
            try: dt = int(time.mktime(time.strptime(ts[:19],"%Y-%m-%dT%H:%M:%S"))) * 1000
            except: dt = 0

            for li in o.get("line_items",[]):
                price = float(li.get("price",0))
                pname = (li.get("name") or li.get("title") or "").strip()
                note = (li.get("note") or "").strip()
                fields = {
                    "Mã đơn hàng SAPO": on, "Khách hàng": name, "SĐT": phone,
                    "Tên sản phẩm mới": pname, "Tổng tiền": price,
                    "Tiền đã đặt cọc": round(price/total*dep) if total > 0 else 0,
                    "Địa chỉ": addr, "Trạng thái thanh toán": fs,
                    "Trạng thái đơn hàng": sts, "Ngày đặt hàng(cọc)": dt,
                    "Ghi chú": note
                }
                try:
                    lark.create_staging_record(fields)
                    count += 1
                except Exception as e:
                    log.warning(f"  Error #{on}/{pname[:20]}: {e}")
        log.info(f"=== Done: {count} staging records created ===")
    except Exception as e:
        log.error(f"Sync fail: {e}")

# ─── Web server ──────────────────────────────
app = Flask(__name__)
@app.route("/") def health(): return jsonify({"status":"ok"})
@app.route("/sync") def trigger(): run_sync(); return jsonify({"status":"synced"})

scheduler = BackgroundScheduler()
scheduler.add_job(run_sync, "interval", hours=SYNC_INTERVAL_HOURS, id="sync_job")
scheduler.start()

if __name__ == "__main__":
    log.info(f"Start (interval {SYNC_INTERVAL_HOURS}h)")
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
