#
# Flask THSR Parser
#

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

# T3: Gunicorn Timeout is 60s (Set in the Start Command on Render)
# T2: Server's internal wait time (The actual Long Polling cycle length)
MAX_WAIT_TIME_SERVER = 57  # Experimental setting: 57 seconds

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
    Blocks for T2 (57 seconds) or until an event/new poll is triggered.
    """
    global current_waiting_event, current_response_data
    
    # 1. Log immediately upon request receipt
    print(f"[{time.strftime('%H:%M:%S')}] 🔥 RECEIVED: /poll_for_update request received.")

    # 2. Prepare new Event
    new_client_event = threading.Event()
    
    # 3. Handle the PREVIOUS waiting request (if any)
    with data_lock:
        if current_waiting_event:
            print(f"[{time.strftime('%H:%M:%S')}] New poll arrived. Waking up the PREVIOUS request (Forced Reconnect).")
            # Set response data for the previous request
            current_response_data = {"status": "forced_reconnect", "message": "New poll initiated. Please re-poll immediately."}
            # Wake up the previous waiting thread
            current_waiting_event.set()
        
        # 4. Store the current request's event as the LATEST
        current_waiting_event = new_client_event
        current_response_data = None # Clear data for the new request
    
    print(f"[{time.strftime('%H:%M:%S')}] New poll entered WAITING state (Max {MAX_WAIT_TIME_SERVER}s).")

    # 5. Block (Blocking) - Wait for up to T2 (57s)
    is_triggered = new_client_event.wait(timeout=MAX_WAIT_TIME_SERVER)
    
    # 6. Retrieve response data and clean up state
    with data_lock:
        response_payload = current_response_data
        # Only clear global state if this thread was the latest one waiting
        if new_client_event == current_waiting_event:
            current_waiting_event = None
            current_response_data = None

    # 7. Check outcome and respond
    if response_payload:
        # Path A: Triggered by /trigger_event OR forced_reconnect
        return jsonify(response_payload), 200
    
    if is_triggered:
        # Path B: Fallback for triggered event
        with data_lock:
            data_to_send = LATEST_EVENT_DATA.copy()
        print(f"[{time.strftime('%H:%M:%S')}] Triggered: Sending LATEST_EVENT_DATA (Fallback).")
        return jsonify({"status": "success", "data": data_to_send}), 200
    else:
        # Path C: Timeout reached (T=57s). Send a planned timeout response.
        print(f"[{time.strftime('%H:%M:%S')}] Timeout reached. Sending 'No Update' response.")
        return jsonify({"status": "timeout", "message": "No new events."}), 200

# --- Event Trigger Endpoint (Non-blocking) ---

@app.route('/trigger_event', methods=['POST'])
def trigger_event():
    """
    Called by an external source. Updates state and wakes up the single waiting client instantly.
    """
    data = request.get_json()
    
    with data_lock:
        global LATEST_EVENT_DATA, current_waiting_event, current_response_data
        
        # 1. Immediately process event data
        LATEST_EVENT_DATA = data
        
        notifications_sent = 0
        if current_waiting_event:
            # 2. Set response data and wake up the waiting Worker
            current_response_data = {"status": "success", "data": LATEST_EVENT_DATA.copy()}
            current_waiting_event.set() 
            notifications_sent = 1
            
    print(f"[{time.strftime('%H:%M:%S')}] ✅ TRIGGERED: External event received. Waking up {notifications_sent} client.")

    # 3. Respond immediately to the external trigger
    return jsonify({"status": "event_received", "notifications_sent": notifications_sent}), 200

# RENDER START COMMAND (T3 = 60s): gunicorn --timeout 60 --bind 0.0.0.0:$PORT app:app 
# RENDER ENV VAR: TZ = Asia/Taipei

if __name__ == "__main__":
    arg_parser = ArgumentParser(
        usage='Usage: python ' + __file__ + ' [--port <port>] [--help]'
    )
    arg_parser.add_argument('-p', '--port', default=10000, help='port')
    arg_parser.add_argument('-d', '--debug', default=True, help='debug')
    options = arg_parser.parse_args()

    app.run(debug=options.debug, port=options.port, threaded=True)
    # app.run(host='0.0.0.0', port=5000, threaded=True)