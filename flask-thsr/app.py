#
# Flask THSR Parser
#

# ===============================================
# 必須放在所有其他 import 之前，解決 MonkeyPatchWarning
import gevent.monkey
gevent.monkey.patch_all()
# ===============================================

import os
import sys
from argparse import ArgumentParser

from flask import Flask, request, abort, render_template, jsonify, redirect, url_for
import json
from datetime import datetime

import time
import threading

from linebot.v3 import (
     WebhookHandler
)

from linebot.v3.exceptions import (
    InvalidSignatureError
)

from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
)

from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)

app = Flask(__name__)

# get channel_secret and channel_access_token from your environment variable
channel_secret = os.getenv('LINE_CHANNEL_SECRET', None)
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', None)

if channel_secret is None:
    print('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)

if channel_access_token is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    sys.exit(1)


handler = WebhookHandler(channel_secret)
configuration = Configuration(access_token=channel_access_token)


@app.errorhandler(404)
def page_not_found(error):
    print(f"[{error}] page not found or undefined route")
    return 'page not found', 404


@app.route("/echo", methods=['POST'])
def cb_echo():
    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    print(f"--> POST data = {body}")
    # sys.stdout.flush()
    return f'[echo]: {body}', 200


@app.route("/callback", methods=['POST'])
def line_webhook():
    print("receive a LINE bot webhook message")

    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    print(f"Request body: {body}")
    # sys.stdout.flush()

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK', 200


@handler.add(MessageEvent, message=TextMessageContent)
def message_text(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=event.message.text)]
            )
        )


TICKET_DIR = "./"
TICKET_REQUEST_FILE = os.path.join(TICKET_DIR, "ticket_requests.json")
TICKET_HISTORY_FILE = os.path.join(TICKET_DIR, "ticket_history.json")

def load_json(filename):
    if not os.path.exists(filename):
        return []
    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(filename, data):
    # Ensure the directory exists before saving
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_new_id():
    requests = load_json(TICKET_REQUEST_FILE)
    if not requests:
        return 1
    return max(r["id"] for r in requests) + 1

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # Receive new ticket request
        data = request.form
        ticket = {
            "id": get_new_id(),
            "status": "待處理",
            "order_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "name": data.get("name"),
            "id_number": data.get("id_number"),
            "train_no": data.get("train_no"),
            "travel_date": data.get("travel_date"),
            "from_station": data.get("from_station"),
            "from_time": data.get("from_time"),
            "to_station": data.get("to_station"),
            "to_time": data.get("to_time"),
        }
        requests = load_json(TICKET_REQUEST_FILE)
        requests.append(ticket)
        save_json(TICKET_REQUEST_FILE, requests)
        return redirect(url_for("index"))
    # Show current ticket requests
    requests = load_json(TICKET_REQUEST_FILE)
    return render_template("index.html", requests=requests)

@app.route("/history.html")
def history():
    history = load_json(TICKET_HISTORY_FILE)
    return render_template("history.html", history=history)

@app.route("/api/ticket_requests", methods=["GET"])
def api_ticket_requests():
    # For external system polling
    requests = load_json(TICKET_REQUEST_FILE)
    pending = [r for r in requests if r["status"] == "待處理"]
    return jsonify(pending)


# app.py - Web Server Code (Running on Render/Gunicorn)

from flask import Flask, request, jsonify
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Any

# app = Flask(__name__)

# --- Critical Configuration & Global State ---

# T3: Gunicorn Timeout. 必須大於 T1 (600s)。
GUNICORN_TIMEOUT = 601 
# T1: Client Base Timeout (預期從 Client POST 數據中取得，預設為 600s)
BASE_CLIENT_TIMEOUT = 600 

# 鎖定機制
data_lock = threading.Lock() 

# 異步 Long Polling 狀態
LATEST_EVENT_DATA: Dict[str, Any] = {"message": "Server initialized. No event yet."}
current_waiting_event: threading.Event | None = None 
current_response_data: Dict[str, Any] | None = None 

# --- 精確計算 T2 邏輯 ---

def calculate_server_timeout(client_timeout_s: int, client_timestamp_str: str) -> int:
    """
    根據 Client 傳入的超時時間和請求開始時間，計算 T2 (Server 應阻塞的秒數)。

    T2 的結束點 = Client 請求時間點 + Client Timeout (T1) - 1 秒
    T2 = T2 結束點 - 當前時間點
    """
    
    try:
        # 1. 解析 Client 請求時間 (假設為 ISO 格式)
        # 由於 Client 沒有指定時區，我們暫時將其視為 UTC 以避免本地時區混亂
        client_start_time = datetime.fromisoformat(client_timestamp_str.replace('Z', '+00:00'))
        
        # 2. 計算 T2 必須結束的目標時間點 (T1 結束前 1 秒)
        # T2_end_time = client_start_time + T1 - 1s
        t2_end_time = client_start_time + timedelta(seconds=client_timeout_s - 1)
        
        # 3. 獲取當前 Server 的時間
        current_server_time = datetime.now(timezone.utc)
        
        # 4. 計算 Server 應阻塞的剩餘秒數 (T2)
        # T2 = T2_end_time - current_server_time
        time_to_wait = (t2_end_time - current_server_time).total_seconds()
        
        # 規則: T2 必須 >= 0 
        return max(0, int(time_to_wait))
        
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ⚠️ TIME CALC ERROR: {e}. Falling back to default T2=599s.")
        # 如果解析失敗，則使用預設 T1-1 的安全值
        return max(0, client_timeout_s - 1)

# --- Long Polling Endpoint (使用 HTTP POST) ---

@app.route('/poll_for_update', methods=['POST'])
def long_poll_endpoint():
    """
    接收 Client POST 請求，計算 T2 並阻塞。
    """
    global current_waiting_event, current_response_data
    
    client_timeout = BASE_CLIENT_TIMEOUT
    client_timestamp = ""
    
    # 嘗試從 POST 數據中獲取 Client 資訊
    try:
        data = request.get_json()
        client_timeout = data.get('client_timeout_s', BASE_CLIENT_TIMEOUT)
        client_timestamp = data.get('timestamp', "")
        
        if not isinstance(client_timeout, int) or client_timeout < 1:
             client_timeout = BASE_CLIENT_TIMEOUT
    except Exception:
        pass
    
    # 1. 計算 T2 (精確計算)
    max_wait_time_server = calculate_server_timeout(client_timeout, client_timestamp)
    
    # 2. 記錄收到請求
    print(f"[{time.strftime('%H:%M:%S')}] 🔥 RECEIVED: /poll_for_update (T1={client_timeout}s, Ts={client_timestamp}). T2 set to {max_wait_time_server}s.")

    # 3. 準備新的 Event (與之前版本相同)
    new_client_event = threading.Event()
    with data_lock:
        if current_waiting_event:
            # 強制喚醒前一個請求
            current_response_data = {"status": "forced_reconnect", "message": "New poll initiated. Please re-poll immediately."}
            current_waiting_event.set()
        
        current_waiting_event = new_client_event
        current_response_data = None
    
    print(f"[{time.strftime('%H:%M:%S')}] New poll entered WAITING state (Max {max_wait_time_server}s).")

    # 4. 阻塞 (Blocking) - 等待 T2
    is_triggered = new_client_event.wait(timeout=max_wait_time_server)
    
    # 5. 取得回覆資料並清理狀態 (與之前版本相同)
    with data_lock:
        response_payload = current_response_data
        if new_client_event == current_waiting_event:
            current_waiting_event = None
            current_response_data = None

    # 6. 檢查結果並回覆
    if response_payload:
        return jsonify(response_payload), 200
    
    if is_triggered:
        # Fallback (不太可能發生)
        with data_lock:
            data_to_send = LATEST_EVENT_DATA.copy()
        return jsonify({"status": "success", "data": data_to_send}), 200
    else:
        # T2 Timeout 達到，Server 主動斷線
        print(f"[{time.strftime('%H:%M:%S')}] Timeout reached. Sending 'No Update' response.")
        return jsonify({"status": "timeout", "message": "No new events."}), 200

# --- Event Trigger Endpoint (保持不變) ---
@app.route('/trigger_event', methods=['POST'])
def trigger_event():
    data = request.get_json()
    
    with data_lock:
        global LATEST_EVENT_DATA, current_waiting_event, current_response_data
        
        LATEST_EVENT_DATA = data
        notifications_sent = 0
        if current_waiting_event:
            current_response_data = {"status": "success", "data": LATEST_EVENT_DATA.copy()}
            current_waiting_event.set() 
            notifications_sent = 1
            
    print(f"[{time.strftime('%H:%M:%S')}] ✅ TRIGGERED: External event received. Waking up {notifications_sent} client.")
    return jsonify({"status": "event_received", "notifications_sent": notifications_sent}), 200


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        usage='Usage: python ' + __file__ + ' [--port <port>] [--help]'
    )
    arg_parser.add_argument('-p', '--port', default=10000, help='port')
    arg_parser.add_argument('-d', '--debug', default=True, help='debug')
    options = arg_parser.parse_args()

    app.run(debug=options.debug, port=options.port, threaded=True)
    # app.run(host='0.0.0.0', port=5000, threaded=True)

# RENDER START COMMAND (T3 = 300s): gunicorn --worker-class gevent --timeout 300 --bind 0.0.0.0:$PORT app:app 
# RENDER ENV VAR: TZ = Asia/Taipei