#!/usr/bin/env python3
"""
SAPO → Lark Base Sync Script
Usage:
  python3 sync-sapo-to-lark.py --order 1444          # Sync 1 order
  python3 sync-sapo-to-lark.py --days 3               # Sync last 3 days
  python3 sync-sapo-to-lark.py --all                  # Sync all orders
  python3 sync-sapo-to-lark.py --github-actions --days 7  # Run on GitHub Actions
"""
import json, subprocess as sp, time, sys, os, requests

# ─── CONFIG ──────────────────────────────────────────────
# Local (lark-cli) mode uses these directly
API_KEY = os.environ["SAPO_KEY"]
API_SECRET = os.environ["SAPO_SECRET"]
STORE = os.environ["SAPO_STORE"]
BASE_TOKEN = os.environ["BASE_TOKEN"]

# GitHub Actions mode uses Lark REST API
LARK_APP_ID = os.environ["LARK_APP_ID"]
LARK_APP_SECRET = os.environ["LARK_APP_SECRET"]
IS_GH_ACTIONS = "--github-actions" in sys.argv
DH_TABLE = "tblZlQNNxxyMb4aS"
SX_TABLE = "tblT60XXm76Xi7fz"
# ─────────────────────────────────────────────────────────

def sapo(path):
    r = sp.run(f'curl -s "https://{STORE}/admin/{path}" -u "{API_KEY}:{API_SECRET}" --connect-timeout 10 --max-time 15 2>/dev/null', shell=True, capture_output=True, text=True, timeout=20)
    if not r.stdout.strip():
        return {}
    try: return json.loads(r.stdout)
    except: return {}

def lark(args):
    if IS_GH_ACTIONS:
        return _lark_api(args)
    r = sp.run(f'lark-cli base {args} --base-token {BASE_TOKEN} --as bot 2>/dev/null', shell=True, capture_output=True, text=True, timeout=30)
    try: return json.loads(r.stdout)
    except: return {}

def _lark_api(args_raw):
    """Call Lark REST API directly (used on GitHub Actions). Client-side filtering."""
    import re, shlex
    try: parts = shlex.split(args_raw)
    except: parts = args_raw.split()
    action = parts[0]

    global _lark_token
    if not _lark_token:
        r = requests.post("https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}, timeout=10).json()
        if r.get("code") != 0: return {"ok": False, "error": r.get("msg","auth failed")}
        _lark_token = r["tenant_access_token"]

    headers = {"Authorization": f"Bearer {_lark_token}"}

    if action == "+record-list":
        tid = _parse_opt(parts, "--table-id")
        # Fetch ALL records (paginated)
        all_items = []
        page_token = None
        while True:
            url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{tid}/records?page_size=500"
            if page_token: url += f"&page_token={page_token}"
            r = requests.get(url, headers=headers, timeout=30).json()
            if r.get("code") != 0: return {"ok": False}
            all_items.extend(r.get("data", {}).get("items", []))
            if not r.get("data", {}).get("has_more"): break
            page_token = r["data"].get("page_token", "")
        # Apply client-side filter (extract conditions from --filter-json)
        filter_match = re.search(r"--filter-json '(.+?)'", args_raw)
        if filter_match:
            try:
                filter_data = json.loads(filter_match.group(1))
                conds = filter_data.get("conditions", [])
                for cond in conds:
                    if len(cond) >= 3 and cond[1] == "==":
                        field, val = cond[0], str(cond[2])
                        all_items = [it for it in all_items if str(it.get("fields", {}).get(field, "")) == val]
            except: pass
        return {"ok": True, "data": {
            "records": [it.get("fields", {}) for it in all_items],
            "record_id_list": [it["record_id"] for it in all_items],
            "items": all_items
        }}

    elif action == "+record-upsert":
        tid = _parse_opt(parts, "--table-id")
        rid = _parse_opt(parts, "--record-id")
        json_str = ""
        idx = -1
        for i, p in enumerate(parts):
            if p == "--json" and i + 1 < len(parts):
                json_str = parts[i + 1]
                break
        try: fields = json.loads(json_str) if json_str else {}
        except: fields = {}
        if not fields:
            return {"ok": True, "data": {"created": False}}  # Skip empty update
        if rid:
            url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{tid}/records/{rid}"
            r = requests.put(url, headers=headers, json={"fields": fields}, timeout=30).json()
            return {"ok": r.get("code") == 0, "data": {"created": False}}
        else:
            url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{tid}/records"
            r = requests.post(url, headers=headers, json={"fields": fields}, timeout=30).json()
            return {"ok": r.get("code") == 0, "data": {"created": True}}

    return {"ok": False}

_lark_token = None

def _parse_opt(parts, opt):
    for i, p in enumerate(parts):
        if p == opt and i + 1 < len(parts):
            return parts[i + 1].strip("'\"")
    return ""

def _gh_upsert(table_id, fields, match_values):
    """GitHub Actions: search + upsert via direct REST API (no shell escaping)."""
    headers = {"Authorization": f"Bearer {_gh_get_token()}"}

    # Build filter from match values (field depends on table)
    match_field = "Mã đơn hàng SAPO"
    filter_cond = json.dumps({"logic":"and","conditions":[[match_field,"==",match_values[0]]]})

    # Search matching records
    all_items = []
    page_token = None
    while True:
        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{table_id}/records?page_size=500"
        if page_token: url += f"&page_token={page_token}"
        r = requests.get(url, headers=headers, timeout=30).json()
        if r.get("code") != 0: break
        all_items.extend(r.get("data", {}).get("items", []))
        if not r.get("data", {}).get("has_more"): break
        page_token = r["data"].get("page_token", "")
    # Client-side filter
    filtered = [it for it in all_items
                if str(it.get("fields",{}).get(match_field,"")) == match_values[0]]
    # Match by product name for DH table
    if table_id == DH_TABLE and len(match_values) > 1 and match_values[1]:
        filtered = [it for it in filtered
                    if str(it.get("fields",{}).get("Tên sản phẩm mới","")) == match_values[1]]

    if filtered:
        rid = filtered[0]["record_id"]
        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{table_id}/records/{rid}"
        requests.put(url, headers=headers, json={"fields": fields}, timeout=30)
    else:
        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{table_id}/records"
        requests.post(url, headers=headers, json={"fields": fields}, timeout=30)

_gh_token = None
def _gh_get_token():
    global _gh_token
    r = requests.post("https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}, timeout=10).json()
    _gh_token = r.get("tenant_access_token","")
    return _gh_token

def escj(j):
    return json.dumps(j).replace("'", "'\\''")

def sync_order(order_id, label=""):
    data = sapo(f"orders/{order_id}.json")
    o = data.get('order')
    if not o:
        print(f"  ⚠ Order {order_id} not found")
        return 0
    order_num = '#' + str(o['order_number'])
    c = o.get('customer') or {}
    ship = o.get('shipping_address') or {}
    bill = o.get('billing_address') or {}

    name = ((c.get('last_name') or '') + ' ' + (c.get('first_name') or '')).strip()
    phone = str(o.get('phone') or c.get('phone') or ship.get('phone') or bill.get('phone') or '')
    addr = ', '.join(filter(None, [ship.get(k,'') for k in ['address1','ward','district','city','province']]))
    total = float(o.get('total_price', 0))
    fs = o.get('financial_status', '')
    sts = o.get('status', '')
    dep = 0
    for tx in o.get('transactions') or []:
        if tx.get('kind') in ('sale','capture') and tx.get('status') == 'success':
            dep += float(tx.get('amount', 0))
    if dep == 0 and fs == 'paid': dep = total
    ts = o.get('created_at', '')
    try: dt = int(time.mktime(time.strptime(ts[:19], '%Y-%m-%dT%H:%M:%S'))) * 1000
    except: dt = 0

    count = 0
    for li in o.get('line_items', []):
        price = float(li.get('price', 0))
        ratio = price / total if total > 0 else 0
        pname = (li.get('name') or li.get('title') or '').strip()
        note = (li.get('note') or '').strip()

        # ── DH ──
        dh_fields = {
            'Mã đơn hàng SAPO': order_num, 'Khách hàng': name, 'SĐT': phone,
            'Tên sản phẩm mới': pname, 'Tổng tiền': price,
            'Tiền đã đặt cọc': round(ratio*dep) if dep > 0 else 0,
            'Địa chỉ': addr, 'Trạng thái thanh toán': fs,
            'Trạng thái đơn hàng': sts, 'Ngày đặt hàng(cọc)': dt,
            'Ghi chú': note
        }
        if IS_GH_ACTIONS:
            # GitHub Actions mode: call REST API directly
            _gh_upsert(DH_TABLE, dh_fields, [order_num, pname])
        else:
            cond = json.dumps({"logic":"and","conditions":[["Mã đơn hàng SAPO","==",order_num],["Tên sản phẩm mới","==",pname]]})
            s = lark(f'+record-list --table-id tblZlQNNxxyMb4aS --filter-json \'{escj(cond)}\' --limit 5 --format json')
            rids = s.get('data',{}).get('record_id_list',[]) if s.get('ok') else []
            fj = escj(dh_fields)
            if rids:
                lark(f'+record-upsert --table-id tblZlQNNxxyMb4aS --record-id {rids[0]} --json \'{fj}\'')
            else:
                lark(f'+record-upsert --table-id tblZlQNNxxyMb4aS --json \'{fj}\'')

        # ── SX ──
        sx_fields = {
            'Mã đơn hàng SAPO': order_num, 'Khách hàng': name, 'SĐT': phone,
            'Địa chỉ': addr, 'Ngày đặt': dt,
            'Ghi chú': note if note else '', 'Hẹn giao': None
        }
        if IS_GH_ACTIONS:
            _gh_upsert(SX_TABLE, sx_fields, [order_num])
        else:
            sx_clean = {k:v for k,v in sx_fields.items() if v is not None and v != ''}
            sx_clean['Mã đơn hàng SAPO'] = order_num
            cond_sx = json.dumps({"logic":"and","conditions":[["Mã đơn hàng SAPO","==",order_num]]})
            s_sx = lark(f'+record-list --table-id tblT60XXm76Xi7fz --filter-json \'{escj(cond_sx)}\' --limit 5 --format json')
            rids_sx = s_sx.get('data',{}).get('record_id_list',[]) if s_sx.get('ok') else []
            fj_sx = escj(sx_clean)
            if rids_sx:
                lark(f'+record-upsert --table-id tblT60XXm76Xi7fz --record-id {rids_sx[0]} --json \'{fj_sx}\'')
            else:
                lark(f'+record-upsert --table-id tblT60XXm76Xi7fz --json \'{fj_sx}\'')
        count += 1
    print(f"  ✅ {label or '#'+order_num}: {count} items synced ({name})")
    return count

if __name__ == '__main__':
    total = 0
    if '--help' in sys.argv or '-h' in sys.argv:
        print(__doc__)
        sys.exit(0)
    if '--order' in sys.argv:
        idx = sys.argv.index('--order') + 1
        oid = sys.argv[idx] if idx < len(sys.argv) else ''
        # Search by order number first (SAPO API uses internal ID, not order number)
        res = sapo(f"orders.json?name=%23{oid}&limit=10")
        found = False
        for o in res.get('orders', []):
            if str(o['order_number']) == oid:
                total += sync_order(o['id'], f"#{o['order_number']}")
                found = True
                break
        if not found:
            print(f"  ⚠ Order #{oid} not found in SAPO")
    if '--days' in sys.argv:
        idx = sys.argv.index('--days') + 1
        days = int(sys.argv[idx]) if idx < len(sys.argv) else 1
        since = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(time.time() - days*86400))
        res = sapo(f"orders.json?created_at_min={since}&limit=250")
        orders = res.get('orders', [])
        # Fetch more pages
        page = 1
        while res.get('orders') and len(res.get('orders',[])) == 250:
            page += 1
            res = sapo(f"orders.json?created_at_min={since}&limit=250&page={page}")
            orders += res.get('orders', [])
        print(f"Found {len(orders)} orders in last {days} days")
        for o in orders:
            total += sync_order(o['id'], f"#{o['order_number']}")
    if '--all' in sys.argv:
        page = 1
        all_orders = []
        while True:
            res = sapo(f"orders.json?limit=250&page={page}")
            orders = res.get('orders', [])
            if not orders: break
            all_orders += orders
            page += 1
        print(f"Found {len(all_orders)} total orders")
        for o in all_orders:
            total += sync_order(o['id'], f"#{o['order_number']}")
    if total == 0 and len(sys.argv) > 1:
        # Try as order ID directly
        for arg in sys.argv[1:]:
            if arg.startswith('#'):
                res = sapo(f"orders.json?name={arg}&limit=5")
                for o in res.get('orders', []):
                    total += sync_order(o['id'], arg)
            elif arg.startswith('--'):
                pass  # flag already handled
            else:
                total += sync_order(arg, f"Order #{arg}")
    print(f"\nDone! {total} items synced")
