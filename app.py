from flask import Flask, request, abort
import os
import requests
from datetime import datetime, timedelta

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError

app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = os.environ["CHANNEL_ACCESS_TOKEN"]
CHANNEL_SECRET = os.environ["CHANNEL_SECRET"]

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

@app.route("/")
def home():
    return "SWIM LINE BOT OK"

@app.route("/test/<icao>")
def test_atis(icao):
    icao = icao.upper()
    result = get_atis(icao)
    return result.replace("\n", "<br>")

def get_atis(icao):
    swim_id = os.environ["SWIM_ID"]
    swim_password = os.environ["SWIM_PASSWORD"]

    session = requests.Session()

    # 1. ログインしてCookie取得
    login_url = "https://top.swim.mlit.go.jp/swim/webapi/login"
    login_payload = {
        "id": swim_id,
        "password": swim_password
    }

    login_res = session.post(
        login_url,
        json=login_payload,
        headers={"Content-Type": "application/json"},
        timeout=10
    )

    if login_res.status_code != 200:
        return f"SWIMログイン失敗: HTTP {login_res.status_code}"

    # 2. ATIS取得
    atis_url = "https://web.swim.mlit.go.jp/f2atrq/web/FLV402001"

    atis_res = session.get(
        atis_url,
        params={
            "location": icao,
            "dispcnt": "1"
        },
        headers={
            "Cookie": login_res.headers.get("Set-Cookie", "")
        },
        timeout=10
    )

    if atis_res.status_code != 200:
        return f"HTTP={atis_res.status_code}"

    data = atis_res.json()
        
    error_code = data["error_info"][0]["error_code"]

    if error_code != "0":
        return f"ATIS取得エラー: code={error_code}"

    atis_list = data["data"][0].get("atisInfo", [])

    if not atis_list:
        return f"{icao} のATISデータなし"

    atis = atis_list[0]
    atis = atis.replace("¥n", "\n").replace("\\n", "\n")
    atis = atis.replace("¥r", "").replace("\\r", "")

    return f"[{icao} ATIS]\n\n{atis}"
    
def get_notam(icao):
    swim_id = os.environ["SWIM_ID"]
    swim_password = os.environ["SWIM_PASSWORD"]

    session = requests.Session()

    login_url = "https://top.swim.mlit.go.jp/swim/webapi/login"

    login_payload = {
        "id": swim_id,
        "password": swim_password
    }

    login_res = session.post(
        login_url,
        json=login_payload,
        headers={"Content-Type": "application/json"},
        timeout=10
    )

    if login_res.status_code != 200:
        return f"SWIMログイン失敗: HTTP {login_res.status_code}"

    notam_url = "https://web.swim.mlit.go.jp/f2dnrq/web/search"
    valid_end = (datetime.utcnow() + timedelta(days=30)).strftime("%Y%m%d%H%M")

    notam_res = session.get(
        notam_url,
        params={
            "userId": swim_id,
            "location": icao,
            "display": "0",
            "validDatetimeEnd": valid_end
        },
        
        headers={
            "Cookie": login_res.headers.get("Set-Cookie", "")
        },
        timeout=20
    )

    if notam_res.status_code != 200:
        return f"NOTAM取得失敗 HTTP={notam_res.status_code}"

    data = notam_res.json()

    error_code = str(data["error_info"]["error_code"])

    if error_code == "1":
        return f"[{icao} NOTAM]\n\n該当NOTAMなし"

    if error_code != "0":
        return f"[{icao} NOTAM]\n\nerror_code={error_code}"

    return str(data)

@app.route("/callback", methods=["POST"])

def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text.strip().upper()
    parts = user_text.replace(",", " ").split()

    try:
        if len(parts) == 0:
            reply_text = "空港コードを入力してください。\n例：RJSS"

        elif len(parts) > 2:
            reply_text = "入力形式を確認してください。\n例：RJSS / RJSS NOTAM / RJSS ALL"

        else:
            airport_code = parts[0]
            mode = "ATIS"

            if len(parts) == 2:
                mode = parts[1]

            if len(airport_code) != 4:
                reply_text = "空港コードを4文字で入力してください。\n例：RJSS"

            elif airport_code[:2] not in ["RJ", "RO"]:
                reply_text = "空港コードを入力してください。\n例：RJSS"

            elif mode == "ATIS":
                reply_text = get_atis(airport_code)

            elif mode == "NOTAM":
                reply_text = get_notam(airport_code)

            elif mode == "ALL":
                atis_text = get_atis(airport_code)
                notam_text = get_notam(airport_code)
                reply_text = atis_text + "\n\n----------------\n\n" + notam_text

            else:
                reply_text = "入力形式を確認してください。\n例：RJSS / RJSS NOTAM / RJSS ALL"

    except Exception as e:
        print("ERROR =", repr(e))
        reply_text = f"エラー: {str(e)}"
               
    if len(reply_text) > 4800:
        reply_text = reply_text[:4800] + "\n\n※文字数制限のため途中まで表示しています。"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(text=reply_text)
                ]
            )
        )
