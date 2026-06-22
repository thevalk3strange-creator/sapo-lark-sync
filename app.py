"""Minimal test - just checks it runs"""
import os, json, requests
from flask import Flask, jsonify
app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"status": "ok"})

@app.route("/sync")
def sync():
    # Test: can we write 1 record to staging?
    r = requests.post("https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": os.environ["LARK_APP_ID"], "app_secret": os.environ["LARK_APP_SECRET"]}, timeout=10)
    t = r.json().get("tenant_access_token", "")
    h = {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}
    f = {"Mã đơn hàng SAPO": "#DEPLOY-TEST", "Khách hàng": "Render Deploy Test"}
    r2 = requests.post(f"https://open.larksuite.com/open-apis/bitable/v1/apps/{os.environ['BASE_TOKEN']}/tables/tbloP45vaT4I2mwF/records",
        headers=h, json={"fields": f}, timeout=10)
    return jsonify({"code": r2.status_code, "lark_ok": r2.json().get("code") == 0})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
