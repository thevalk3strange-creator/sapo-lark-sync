"""
SAPO → Staging Backup Sync (dùng cho GitHub Actions)
Phiên bản nhẹ: 1 trang, timeout ngắn, log từng bước.
"""
import json, os, time, requests, sys

print("=== Khởi động sync_backup.py ===")
sys.stdout.flush()

# ─── Config ─────────────────────────
LARK_APP_ID = os.environ.get("LARK_APP_ID", "")
LARK_APP_SECRET = os.environ.get("LARK_APP_SECRET", "")
BASE_TOKEN = os.environ.get("BASE_TOKEN", "")
STAGING = "tbloP45vaT4I2mwF"
SAPO_STORE = os.environ.get("SAPO_STORE", "")
SAPO_KEY = os.environ.get("SAPO_KEY", "")
SAPO_SECRET = os.environ.get("SAPO_SECRET", "")
LARK_HOST = "https://open.larksuite.com"

missing = [k for k,v in {"LARK_APP_ID":LARK_APP_ID,"LARK_APP_SECRET":LARK_APP_SECRET,"BASE_TOKEN":BASE_TOKEN,"SAPO_STORE":SAPO_STORE,"SAPO_KEY":SAPO_KEY,"SAPO_SECRET":SAPO_SECRET}.items() if not v]
if missing:
    print(f"LỖI: Thiếu secrets: {missing}")
    sys.exit(1)
print("Config OK")
sys.stdout.flush()

# ─── Lark ───────────────────────────
class LarkClient:
    def __init__(self):
        self.token = None; self.expire = 0
    def _token(self):
        if self.token and time.time() < self.expire - 60: return self.token
        r = requests.post(f"{LARK_HOST}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}, timeout=10).json()
        if r.get("code") != 0: raise RuntimeError(f"Auth fail: {r}")
        self.token = r["tenant_access_token"]
        self.expire = time.time() + r.get("expire", 7200)
        return self.token
    def _h(self):
        return {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}
    def create(self, fields):
        r = requests.post(f"{LARK_HOST}/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{STAGING}/records",
            headers=self._h(), json={"fields": fields}, timeout=15)
        return r.json().get("code") == 0

print("Connecting to Lark...")
lark = LarkClient()
try:
    lark._token()
    print("Lark token OK")
except Exception as e:
    print(f"LARK AUTH FAIL: {e}")
    sys.exit(1)
sys.stdout.flush()

# ─── SAPO ───────────────────────────
def sapo(path):
    r = requests.get(f"https://{SAPO_STORE}/admin/{path}", auth=(SAPO_KEY, SAPO_SECRET), timeout=15)
    if r.status_code != 200:
        print(f"SAPO error: {r.status_code}")
        return {"orders": []}
    return r.json()

print("Fetching SAPO orders...")
sys.stdout.flush()
data = sapo("orders.json?created_at_min=2026-06-24T00:00:00Z&limit=50")
orders = data.get("orders", [])
print(f"SAPO OK: {len(orders)} orders")
sys.stdout.flush()

# ─── Sync ───────────────────────────
def sync_order(o):
    on = "#" + str(o["order_number"])
    c = o.get("customer") or {}
    ship = o.get("shipping_address") or {}
    bill = o.get("billing_address") or {}
    name = ((c.get("last_name") or "") + " " + (c.get("first_name") or "")).strip()
    phone = str(o.get("phone") or c.get("phone") or ship.get("phone") or bill.get("phone") or "")
    addr = ", ".join(filter(None, [ship.get(k,"") for k in ["address1","ward","district","city","province"]]))
    total = float(o.get("total_price", 0))
    dep = 0
    for tx in (o.get("transactions") or []):
        if tx.get("kind") in ("sale","capture") and tx.get("status") == "success":
            dep += float(tx.get("amount", 0))
    if dep == 0 and o.get("financial_status") == "paid":
        dep = total
    n = 0
    for li in o.get("line_items", []):
        price = float(li.get("price", 0))
        pname = (li.get("name") or li.get("title") or "").strip()
        note = (li.get("note") or "").strip()
        fields = {
            "Mã đơn hàng SAPO": on, "Khách hàng": name, "SĐT": phone,
            "Tên sản phẩm mới": pname, "Tổng tiền": price,
            "Tiền đã đặt cọc": round(price / total * dep) if total > 0 else 0,
            "Địa chỉ": addr,
            "Ghi chú": note, "Hẹn giao": o.get("expected_delivery_date", "")
        }
        try:
            lark.create(fields)
            n += 1
        except:
            pass
    return n

n = 0
for o in orders:
    n += sync_order(o)
    print(f"  #{o['order_number']}: synced")
    sys.stdout.flush()

print(f"=== Done: {n} records ===")
