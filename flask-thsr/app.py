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

import requests
import time
import sys
from datetime import datetime
from typing import Dict, Any

# app = Flask(__name__)

# --- Configuration ---

SERVER_URL = "https://flask-thsr.onrender.com/poll_for_update" 
# T1: Client Base Timeout (600s)
CLIENT_TIMEOUT = 600 
# RETRY_DELAY (60s) 僅用於 requests.exceptions.RequestException
RETRY_DELAY = 60 

# --- Long Polling Loop ---

def run_long_polling():
    
    print(f"[{time.strftime('%H:%M:%S')}] Starting client. Cycle: {CLIENT_TIMEOUT - 1}s max.")
    
    while True:
        
        # 1. 記錄請求開始時間 (用於 POST 數據)
        request_start_time = datetime.now()
        
        print(f"[{time.strftime('%H:%M:%S')}] Client initiating request (POST). Max patience: {CLIENT_TIMEOUT}s.")
        
        # 2. 準備 POST 數據
        post_data: Dict[str, Any] = {
            "client_timeout_s": CLIENT_TIMEOUT,
            # 傳送 ISO 格式的 timestamp 給 Server 進行 T2 計算
            "timestamp": request_start_time.isoformat() 
        }
        
        # --- Long Poll Request ---
        try:
            # 3. 發送 HTTP POST 請求，使用 T1 = 600 秒超時
            response = requests.post(SERVER_URL, json=post_data, timeout=CLIENT_TIMEOUT) 
            
            # --- Status Code Handling ---
            if response.status_code == 404:
                print("\n" + "="*70)
                print(f"[{time.strftime('%H:%M:%S')}] **FATAL ERROR: Server returned 404 (Not Found).**")
                print("Program terminated due to incorrect path configuration.")
                print("="*70 + "\n")
                sys.exit(1)

            elif response.status_code == 200:
                data = response.json()
                status = data.get("status")

                if status == "success":
                    # Instant notification received (T < T2)
                    print("="*50)
                    print(f"[{time.strftime('%H:%M:%S')}] **🚀 RECEIVED INSTANT NOTIFICATION!**")
                    print(f"Data: {data.get('data')}")
                    print("="*50)
                
                else:  # Handles "timeout" and "forced_reconnect"
                    print(f"[{time.strftime('%H:%M:%S')}] Connection ended ({status}). Initiating next poll immediately.")
                
            else:
                # Other server errors (500, 502, etc.)
                print(f"[{time.strftime('%H:%M:%S')}] Server returned unexpected status code: {response.status_code}. Initiating next poll immediately.")
        
        # --- Exception Handling ---
        except requests.exceptions.Timeout:
            # T1 Timeout (600s) 發生，表示 T3 (Gunicorn) 超時可能先發生了
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ UNEXPECTED TIMEOUT: Client request timed out ({CLIENT_TIMEOUT}s reached). Initiating next poll immediately.")
            
        except requests.exceptions.RequestException as e:
            # 連線失敗、DNS 錯誤等硬性網路問題
            print(f"[{time.strftime('%H:%M:%S')}] ⛔ CONNECTION ERROR: {e}. Retrying in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)
            
        except Exception as e:
            # 其他所有未知錯誤
            print(f"[{time.strftime('%H:%M:%S')}] ❌ UNKNOWN ERROR: {e}. Initiating next poll immediately.")


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