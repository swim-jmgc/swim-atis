from flask import Flask, request, abort
import os
import requests

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

    text = event.message.text.strip().upper()
    airports = text.replace(",", " ").split()

    try:
        if len(airports) == 0 or len(airports) > 3:
            reply_text = "空港コードは1〜3個まで入力してください\n例:\nRJAA RJTT ROAH"

        elif all(len(code) == 4 and code[:2] in ["RJ", "RO"] for code in airports):
            results = []

            for code in airports:
                result = get_atis(code)

                if "ATISデータなし" in result:
                    results.append(f"[{code}]\n空港コードを入力してください")
                else:
                    results.append(result)

            reply_text = "\n\n----------------\n\n".join(results)

        else:
            reply_text = "空港コードを入力してください\n例:\nRJAA RJTT ROAH"

    except Exception as e:
        reply_text = f"エラー: {str(e)}"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(
                        text=reply_text
                    )
                ]
            )
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
