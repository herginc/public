# =======================================================
# app.py (Flask Web Server) - 最終任務持久化同步版本
# =======================================================

import gevent.monkey
gevent.monkey.patch_all()

import os
import sys
import json
import time
import threading
from datetime import datetime, timezone, timedelta 
from typing import Dict, Any
from zoneinfo import ZoneInfo
from argparse import ArgumentParser

# 修正 Render 環境下的重定向問題
from werkzeug.middleware.proxy_fix import ProxyFix 
from flask import Flask, request, abort, render_template, jsonify, render_template_string

# --- LINE Bot (保持原有結構，與核心功能獨立) ---
# (省略 LINE Bot 相關設定和路由)
# -----------------------------------------------

app = Flask(__name__)
# 啟用 ProxyFix 修正 Render/Gunicorn 環境下的 URL 重定向問題
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1) 

# --- 核心配置與全局狀態 ---
MAX_NETWORK_LATENCY = 5
BASE_CLIENT_TIMEOUT = 600 + MAX_NETWORK_LATENCY
CST_TIMEZONE = ZoneInfo('Asia/Taipei') 

data_lock = threading.Lock() 
current_waiting_event: threading.Event | None = None 
current_response_data: Dict[str, Any] | None = None 

# 任務佇列文件
TICKET_DIR = "./"
TICKET_REQUEST_FILE = os.path.join(TICKET_DIR, "ticket_requests.json")
TICKET_HISTORY_FILE = os.path.join(TICKET_DIR, "ticket_history.json")

# --- 數據庫操作函式 (保持不變) ---
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

def calculate_server_timeout(client_timeout_s: int, client_timestamp_str: str) -> int:
    try:
        client_start_time_naive = datetime.fromisoformat(client_timestamp_str)
        client_start_time_cst = client_start_time_naive.replace(tzinfo=CST_TIMEZONE)
        client_start_time_utc = client_start_time_cst.astimezone(timezone.utc)
        t2_end_time = client_start_time_utc + timedelta(seconds=client_timeout_s - MAX_NETWORK_LATENCY)
        current_server_time = datetime.now(timezone.utc)
        time_to_wait = (t2_end_time - current_server_time).total_seconds()
        return max(0, int(time_to_wait))
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ⚠️ TIME CALC ERROR: {e}. Falling back to default T2={max(0, client_timeout_s - MAX_NETWORK_LATENCY)}s.")
        return max(0, client_timeout_s - MAX_NETWORK_LATENCY)

def push_task_to_client(task_data: Dict[str, Any]):
    global current_waiting_event, current_response_data
    with data_lock:
        notifications_sent = 0
        if current_waiting_event:
            # 被喚醒的客戶端將收到單一新任務
            current_response_data = {"status": "success", "data": task_data.copy()}
            current_waiting_event.set() 
            notifications_sent = 1
    print(f"[{time.strftime('%H:%M:%S')}] ✅ PUSHED: New booking task (ID: {task_data.get('id')}). Waking up {notifications_sent} client.")


# ===================================================
# --- 路由定義 ---
# ===================================================

# 1. 訂票首頁 (GET)
@app.route("/", methods=["GET"])
def index():
    requests = load_json(TICKET_REQUEST_FILE)
    return render_template("index.html", requests=requests)

# 2. JSON API 訂票提交路由
@app.route("/api/submit_ticket", methods=["POST"])
def api_submit_ticket():
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"status": "error", "message": "Missing JSON data in request body."}), 400

        required_fields = ["name", "id_number", "train_no", "travel_date", "from_station", "from_time", "to_station", "to_time"]
        for field in required_fields:
            if not data.get(field):
                 return jsonify({"status": "error", "message": f"Missing required field: {field}"}), 400
                 
        ticket = {
            "id": get_new_id(),
            "status": "待處理",
            "order_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "name": data["name"],
            "id_number": data["id_number"],
            "train_no": data["train_no"],
            "travel_date": data["travel_date"],
            "from_station": data["from_station"],
            "from_time": data["from_time"],
            "to_station": data["to_station"],
            "to_time": data["to_time"],
            "code": None
        }
        
        # 1. 記錄到持久化佇列
        requests = load_json(TICKET_REQUEST_FILE)
        requests.append(ticket)
        save_json(TICKET_REQUEST_FILE, requests)
        
        # 2. 自動推送通知（如果 client 正在等候）
        push_task_to_client(ticket)
        
        print(f"[{time.strftime('%H:%M:%S')}] 📝 JSON SUBMIT: New task ID {ticket['id']} created.")
        return jsonify({
            "status": "success", 
            "message": "Booking task submitted successfully.",
            "task_id": ticket["id"]
        }), 201 

    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ JSON SUBMIT UNKNOWN ERROR: {e}")
        return jsonify({"status": "internal_error", "message": str(e)}), 500


# 3. 歷史記錄頁面 (保持不變)
@app.route("/history.html")
def history():
    history = load_json(TICKET_HISTORY_FILE)
    return render_template("history.html", history=history)

# 4. AJAX 短輪詢路由 (保持不變)
@app.route("/api/pending_table", methods=["GET"])
def api_pending_table():
    requests = load_json(TICKET_REQUEST_FILE)
    
    template_str = """
    {% for r in requests %}
    <tr>
        <td>{{ r.id }}</td>
        <td>{{ r.status }}</td>
        <td>{{ r.order_date }}</td>
        <td>{{ r.name }}</td>
        <td>{{ r.id_number }}</td>
        <td>{{ r.train_no }}</td>
        <td>{{ r.travel_date }}</td>
        <td>{{ r.from_station }}</td>
        <td>{{ r.from_time }}</td>
        <td>{{ r.to_station }}</td>
        <td>{{ r.to_time }}</td>
        <td>{{ r.code if r.code else "" }}</td>
    </tr>
    {% else %}
    <tr>
        <td colspan="12">目前沒有待處理的訂票任務。</td>
    </tr>
    {% endfor %}
    """
    
    rendered_html = render_template_string(template_str, requests=requests)
    return rendered_html, 200

# 5. Long Polling 端點 (**已實現持久化同步**)
@app.route('/poll_for_update', methods=['POST'])
def long_poll_endpoint():
    global current_waiting_event, current_response_data
    client_timeout = BASE_CLIENT_TIMEOUT
    client_timestamp = ""
    try:
        data = request.get_json()
        client_timeout = data.get('client_timeout_s', BASE_CLIENT_TIMEOUT)
        client_timestamp = data.get('timestamp', "")
    except Exception:
        pass
    
    max_wait_time_server = calculate_server_timeout(client_timeout, client_timestamp)
    print(f"[{time.strftime('%H:%M:%S')}] 🔥 RECEIVED: /poll_for_update. T2 set to {max_wait_time_server}s.")

    # --- 關鍵修改點：檢查待處理任務佇列 (同步邏輯) ---
    # 確保在進入阻塞狀態前，先檢查是否有 Client 錯過的任務
    requests = load_json(TICKET_REQUEST_FILE)
    if requests:
        # 如果佇列中有任務，立即回傳所有待處理任務
        print(f"[{time.strftime('%H:%M:%S')}] 🚨 WAITING TASKS FOUND: Returning {len(requests)} pending tasks immediately.")
        # 回傳所有任務，客戶端必須自行判斷哪些任務是它還沒處理過的。
        return jsonify({
            "status": "initial_sync",
            "message": "Found pending tasks in queue.",
            "data": requests.copy() # 將整個任務列表回傳
        }), 200
    # --- 關鍵修改點結束 ---

    # 如果佇列為空，進入正常 Long Polling 阻塞流程
    new_client_event = threading.Event()
    response_payload = None
    with data_lock:
        if current_waiting_event:
            # 如果有其他客戶端正在等候，強制它重新輪詢
            current_response_data = {"status": "forced_reconnect", "message": "New poll initiated. Please re-poll immediately."}
            current_waiting_event.set()
        
        current_waiting_event = new_client_event
        current_response_data = None
    
    # 阻塞等待新任務或超時
    is_triggered = new_client_event.wait(timeout=max_wait_time_server)
    
    with data_lock:
        response_payload = current_response_data
        if new_client_event == current_waiting_event:
            current_waiting_event = None
            current_response_data = None
            
    if response_payload:
        return jsonify(response_payload), 200
    
    if not is_triggered:
        print(f"[{time.strftime('%H:%M:%S')}] Timeout reached. Sending 'No Update' response.")
        return jsonify({"status": "timeout", "message": "No new events."}), 200
        
    return jsonify({"status": "internal_error", "message": "Unknown trigger state."}), 500


# 6. 任務結果回傳端點 (保持不變)
@app.route('/update_status', methods=['POST'])
def update_status():
    # ... (程式碼保持不變) ...
    try:
        data = request.get_json()
        task_id = data.get('task_id')
        status = data.get('status') 
        details = data.get('details', {})
        
        if not task_id or not status:
            return jsonify({"status": "error", "message": "Missing task_id or status"}), 400
        
        task_id = int(task_id)

        with data_lock:
            requests = load_json(TICKET_REQUEST_FILE)
            found = False
            for ticket in requests:
                if ticket.get("id") == task_id:
                    ticket["status"] = status
                    ticket["result_details"] = details
                    ticket["completion_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    if details.get("code"):
                        ticket["code"] = details["code"]
                    
                    if status in ["booked", "failed"]:
                        requests.remove(ticket)
                        history_data = load_json(TICKET_HISTORY_FILE)
                        history_data.append(ticket)
                        save_json(TICKET_HISTORY_FILE, history_data)
                    
                    found = True
                    break
            
            save_json(TICKET_REQUEST_FILE, requests)
        
        if found:
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