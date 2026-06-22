"""
Cloud Sync Service — SAPO ↔ Lark Base
Runs 24/7, syncs orders automatically every 6 hours.
Deploy to Render / Railway / Fly.io
"""
import json, logging, os, time, requests
from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sync_service")

# ─── CONFIG (set via env vars) ─────────────────────────
LARK_APP_ID = os.environ["LARK_APP_ID"]
LARK_APP_SECRET = os.environ["LARK_APP_SECRET"]
BASE_TOKEN = os.environ["BASE_TOKEN"]
DH_TABLE = "tblZlQNNxxyMb4aS"
SX_TABLE = "tblT60XXm76Xi7fz"
SAPO_STORE = os.environ["SAPO_STORE"]
SAPO_KEY = os.environ["SAPO_KEY"]
SAPO_SECRET = os.environ["SAPO_SECRET"]
SYNC_INTERVAL_HOURS = int(os.environ.get("SYNC_INTERVAL_HOURS", "6"))
LARK_HOST = "https://open.larksuite.com"
# ────────────────────────────────────────────────────────

class LarkClient:
    def __init__(self):
        self.token = None; self.token_expire = 0
    def _ensure_token(self):
        if self.token and time.time() < self.token_expire - 60: return self.token
        r = requests.post(f"{LARK_HOST}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}, timeout=10).json()
        if r.get("code") != 0: raise RuntimeError(f"Lark auth failed: {r}")
        self.token = r["tenant_access_token"]
        self.token_expire = time.time() + r.get("expire", 7200)
        return self.token
    def _headers(self):
        return {"Authorization": f"Bearer {self._ensure_token()}"}

    def get_all_records(self, table_id):
        """Fetch ALL records from a table (paginated)."""
        items = []
        page_token = None
        while True:
            url = f"{LARK_HOST}/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{table_id}/records?page_size=500"
            if page_token: url += f"&page_token={page_token}"
            r = requests.get(url, headers=self._headers(), timeout=30).json()
            if r.get("code") != 0:
                log.warning(f"Lark list error: {r.get('msg','')}")
                break
            items.extend(r.get("data", {}).get("items", []))
            if not r.get("data", {}).get("has_more"): break
            page_token = r["data"].get("page_token", "")
        return items

    def update_record(self, table_id, record_id, fields):
        url = f"{LARK_HOST}/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{table_id}/records/{record_id}"
        r = requests.put(url, headers=self._headers(), json={"fields": fields}, timeout=30)
        d = r.json()
        if d.get("code") != 0: log.warning(f"Update fail {record_id}: {d.get('msg','')}")
        return d.get("code") == 0

    def create_record(self, table_id, fields):
        url = f"{LARK_HOST}/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{table_id}/records"
        r = requests.post(url, headers=self._headers(), json={"fields": fields}, timeout=30)
        d = r.json()
        return d.get("code") == 0

# ─── SAPO API ──────────────────────────────────────────
def sapo_get(path):
    r = requests.get(f"https://{SAPO_STORE}/admin/{path}", auth=(SAPO_KEY, SAPO_SECRET), timeout=30)
    return r.json() if r.status_code == 200 else {}

# ─── Sync Logic ────────────────────────────────────────
lark = LarkClient()

def build_record_index(items, key_field="Mã đơn hàng SAPO"):
    """Build {order_number: [{record_id, fields, product_name?}]} lookup."""
    idx = {}
    for item in items:
        f = item.get("fields", {})
        key = str(f.get(key_field, ""))
        if not key: continue
        idx.setdefault(key, []).append({
            "record_id": item["record_id"],
            "fields": f,
            "product_name": str(f.get("Tên sản phẩm mới", ""))
        })
    return idx

def sync_order(api_id):
    """Sync one SAPO order to DH + SX."""
    data = sapo_get(f"orders/{api_id}.json")
    o = data.get("order")
    if not o: return
    on = "#" + str(o["order_number"])
    c = o.get("customer") or {}
    ship = o.get("shipping_address") or {}
    bill = o.get("billing_address") or {}
    name = ((c.get("last_name") or "") + " " + (c.get("first_name") or "")).strip()
    phone = str(o.get("phone") or c.get("phone") or ship.get("phone") or bill.get("phone") or "")
    addr = ", ".join(filter(None, [ship.get(k, "") for k in ["address1", "ward", "district", "city", "province"]]))
    total = float(o.get("total_price", 0))
    fs = o.get("financial_status", "")
    sts = o.get("status", "")
    dep = 0
    for tx in o.get("transactions") or []:
        if tx.get("kind") in ("sale", "capture") and tx.get("status") == "success":
            dep += float(tx.get("amount", 0))
    if dep == 0 and fs == "paid": dep = total
    ts = o.get("created_at", "")
    try: dt = int(time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))) * 1000
    except: dt = 0
    for li in o.get("line_items", []):
        price = float(li.get("price", 0))
        ratio = price / total if total > 0 else 0
        pname = (li.get("name") or "").strip()
        note = (li.get("note") or "").strip()
        dh_fields = {"Mã đơn hàng SAPO": on, "Khách hàng": name, "SĐT": phone,
            "Tên sản phẩm mới": pname, "Tổng tiền": price,
            "Tiền đã đặt cọc": round(ratio * dep) if dep > 0 else 0,
            "Địa chỉ": addr, "Trạng thái thanh toán": fs,
            "Trạng thái đơn hàng": sts, "Ngày đặt hàng(cọc)": dt, "Ghi chú": note}
        # Match DH by order# + product name
        records = dh_index.get(on, [])
        match = next((r for r in records if r["product_name"] == pname), None)
        if match:
            lark.update_record(DH_TABLE, match["record_id"], dh_fields)
        else:
            lark.create_record(DH_TABLE, dh_fields)
        # Match SX by order#
        sx_records = sx_index.get(on, [])
        sx_fields = {"Mã đơn hàng SAPO": on, "Khách hàng": name, "SĐT": phone,
            "Địa chỉ": addr, "Ngày đặt": dt, "Ghi chú": note if note else ""}
        if sx_records:
            lark.update_record(SX_TABLE, sx_records[0]["record_id"], sx_fields)
        else:
            lark.create_record(SX_TABLE, sx_fields)

def run_sync():
    """Main sync: fetch SAPO orders → update Lark"""
    log.info("=== Sync started ===")
    global dh_index, sx_index
    try:
        # Build local indexes
        log.info("Fetching DH records...")
        dh_items = lark.get_all_records(DH_TABLE)
        dh_index = build_record_index(dh_items)
        log.info(f"  {len(dh_items)} DH records loaded")
        log.info("Fetching SX records...")
        sx_items = lark.get_all_records(SX_TABLE)
        sx_index = build_record_index(sx_items)
        log.info(f"  {len(sx_items)} SX records loaded")
        # Fetch SAPO orders (last 7 days)
        since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 7 * 86400))
        data = sapo_get(f"orders.json?created_at_min={since}&limit=250")
        orders = data.get("orders", [])
        # Get more pages
        page = 1
        while data.get("orders") and len(data.get("orders", [])) == 250:
            page += 1
            data = sapo_get(f"orders.json?created_at_min={since}&limit=250&page={page}")
            orders += data.get("orders", [])
        log.info(f"Found {len(orders)} SAPO orders")
        # Sync each order
        synced = 0
        for o in orders:
            try:
                sync_order(o["id"])
                synced += 1
            except Exception as e:
                log.warning(f"  Error #{o.get('order_number')}: {e}")
        log.info(f"=== Sync done: {synced} orders processed ===")
    except Exception as e:
        log.error(f"Sync failed: {e}")
        import traceback; traceback.print_exc()

# ─── Web Server ────────────────────────────────────────
app = Flask(__name__)
@app.route("/") def health(): return jsonify({"status": "ok"})
@app.route("/sync") def trigger_sync(): run_sync(); return jsonify({"status": "synced"})

# ─── Scheduler ─────────────────────────────────────────
scheduler = BackgroundScheduler()
scheduler.add_job(run_sync, "interval", hours=SYNC_INTERVAL_HOURS, id="sync_job")
scheduler.start()

if __name__ == "__main__":
    log.info(f"Starting (interval: {SYNC_INTERVAL_HOURS}h)")
    run_sync()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
