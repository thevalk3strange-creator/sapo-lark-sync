"""
SAPO → Staging Sync Service
Chỉ ghi vào STAGING — không đụng DH/SX. An toàn tuyệt đối.
Workflow v5 (Lark Base) sẽ xử lý staging → DH + SX.
"""
import json, logging, os, time, requests
from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sapo_staging_sync")

# ─── CONFIG ─────────────────────────
LARK_APP_ID = os.environ["LARK_APP_ID"]
LARK_APP_SECRET = os.environ["LARK_APP_SECRET"]
BASE_TOKEN = os.environ["BASE_TOKEN"]
STAGING = "tbloP45vaT4I2mwF"
SAPO_STORE = os.environ["SAPO_STORE"]
SAPO_KEY = os.environ["SAPO_KEY"]
SAPO_SECRET = os.environ["SAPO_SECRET"]
LARK_HOST = "https://open.larksuite.com"
INTERVAL_HOURS = int(os.environ.get("INTERVAL_HOURS", "6"))
# ────────────────────────────────────

# ─── Lark: chỉ ghi staging ─────────
class LarkClient:
    def __init__(self):
        self.token = None; self.expire = 0
    def _token(self):
        if self.token and time.time() < self.expire - 60: return self.token
        r = requests.post(f"{LARK_HOST}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}, timeout=10).json()
        if r.get("code") != 0: raise RuntimeError(f"Lark auth fail: {r}")
        self.token = r["tenant_access_token"]
        self.expire = time.time() + r.get("expire", 7200)
        return self.token
    def _h(self):
        return {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}
    def create(self, fields):
        r = requests.post(f"{LARK_HOST}/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{STAGING}/records",
            headers=self._h(), json={"fields": fields}, timeout=30)
        return r.json().get("code") == 0

lark = LarkClient()

# ─── SAPO ───────────────────────────
def sapo(path):
    r = requests.get(f"https://{SAPO_STORE}/admin/{path}", auth=(SAPO_KEY, SAPO_SECRET), timeout=30)
    return r.json() if r.status_code == 200 else {}

# ─── Sync ───────────────────────────
def sync_order(o):
    """Write 1 SAPO order → staging (all fields)."""
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
    n = 0
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
            "Ghi chú": note, "Hẹn giao": o.get("expected_delivery_date","")
        }
        try: lark.create(fields); n += 1
        except Exception as e: log.warning(f"  #{on}/{pname[:20]}: {e}")
    return n

def run():
    log.info("=== Sync last 7 days ===")
    try:
        since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 7 * 86400))
        data = sapo(f"orders.json?created_at_min={since}&limit=250")
        orders = data.get("orders", [])
        p = 1
        while data.get("orders") and len(data.get("orders",[])) == 250:
            p += 1
            data = sapo(f"orders.json?created_at_min={since}&limit=250&page={p}")
            orders += data.get("orders", [])
        log.info(f"{len(orders)} orders")
        n = sum(sync_order(o) for o in orders)
        log.info(f"=== Done: {n} records ===")
    except Exception as e:
        log.error(f"Sync fail: {e}")

def scan_all():
    log.info("=== SCAN ALL SAPO ORDERS ===")
    try:
        data = sapo("orders.json?limit=250")
        orders = data.get("orders", [])
        p = 1
        while data.get("orders") and len(data.get("orders",[])) == 250:
            p += 1
            data = sapo(f"orders.json?limit=250&page={p}")
            orders += data.get("orders", [])
        log.info(f"{len(orders)} total orders")
        n = sum(sync_order(o) for o in orders)
        log.info(f"=== Scan done: {n} records ===")
    except Exception as e:
        log.error(f"Scan fail: {e}")

# ─── Web ────────────────────────────
app = Flask(__name__)

@app.route("/")
def health():
    return jsonify({"status":"ok"})

@app.route("/sync")
def trigger():
    run(); return jsonify({"status":"synced"})

@app.route("/scan-all")
def trigger_scan():
    scan_all(); return jsonify({"status":"scan_completed"})

# ─── Scheduler ──────────────────────
scheduler = BackgroundScheduler()
scheduler.add_job(run, "interval", hours=INTERVAL_HOURS, id="sync")
scheduler.start()

if __name__ == "__main__":
    log.info(f"Start (interval={INTERVAL_HOURS}h)")
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
