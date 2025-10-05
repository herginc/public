#
# Flask THSR Parser
#

# ===============================================
# 必須放在所有其他 import 之前
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

# app = Flask(__name__)

# --- Critical Configuration (T2) & Global State ---

# T3: Gunicorn Timeout is 300s (Set in the Start Command on Render)
# T2: Server's internal wait time (The actual Long Polling cycle length)
MAX_WAIT_TIME_SERVER = 298  # 最終設定: 298 秒

# Stores the LATEST event data 
LATEST_EVENT_DATA = {"message": "Server initialized. No event yet."}

# Stores the LATEST active threading.Event object and its response data.
current_waiting_event = None 
current_response_data = None 

# Lock mechanism for all global variables
data_lock = threading.Lock() 

# --- Long Polling Endpoint (T2) ---

@app.route('/poll_for_update', methods=['GET'])
def long_poll_endpoint():
    """
    Blocks for T2 (298 seconds) or until an event/new poll is triggered.
    """
    global current_waiting_event, current_response_data
    
    # 1. 收到請求時立即印出訊息
    print(f"[{time.strftime('%H:%M:%S')}] 🔥 RECEIVED: /poll_for_update request received.")

    # 2. 準備新的 Event
    new_client_event = threading.Event()
    
    # 3. 處理 PREVIOUS 請求 (如果有的話)
    with data_lock:
        if current_waiting_event:
            print(f"[{time.strftime('%H:%M:%S')}] New poll arrived. Waking up the PREVIOUS request (Forced Reconnect).")
            # 設定前一個請求的回覆數據
            current_response_data = {"status": "forced_reconnect", "message": "New poll initiated. Please re-poll immediately."}
            # 喚醒前一個等待中的執行緒
            current_waiting_event.set()
        
        # 4. 儲存目前的 Event 作為 LATEST
        current_waiting_event = new_client_event
        current_response_data = None # 清除這次請求的資料
    
    print(f"[{time.strftime('%H:%M:%S')}] New poll entered WAITING state (Max {MAX_WAIT_TIME_SERVER}s).")

    # 5. 阻塞 (Blocking) - 最多等待 T2 (298s)
    is_triggered = new_client_event.wait(timeout=MAX_WAIT_TIME_SERVER)
    
    # 6. 取得回覆資料並清理狀態
    with data_lock:
        response_payload = current_response_data
        # 只有在 current_waiting_event 確實是這個執行緒時，才清理全局狀態
        if new_client_event == current_waiting_event:
            current_waiting_event = None
            current_response_data = None

    # 7. 檢查結果並回覆
    if response_payload:
        # 路徑 A: 被 trigger_event 喚醒 OR 被 forced_reconnect 喚醒
        return jsonify(response_payload), 200
    
    if is_triggered:
        # 路徑 B: Event 被喚醒，但 response_payload 沒設 (Fallback)
        with data_lock:
            data_to_send = LATEST_EVENT_DATA.copy()
        print(f"[{time.strftime('%H:%M:%S')}] Triggered: Sending LATEST_EVENT_DATA (Fallback).")
        return jsonify({"status": "success", "data": data_to_send}), 200
    else:
        # 路徑 C: Timeout 達到 (T=298s)。伺服器發送計劃性超時回覆。
        print(f"[{time.strftime('%H:%M:%S')}] Timeout reached. Sending 'No Update' response.")
        return jsonify({"status": "timeout", "message": "No new events."}), 200

# --- Event Trigger Endpoint (非阻塞) ---

@app.route('/trigger_event', methods=['POST'])
def trigger_event():
    """
    Called by an external source. Updates state and wakes up the single waiting client instantly.
    """
    data = request.get_json()
    
    with data_lock:
        global LATEST_EVENT_DATA, current_waiting_event, current_response_data
        
        # 1. 立即處理事件資料
        LATEST_EVENT_DATA = data
        
        notifications_sent = 0
        if current_waiting_event:
            # 2. 設定回覆資料並喚醒等待中的 Worker
            current_response_data = {"status": "success", "data": LATEST_EVENT_DATA.copy()}
            current_waiting_event.set() 
            notifications_sent = 1
            
    print(f"[{time.strftime('%H:%M:%S')}] ✅ TRIGGERED: External event received. Waking up {notifications_sent} client.")

    # 3. 立即回覆給觸發者 (非阻塞)
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