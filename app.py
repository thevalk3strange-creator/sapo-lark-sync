"""
SAPO → Staging Sync Service
Chỉ ghi vào STAGING — không đụng DH/SX. An toàn tuyệt đối.
Workflow v5 (Lark Base) sẽ xử lý staging → DH + SX.
"""
import json, logging, os, time, requests, threading
from flask import Flask, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sapo_staging_sync")

# ─── CONFIG ─────────────────────────
LARK_APP_ID = os.environ["LARK_APP_ID"]
LARK_APP_SECRET = os.environ["LARK_APP_SECRET"]
BASE_TOKEN = os.environ["BASE_TOKEN"]
STAGING = "tbloP45vaT4I2mwF"
DH_TABLE = "tblZlQNNxxyMb4aS"
SAPO_STORE = os.environ["SAPO_STORE"]
SAPO_KEY = os.environ["SAPO_KEY"]
SAPO_SECRET = os.environ["SAPO_SECRET"]
LARK_HOST = "https://open.larksuite.com"
SYNC_HOURS = os.environ.get("SYNC_HOURS", "8-20/2")
SYNC_TZ = "Asia/Ho_Chi_Minh"

# ─── Telegram ──────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
CHAT_IDS_FILE = "/tmp/chat_ids.json"

# ─── OpenRouter (free model) ────────
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
AI_MODEL = "nousresearch/hermes-3-llama-3.1-8b:free"

SYSTEM_PROMPT = """Bạn là trợ lý CSKH của Gấm Vóc (shop áo dài cưới).
Bạn trả lời ngắn gọn, thân thiện bằng tiếng Việt.
Bạn có thể tra cứu thông tin đơn hàng khi khách hàng cung cấp số điện thoại hoặc mã đơn.
Khi khách hỏi về sản phẩm/áo dài, bạn tư vấn nhiệt tình.
Nếu không tìm thấy đơn hàng, hãy đề nghị khách cung cấp thêm thông tin (số điện thoại, mã đơn chính xác).
Không nói "không có quyền truy cập" — thay vào đó hãy nói "không tìm thấy" và đề nghị khách kiểm tra lại thông tin."""

def ask_ai(user_msg):
    """Gọi OpenRouter API để trả lời tin nhắn"""
    if not OPENROUTER_KEY:
        return "❌ Chưa cấu hình AI. Liên hệ admin để setup."
    try:
        r = requests.post(OPENROUTER_URL, json={
            "model": AI_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg}
            ],
            "max_tokens": 500,
            "temperature": 0.7
        }, headers={
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://gam-voc.mysapo.net",
            "X-Title": "Tro Ly Gam Voc CSKH"
        }, timeout=30)
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.error(f"AI error: {e}")
        return "😅 Xin lỗi, mình đang bị lỗi kết nối AI. Thử lại sau nhé!"

def load_chat_ids():
    try:
        with open(CHAT_IDS_FILE) as f:
            return json.load(f)
    except:
        return []

def save_chat_id(chat_id):
    ids = load_chat_ids()
    if chat_id not in ids:
        ids.append(chat_id)
        with open(CHAT_IDS_FILE, "w") as f:
            json.dump(ids, f)
        return True
    return False

def send_telegram(text, chat_id=None):
    if not TELEGRAM_TOKEN:
        return
    targets = [chat_id] if chat_id else load_chat_ids()
    for cid in targets:
        try:
            requests.post(f"{TELEGRAM_API}/sendMessage", json={
                "chat_id": cid, "text": text, "parse_mode": "HTML"
            }, timeout=10)
        except Exception as e:
            log.warning(f"Telegram send fail ({cid}): {e}")

def lookup_order(query):
    """Tìm đơn hàng theo SĐT hoặc mã đơn — dùng Lark filter API để nhanh."""
    try:
        q = query.strip().lstrip("#").lower()
        all_items = []
        
        # 1. Nếu query có dạng số, thử filter theo Mã đơn hàng SAPO
        if q.isdigit() or (query.startswith("#") and q.isdigit()):
            order_code = "#" + q if not query.startswith("#") else query.strip()
            try:
                url = f"{LARK_HOST}/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{DH_TABLE}/records"
                params = {"filter": f'CurrentValue.[Mã đơn hàng SAPO] = "{order_code}"', "page_size": 20}
                r = requests.get(url, headers=lark._h(), params=params, timeout=10).json()
                if r.get("code") == 0:
                    all_items.extend(r.get("data", {}).get("items", []))
            except: pass
        
        # 2. Nếu query là SĐT (10 chữ số), filter theo SĐT
        clean_phone = q.replace(" ", "").replace("-", "")
        if clean_phone.isdigit() and len(clean_phone) >= 9:
            try:
                url = f"{LARK_HOST}/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{DH_TABLE}/records"
                params = {"filter": f'CurrentValue.[SĐT] = "{clean_phone}"', "page_size": 20}
                r = requests.get(url, headers=lark._h(), params=params, timeout=10).json()
                if r.get("code") == 0:
                    all_items.extend(r.get("data", {}).get("items", []))
            except: pass
        
        # 3. Nếu không tìm được bằng filter, fallback quét 1 page
        if not all_items:
            chunk = lark.list_records(DH_TABLE, page_size=100)
            for item in chunk.get("items", []):
                f = item.get("fields", {})
                phone = str(f.get("SĐT", "")).strip()
                order_num = str(f.get("Mã đơn hàng SAPO", "")).strip().lstrip("#")
                name = str(f.get("Khách hàng", "")).strip()
                if q in phone or q == order_num or q in name.lower():
                    all_items.append(item)
        
        # Dedup
        seen = set()
        matches = []
        for item in all_items:
            f = item.get("fields", {})
            key = f.get("Mã đơn hàng SAPO", "") + "|" + f.get("Tên sản phẩm mới", "")
            if key not in seen:
                seen.add(key)
                matches.append(f)
        
        log.info(f"Lookup '{query}': found {len(matches)} matches")
        return matches[:5]
    except Exception as e:
        log.warning(f"Order lookup fail: {e}")
        return []

def format_order_info(matches):
    """Format thông tin đơn hàng để hiển thị."""
    if not matches:
        return "❌ Không tìm thấy đơn hàng nào phù hợp."
    lines = ["📦 <b>Kết quả tìm kiếm:</b>\n"]
    for m in matches[:3]:
        order = m.get("Mã đơn hàng SAPO", "?")
        name = m.get("Khách hàng", "?")
        product = m.get("Tên sản phẩm mới", "?")
        status = m.get("Trạng thái đơn hàng", "?")
        payment = m.get("Trạng thái thanh toán", "?")
        total = m.get("Tổng tiền", 0)
        lines.append(f"• <b>{order}</b> - {name}")
        lines.append(f"  Sản phẩm: {product}")
        lines.append(f"  Trạng thái: {status} | Thanh toán: {payment}")
        lines.append(f"  Tổng: {float(total):,.0f}đ\n")
    return "\n".join(lines)

def detect_month_query(text):
    """Phát hiện câu hỏi về tháng. Trả về (month, year) hoặc None."""
    import re
    text = text.lower().strip()
    
    # Map tháng Việt Nam
    month_map = {
        "tháng 1": 1, "tháng 2": 2, "tháng 3": 3, "tháng 4": 4,
        "tháng 5": 5, "tháng 6": 6, "tháng 7": 7, "tháng 8": 8,
        "tháng 9": 9, "tháng 10": 10, "tháng 11": 11, "tháng 12": 12,
        "thang 1": 1, "thang 2": 2, "thang 3": 3, "thang 4": 4,
        "thang 5": 5, "thang 6": 6, "thang 7": 7, "thang 8": 8,
        "thang 9": 9, "thang 10": 10, "thang 11": 11, "thang 12": 12,
        "thg 1": 1, "thg 2": 2, "thg 3": 3, "thg 4": 4,
        "thg 5": 5, "thg 6": 6, "thg 7": 7, "thg 8": 8,
        "thg 9": 9, "thg 10": 10, "thg 11": 11, "thg 12": 12,
    }
    
    # Kiểm tra pattern "tháng X"
    for key, month in month_map.items():
        if key in text:
            # Tìm year nếu có
            year_match = re.search(r'20\d{2}', text)
            year = int(year_match.group()) if year_match else None
            return (month, year)
    
    return None

def report_daily():
    """Gửi báo cáo cuối ngày cho CSKH"""
    log.info("=== Daily report ===")
    try:
        today = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime())
        data = sapo(f"orders.json?created_at_min={today}&limit=250")
        orders = data.get("orders", [])
        total_revenue = sum(float(o.get("total_price", 0)) for o in orders)

        msg = f"📊 <b>Báo cáo hôm nay</b>\n"
        msg += f"📅 {time.strftime('%d/%m/%Y', time.localtime())}\n\n"
        msg += f"🆕 Đơn mới: <b>{len(orders)}</b>\n"
        msg += f"💰 Doanh thu: <b>{total_revenue:,.0f}đ</b>\n\n"

        if orders:
            msg += "━━━ Danh sách ━━━\n"
            for o in orders[:15]:
                ship = o.get("shipping_address") or {}
                c = o.get("customer") or {}
                name = ship.get("name", "") or f"{c.get('last_name','')} {c.get('first_name','')}".strip()
                msg += f"• #{o['order_number']} {name}: {float(o['total_price']):,.0f}đ\n"
            if len(orders) > 15:
                msg += f"... và {len(orders)-15} đơn khác\n"

        msg += f"\n━━━━━━━━━\n<i>Nguồn: Railway | {time.strftime('%H:%M %d/%m/%Y')}</i>"
        send_telegram(msg)
        log.info(f"Report sent to {len(load_chat_ids())} chats")
    except Exception as e:
        log.error(f"Report fail: {e}")

def report_monthly(month, year=None):
    """Báo cáo thống kê theo tháng"""
    if not year:
        year = time.localtime().tm_year
    try:
        # Tính ngày đầu và cuối tháng
        from calendar import monthrange
        last_day = monthrange(year, month)[1]
        date_min = f"{year}-{month:02d}-01T00:00:00Z"
        date_max = f"{year}-{month:02d}-{last_day:02d}T23:59:59Z"
        
        # Fetch orders trong tháng
        all_orders = []
        page = 1
        while True:
            data = sapo(f"orders.json?created_at_min={date_min}&created_at_max={date_max}&limit=250&page={page}")
            orders = data.get("orders", [])
            all_orders.extend(orders)
            if len(orders) < 250:
                break
            page += 1
        
        total_revenue = sum(float(o.get("total_price", 0)) for o in all_orders)
        paid_orders = [o for o in all_orders if o.get("financial_status") == "paid"]
        paid_revenue = sum(float(o.get("total_price", 0)) for o in paid_orders)
        
        # Top customers
        customer_stats = {}
        for o in all_orders:
            ship = o.get("shipping_address") or {}
            c = o.get("customer") or {}
            name = ship.get("name", "") or f"{c.get('last_name','')} {c.get('first_name','')}".strip()
            if name:
                if name not in customer_stats:
                    customer_stats[name] = {"count": 0, "total": 0}
                customer_stats[name]["count"] += 1
                customer_stats[name]["total"] += float(o.get("total_price", 0))
        
        top_customers = sorted(customer_stats.items(), key=lambda x: x[1]["total"], reverse=True)[:5]
        
        month_names = ["", "Tháng 1", "Tháng 2", "Tháng 3", "Tháng 4", "Tháng 5", "Tháng 6",
                       "Tháng 7", "Tháng 8", "Tháng 9", "Tháng 10", "Tháng 11", "Tháng 12"]
        
        msg = f"📊 <b>{month_names[month]} {year}</b>\n\n"
        msg += f"📦 Tổng đơn: <b>{len(all_orders)}</b>\n"
        msg += f"✅ Đã thanh toán: <b>{len(paid_orders)}</b>\n"
        msg += f"💰 Tổng doanh thu: <b>{total_revenue:,.0f}đ</b>\n"
        msg += f"💵 Đã thu: <b>{paid_revenue:,.0f}đ</b>\n\n"
        
        if top_customers:
            msg += "🏆 <b>Top khách hàng:</b>\n"
            for name, stats in top_customers:
                msg += f"• {name}: {stats['count']} đơn, {stats['total']:,.0f}đ\n"
        
        msg += f"\n━━━━━━━━━\n<i>Nguồn: Railway | {time.strftime('%H:%M %d/%m/%Y')}</i>"
        send_telegram(msg)
        log.info(f"Monthly report {month}/{year}: {len(all_orders)} orders")
    except Exception as e:
        log.error(f"Monthly report fail: {e}")
        send_telegram(f"❌ Không thể tạo báo cáo tháng {month}/{year}. Thử lại sau.")
# ────────────────────────────────────
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
    def list_records(self, table_id, page_size=500, page_token=None):
        url = f"{LARK_HOST}/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{table_id}/records?page_size={page_size}"
        if page_token: url += f"&page_token={page_token}"
        r = requests.get(url, headers=self._h(), timeout=30).json()
        return r.get("data", {})
    def update(self, table_id, record_id, fields):
        r = requests.put(f"{LARK_HOST}/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{table_id}/records/{record_id}",
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

def backfill_sx():
    """Scan DH → write to staging → v5 pushes to SX"""
    log.info("=== Backfill DH → SX ===")
    try:
        h = lark._h(); items = []; pt = None
        while True:
            url = f"{LARK_HOST}/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{DH_TABLE}/records?page_size=500"
            if pt: url += f"&page_token={pt}"
            r = requests.get(url, headers=h, timeout=30).json()
            items += r.get("data", {}).get("items", [])
            if not r.get("data", {}).get("has_more"): break
            pt = r["data"].get("page_token", "")
        log.info(f"{len(items)} DH records")
        n = 0
        for item in items:
            f = item.get("fields", {})
            order = f.get("Mã đơn hàng SAPO", "")
            if not order: continue
            clean = {k:v for k,v in {
                "Mã đơn hàng SAPO": order, "Khách hàng": f.get("Khách hàng", ""),
                "SĐT": f.get("SĐT", ""), "Địa chỉ": f.get("Địa chỉ", ""),
                "Ngày đặt hàng(cọc)": f.get("Ngày đặt hàng(cọc)", 0),
                "Ghi chú": f.get("Ghi chú", ""), "Hẹn giao": f.get("Hẹn giao", 0),
                "Tên sản phẩm mới": f.get("Tên sản phẩm mới", ""),
                "Tổng tiền": f.get("Tổng tiền", 0),
                "Tiền đã đặt cọc": f.get("Tiền đã đặt cọc", 0),
                "Trạng thái thanh toán": f.get("Trạng thái thanh toán", ""),
                "Trạng thái đơn hàng": f.get("Trạng thái đơn hàng", ""),
            }.items() if v is not None and v != ""}
            try: lark.create(clean); n += 1
            except: pass
        log.info(f"=== Done: {n} staging records ===")
    except Exception as e:
        log.error(f"Backfill fail: {e}")

def scan_all():
    """Scan ALL SAPO orders → staging"""
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

@app.route("/backfill-sx")
def trigger_backfill():
    backfill_sx(); return jsonify({"status":"backfill_completed"})

@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    data = request.json
    if not data:
        return jsonify({"ok": False}), 400
    
    def process():
        msg = data.get("message", {})
        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        text = msg.get("text", "")
        if text == "/start":
            new = save_chat_id(chat_id)
            reply = "✅ Đã đăng ký nhận báo cáo hàng ngày!\nTừ 17h mỗi ngày bạn sẽ nhận được báo cáo tổng kết."
            if not new:
                reply = "✅ Bạn đã đăng ký trước đó rồi."
            send_telegram(reply, chat_id)
        elif text == "/now":
            report_daily()
        elif text == "/help":
            send_telegram(
                "🤖 <b>Trợ lý Gấm Vóc</b>\n\n"
                "/start - Đăng ký nhận báo cáo\n"
                "/now - Báo cáo ngay\n"
                "/help - Trợ giúp\n\n"
                "💬 Hoặc hỏi mình bất cứ điều gì!", chat_id)
        elif text:
            is_order_query = (
                text.startswith("#") or 
                (text.replace(" ", "").replace("-", "").isdigit() and len(text) >= 4)
            )
            if is_order_query:
                matches = lookup_order(text)
                if matches:
                    reply = format_order_info(matches)
                    send_telegram(reply, chat_id)
                else:
                    reply = ask_ai(text)
                    send_telegram(reply, chat_id)
            else:
                log.info(f"AI question from {chat_id}: {text[:50]}")
                reply = ask_ai(text)
                send_telegram(reply, chat_id)
    
    threading.Thread(target=process, daemon=True).start()
    return jsonify({"ok": True})

# ─── Scheduler ──────────────────────
scheduler = BackgroundScheduler()
scheduler.add_job(run, "cron", hour=SYNC_HOURS, minute="0", timezone="Asia/Ho_Chi_Minh", id="sync")
if TELEGRAM_TOKEN:
    scheduler.add_job(report_daily, "cron", hour="17", minute="0", timezone="Asia/Ho_Chi_Minh", id="daily_report")
scheduler.start()

if __name__ == "__main__":
    log.info(f"Start (cron hour={SYNC_HOURS}, tz=Asia/Ho_Chi_Minh)")
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
