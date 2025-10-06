# ===============================================
# app.py (Flask Web Server)
# ===============================================

import gevent.monkey
gevent.monkey.patch_all() # 確保 gevent/gunicorn 能處理多個長連線

import os
import sys
import json
import time
import threading
from datetime import datetime, timezone, timedelta 
from typing import Dict, Any
from zoneinfo import ZoneInfo
from argparse import ArgumentParser

from flask import Flask, request, abort, render_template, jsonify, redirect, url_for

# --- LINE Bot (保持原有結構，與核心功能獨立) ---
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
# (省略 LINE Bot 相關設定和路由，因為它們不影響核心訂票流程)
# -----------------------------------------------

app = Flask(__name__)

# --- 核心配置與全局狀態 ---
MAX_NETWORK_LATENCY = 5
BASE_CLIENT_TIMEOUT = 600 + MAX_NETWORK_LATENCY
CST_TIMEZONE = ZoneInfo('Asia/Taipei') 
GUNICORN_TIMEOUT = 610 # 建議在 Render 設置此值

data_lock = threading.Lock() 

# Long Polling 狀態
current_waiting_event: threading.Event | None = None # 當前等待中的 Client Event
current_response_data: Dict[str, Any] | None = None # 準備回傳給 Long Polling Client 的數據

# 任務佇列文件
TICKET_DIR = "./"
TICKET_REQUEST_FILE = os.path.join(TICKET_DIR, "ticket_requests.json")
TICKET_HISTORY_FILE = os.path.join(TICKET_DIR, "ticket_history.json")

# --- 數據庫操作函式 (基於 JSON 檔案) ---

def load_json(filename):
    if not os.path.exists(filename):
        return []
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"[{time.strftime('%H:%M:%S')}] WARNING: Failed to decode {filename}. Starting with empty list.")
        return []

def save_json(filename, data):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_new_id():
    requests = load_json(TICKET_REQUEST_FILE)
    history = load_json(TICKET_HISTORY_FILE)
    
    max_id = 0
    if requests:
        max_id = max(max_id, max(r.get("id", 0) for r in requests))
    if history:
        max_id = max(max_id, max(h.get("id", 0) for h in history))
        
    return max_id + 1

# --- 時間同步函式 ---

def calculate_server_timeout(client_timeout_s: int, client_timestamp_str: str) -> int:
    """根據 Client 時間戳，計算 T2 (Server 應阻塞的秒數)。"""
    try:
        client_start_time_naive = datetime.fromisoformat(client_timestamp_str)
        client_start_time_cst = client_start_time_naive.replace(tzinfo=CST_TIMEZONE)
        client_start_time_utc = client_start_time_cst.astimezone(timezone.utc)
        
        # T2 應在 T1 結束前 MAX_NETWORK_LATENCY 秒結束
        t2_end_time = client_start_time_utc + timedelta(seconds=client_timeout_s - MAX_NETWORK_LATENCY)
        
        current_server_time = datetime.now(timezone.utc)
        
        time_to_wait = (t2_end_time - current_server_time).total_seconds()
        
        return max(0, int(time_to_wait))
        
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ⚠️ TIME CALC ERROR: {e}. Falling back to default T2={max(0, client_timeout_s - MAX_NETWORK_LATENCY)}s.")
        return max(0, client_timeout_s - MAX_NETWORK_LATENCY)

# --- 任務推送函式 (Long Polling 喚醒) ---

def push_task_to_client(task_data: Dict[str, Any]):
    """將最新的 '待處理' 任務推送給 Long Polling Client。"""
    global current_waiting_event, current_response_data
    
    with data_lock:
        notifications_sent = 0
        if current_waiting_event:
            # 準備回覆 Client 的 payload，告知有任務
            current_response_data = {"status": "success", "data": task_data.copy()}
            current_waiting_event.set() # 喚醒等待中的 Client
            notifications_sent = 1
            
    print(f"[{time.strftime('%H:%M:%S')}] ✅ PUSHED: New booking task (ID: {task_data.get('id')}). Waking up {notifications_sent} client.")


# ===================================================
# --- 路由定義 ---
# ===================================================

# 1. 訂票首頁/提交訂票 (Web Form 入口)
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
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
            # 確保初始沒有訂位代號
            "code": None
        }
        
        # 1. 記錄到待處理佇列
        requests = load_json(TICKET_REQUEST_FILE)
        requests.append(ticket)
        save_json(TICKET_REQUEST_FILE, requests)
        
        # 2. **自動推送任務** 給 Long Polling Client
        push_task_to_client(ticket)
        
        return redirect(url_for("index"))
        
    # GET 請求: 顯示當前待處理任務
    requests = load_json(TICKET_REQUEST_FILE)
    return render_template("index.html", requests=requests)

# 2. 歷史記錄頁面
@app.route("/history.html")
def history():
    history = load_json(TICKET_HISTORY_FILE)
    return render_template("history.html", history=history)

# 3. Long Polling 端點 (Server)
@app.route('/poll_for_update', methods=['POST'])
def long_poll_endpoint():
    global current_waiting_event, current_response_data
    
    client_timeout = BASE_CLIENT_TIMEOUT
    client_timestamp = ""
    
    # 解析 Client 傳入的 Long Polling 參數
    try:
        data = request.get_json()
        client_timeout = data.get('client_timeout_s', BASE_CLIENT_TIMEOUT)
        client_timestamp = data.get('timestamp', "")
    except Exception:
        pass
    
    # 1. 計算 T2
    max_wait_time_server = calculate_server_timeout(client_timeout, client_timestamp)
    print(f"[{time.strftime('%H:%M:%S')}] 🔥 RECEIVED: /poll_for_update. T2 set to {max_wait_time_server}s.")

    # 2. 處理連線競爭，並設置新的 Event
    new_client_event = threading.Event()
    response_payload = None
    with data_lock:
        if current_waiting_event:
            # 強制喚醒舊的 Client，要求它立即重連
            current_response_data = {"status": "forced_reconnect", "message": "New poll initiated. Please re-poll immediately."}
            current_waiting_event.set()
        
        # 設置當前等待的 Client
        current_waiting_event = new_client_event
        current_response_data = None
    
    # 3. 阻塞 (Blocking) - 等待 T2
    is_triggered = new_client_event.wait(timeout=max_wait_time_server)
    
    # 4. 取得回覆資料並清理狀態
    with data_lock:
        response_payload = current_response_data
        # 只有當前 Event 結束時才清空全局變數，防止被強制重連的舊 Event 覆蓋
        if new_client_event == current_waiting_event:
            current_waiting_event = None
            current_response_data = None
            
    # 5. 回覆結果
    if response_payload:
        return jsonify(response_payload), 200
    
    # T2 Timeout 達到
    if not is_triggered:
        print(f"[{time.strftime('%H:%M:%S')}] Timeout reached. Sending 'No Update' response.")
        return jsonify({"status": "timeout", "message": "No new events."}), 200
        
    # 如果是 is_triggered，但 response_payload 為空，則表示是被 forced_reconnect 喚醒，
    # 應該在 data_lock 區塊內收到 response_payload，這裡應為安全檢查。
    return jsonify({"status": "internal_error", "message": "Unknown trigger state."}), 500


# 4. 任務結果回傳端點 (Server 接收 Client 執行結果)
@app.route('/update_status', methods=['POST'])
def update_status():
    """接收 long_polling_client.py 回傳的訂票結果或狀態更新。"""
    
    try:
        data = request.get_json()
        task_id = data.get('task_id')
        status = data.get('status') # 例如: "booked", "failed", "in_progress"
        details = data.get('details', {})
        
        if not task_id or not status:
            return jsonify({"status": "error", "message": "Missing task_id or status"}), 400
        
        task_id = int(task_id) # 確保 ID 類型一致

        with data_lock: # 鎖定，確保 JSON 讀寫安全
            requests = load_json(TICKET_REQUEST_FILE)
            
            found = False
            for ticket in requests:
                if ticket.get("id") == task_id:
                    # 1. 更新任務狀態
                    ticket["status"] = status
                    ticket["result_details"] = details
                    ticket["completion_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    # 將 Client 回傳的訂位代號 (如果有) 更新到主紀錄
                    if details.get("code"):
                        ticket["code"] = details["code"]
                    
                    # 2. 如果完成或失敗，將任務移到 History
                    if status in ["booked", "failed"]:
                        requests.remove(ticket)
                        history_data = load_json(TICKET_HISTORY_FILE)
                        history_data.append(ticket)
                        save_json(TICKET_HISTORY_FILE, history_data)
                    
                    found = True
                    break
            
            # 3. 儲存更新後的任務佇列
            save_json(TICKET_REQUEST_FILE, requests)
        
        if found:
            print(f"[{time.strftime('%H:%M:%S')}] 💾 STATUS UPDATE: Task ID {task_id} updated to '{status}'.")
            return jsonify({"status": "success", "message": f"Task {task_id} status updated to {status}."}), 200
        else:
            return jsonify({"status": "not_found", "message": f"Task {task_id} not found."}), 404
            
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ STATUS UPDATE UNKNOWN ERROR: {e}")
        return jsonify({"status": "internal_error", "message": str(e)}), 500


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        usage='Usage: python ' + __file__ + ' [--port <port>] [--help]'
    )
    arg_parser.add_argument('-p', '--port', default=10000, help='port')
    arg_parser.add_argument('-d', '--debug', default=True, help='debug')
    options = arg_parser.parse_args()

    app.run(debug=options.debug, port=options.port, threaded=True)

# RENDER START COMMAND: gunicorn --worker-class gevent --timeout 610 --bind 0.0.0.0:$PORT app:app 
# RENDER ENV VAR: TZ = Asia/Taipei