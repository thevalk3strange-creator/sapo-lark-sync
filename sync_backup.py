"""
SAPO → Staging Backup Sync (dùng cho GitHub Actions)
Chạy độc lập, không phụ thuộc Flask.
"""
import json, os, time, requests

# ─── Config ─────────────────────────
LARK_APP_ID = os.environ["LARK_APP_ID"]
LARK_APP_SECRET = os.environ["LARK_APP_SECRET"]
BASE_TOKEN = os.environ["BASE_TOKEN"]
STAGING = "tbloP45vaT4I2mwF"
SAPO_STORE = os.environ["SAPO_STORE"]
SAPO_KEY = os.environ["SAPO_KEY"]
SAPO_SECRET = os.environ["SAPO_SECRET"]
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
LARK_HOST = "https://open.larksuite.com"
# ────────────────────────────────────

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
            headers=self._h(), json={"fields": fields}, timeout=30)
        return r.json().get("code") == 0

lark = LarkClient()

# ─── SAPO ───────────────────────────
def sapo(path):
    r = requests.get(f"https://{SAPO_STORE}/admin/{path}", auth=(SAPO_KEY, SAPO_SECRET), timeout=30)
    return r.json() if r.status_code == 200 else {}

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
    ts = o.get("created_at", "")
    try: dt = int(time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))) * 1000
    except: dt = 0
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

def run():
    print("=== Backup sync ===")
    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 7 * 86400))
    data = sapo(f"orders.json?created_at_min={since}&limit=250")
    orders = data.get("orders", [])
    p = 1
    while data.get("orders") and len(data.get("orders", [])) == 250:
        p += 1
        data = sapo(f"orders.json?created_at_min={since}&limit=250&page={p}")
        orders += data.get("orders", [])
    print(f"{len(orders)} orders found")
    n = sum(sync_order(o) for o in orders)
    print(f"Done: {n} records synced")

    # Thông báo lỗi cho Telegram nếu có
    if n == 0 and len(orders) > 0 and TELEGRAM_TOKEN:
        msg = f"⚠️ <b>Cảnh báo</b>\nBackup sync (GitHub Actions) chạy lúc {time.strftime('%H:%M %d/%m/%Y')}\n"
        msg += f"Có {len(orders)} đơn nhưng 0 record được sync.\nCần kiểm tra Render và Lark workflow."
        try:
            r = requests.get(f"{LARK_HOST}/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{STAGING}/records?page_size=1",
                headers=lark._h(), timeout=10)
            if r.json().get("code") != 0:
                msg += f"\nLỗi Lark: {r.json().get('msg','')}"
            requests.post(f"{TELEGRAM_API}/sendMessage", json={
                "chat_id": os.environ.get("TELEGRAM_ALERT_CHAT_ID", ""),
                "text": msg, "parse_mode": "HTML"
            }, timeout=10)
        except:
            pass

if __name__ == "__main__":
    run()
