# =======================================================
# app.py (Flask Web Server) - 已更新表格數據格式
# =======================================================

import gevent.monkey
gevent.monkey.patch_all()

import os
import sys
import json
import time
import threading
from datetime import datetime, timezone, timedelta 
from typing import Dict, Any, List
from zoneinfo import ZoneInfo
from argparse import ArgumentParser

from werkzeug.middleware.proxy_fix import ProxyFix 
from flask import Flask, request, abort, render_template, jsonify, render_template_string

# ... (省略 LINE Bot 相關設定) ...

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1) 

# --- 核心配置與全局狀態 (保持不變) ---
MAX_NETWORK_LATENCY = 5
BASE_CLIENT_TIMEOUT = 600 + MAX_NETWORK_LATENCY
CST_TIMEZONE = ZoneInfo('Asia/Taipei') 

data_lock = threading.Lock() 
current_waiting_event: threading.Event | None = None 
current_response_data: Dict[str, Any] | None = None 

TICKET_DIR = "./"
TICKET_REQUEST_FILE = os.path.join(TICKET_DIR, "ticket_requests.json")
TICKET_HISTORY_FILE = os.path.join(TICKET_DIR, "ticket_history.json")

PASSENGER_DIR = "./json"
PASSENGER_FILE = os.path.join(PASSENGER_DIR, "passenger_data.json")

# --- 數據庫操作函式 (保持不變) ---
def load_json(filename):
    if not os.path.exists(filename):
        return []
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
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

def get_new_passenger_id():
    passengers = load_json(PASSENGER_FILE)
    if not passengers:
        return 1
    return max(p["id"] for p in passengers) + 1

# --- 時間同步函式 (保持不變) ---
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
            current_response_data = {"status": "success", "data": task_data.copy()}
            current_waiting_event.set() 
            notifications_sent = 1
    print(f"[{time.strftime('%H:%M:%S')}] ✅ PUSHED: New booking task (ID: {task_data.get('id')}). Waking up {notifications_sent} client.")

# --- 新增：數據格式化函式 ---
def format_ticket_data(ticket: Dict[str, Any]) -> Dict[str, Any]:
    """將單筆訂票數據格式化為前端表格所需的精簡格式"""
    
    # 訂票日期 (Order Date): 格式 'hh:mm'
    try:
        # 假設 order_date 格式為 "YYYY-MM-DD HH:MM:SS"
        order_dt = datetime.strptime(ticket.get("order_date"), "%Y-%m-%d %H:%M:%S")
        formatted_order_date = order_dt.strftime("%H:%M")
    except Exception:
        formatted_order_date = "N/A"
        
    # 乘車日期 (Travel Date): 格式 'MM/DD'
    try:
        # 假設 travel_date 格式為 "YYYY-MM-DD"
        travel_dt = datetime.strptime(ticket.get("travel_date"), "%Y-%m-%d")
        formatted_travel_date = travel_dt.strftime("%m/%d")
    except Exception:
        formatted_travel_date = "N/A"

    # 組合時間地點資訊
    from_info = f"{ticket.get('from_station', 'N/A')} {ticket.get('from_time', 'N/A')}"
    to_info = f"{ticket.get('to_station', 'N/A')} {ticket.get('to_time', 'N/A')}"
    
    # 創建新的精簡字典
    formatted_ticket = {
        "id": ticket["id"],
        "status": ticket.get("status"), 
        "result": ticket.get("status", "N/A"),
        "code": ticket.get("code", "N/A"), 
        "name": ticket.get("name", "N/A"),
        "id_number": ticket.get("id_number", "N/A"), # 雖然表格不顯示，但保留原始數據
        "train_no": ticket.get("train_no", "N/A"),
        "formatted_order_date": formatted_order_date,
        "formatted_travel_date": formatted_travel_date,
        "from_info": from_info,
        "to_info": to_info,
    }
    return formatted_ticket


# ===================================================
# --- 路由定義 ---
# ===================================================

# 1. 訂票首頁 (GET)
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        data = request.form
        # ...原本的訂票資料處理...
        ticket = {
            "id": get_new_id(),
            "status": "訂票待處理",
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
        # 新增：檢查是否需要新增乘客資料
        add_passenger_if_new(ticket["name"], ticket["id_number"])
        return redirect(url_for("index"))
    requests = load_json(TICKET_REQUEST_FILE)
    # 雖然 index.html 的表格內容由 AJAX 獲取，但這裡仍需傳遞數據以供初始渲染
    formatted_requests = [format_ticket_data(r) for r in requests]
    return render_template("index.html", requests=formatted_requests)

# 2. JSON API 訂票提交路由 (保持不變)
@app.route("/api/submit_ticket", methods=["POST"])
def api_submit_ticket():
    # ... (程式碼保持不變) ...
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
        
        requests = load_json(TICKET_REQUEST_FILE)
        requests.append(ticket)
        save_json(TICKET_REQUEST_FILE, requests)
        
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


# 3. 歷史記錄頁面 (已修改：應用格式化)
@app.route("/history.html")
def history():
    history_data = load_json(TICKET_HISTORY_FILE)
    
    # 應用格式化函式，將格式化後的數據傳遞給 history.html
    formatted_history = [format_ticket_data(h) for h in history_data]
    
    return render_template("history.html", history=formatted_history)

# 4. AJAX 短輪詢路由 (已修改：使用格式化數據和新模板)
@app.route("/api/pending_table", methods=["GET"])
def api_pending_table():
    requests = load_json(TICKET_REQUEST_FILE)
    
    # 應用格式化函式
    formatted_requests = [format_ticket_data(r) for r in requests]
    
    # 新的模板字串，配合 index.html 的新表頭
    template_str = """
    {% for r in formatted_requests %}
    <tr>
        <td>{{ r.id }}</td>
        <td>{{ r.status }}</td>
        <td>{{ r.formatted_order_date }}</td>
        <td>{{ r.name }}</td>
        <td>{{ r.train_no }}</td>
        <td>{{ r.formatted_travel_date }}</td>
        <td>{{ r.from_info }}</td>
        <td>{{ r.to_info }}</td>
    </tr>
    {% else %}
    <tr>
        <td colspan="8">目前沒有待處理的訂票任務。</td>
    </tr>
    {% endfor %}
    """
    
    rendered_html = render_template_string(template_str, formatted_requests=formatted_requests)
    return rendered_html, 200

# 5. Long Polling 端點 (保持不變)
@app.route('/poll_for_update', methods=['POST'])
def long_poll_endpoint():
    # ... (程式碼保持不變) ...
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

    requests = load_json(TICKET_REQUEST_FILE)
    if requests:
        print(f"[{time.strftime('%H:%M:%S')}] 🚨 WAITING TASKS FOUND: Returning {len(requests)} pending tasks immediately.")
        return jsonify({
            "status": "initial_sync",
            "message": "Found pending tasks in queue.",
            "data": requests.copy() 
        }), 200

    new_client_event = threading.Event()
    response_payload = None
    with data_lock:
        if current_waiting_event:
            current_response_data = {"status": "forced_reconnect", "message": "New poll initiated. Please re-poll immediately."}
            current_waiting_event.set()
        
        current_waiting_event = new_client_event
        current_response_data = None
    
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


def add_passenger_if_new(name, id_number):
    passengers = load_json(PASSENGER_FILE)
    for p in passengers:
        if p["name"] == name and p["id_number"] == id_number:
            return  # Already exists
    # Add new passenger with default identity
    new_passenger = {
        "id": get_new_passenger_id(),
        "name": name,
        "id_number": id_number,
        "identity": "一般"
    }
    passengers.append(new_passenger)
    save_json(PASSENGER_FILE, passengers)

@app.route("/passenger.html", methods=["GET", "POST"])
def passenger_page():
    if request.method == "POST":
        data = request.form
        passenger = {
            "id": get_new_passenger_id(),
            "name": data.get("name"),
            "id_number": data.get("id_number"),
            "identity": data.get("identity")
        }
        passengers = load_json(PASSENGER_FILE)
        passengers.append(passenger)
        save_json(PASSENGER_FILE, passengers)
        return render_template("passenger.html", passengers=passengers, success=True)
    passengers = load_json(PASSENGER_FILE)
    return render_template("passenger.html", passengers=passengers)

if __name__ == "__main__":
    arg_parser = ArgumentParser(
        usage='Usage: python ' + __file__ + ' [--port <port>] [--help]'
    )
    arg_parser.add_argument('-p', '--port', default=10000, help='port')
    arg_parser.add_argument('-d', '--debug', default=True, help='debug')
    options = arg_parser.parse_args()

    app.run(debug=options.debug, port=options.port, threaded=True)