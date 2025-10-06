# ===============================================
# long_polling_client.py (Private PC Client)
# ===============================================

import requests
import time
import sys
import json
from datetime import datetime
from typing import Dict, Any

# --- Configuration ---
# 請將 SERVER_URL 替換為您 Render 部署的實際網址
SERVER_URL = "https://flask-thsr.onrender.com" 
POLL_URL = f"{SERVER_URL}/poll_for_update"
UPDATE_URL = f"{SERVER_URL}/update_status"

POLLING_INTERVAL = 600
MAX_NETWORK_LATENCY = 5
CLIENT_TIMEOUT = POLLING_INTERVAL + MAX_NETWORK_LATENCY # T1
RETRY_DELAY = 60 
SHORT_UPDATE_TIMEOUT = 10 # 回傳結果時的短超時

# --- 訂票模擬函式 (你需要自行實現 thsr_booking_system.py) ---

def run_thsr_booking_system(booking_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    模擬呼叫 thsr_booking_system.py 進行訂票。
    實際程式碼應在此處替換為對真實或模擬訂票系統的調用。
    """
    task_id = booking_data.get('id', 'N/A')
    print(f"[{time.strftime('%H:%M:%S')}] ⚙️ STARTING thsr_booking_system for Task ID: {task_id}...")
    
    # 模擬耗時操作
    time.sleep(3) 

    # 模擬訂票結果 (例如：成功)
    if booking_data.get("train_no") == "999":
        # 模擬訂票失敗
        return {"result": "failed", "error_message": "Train 999 is full or cancelled.", "code": None}
    else:
        # 模擬訂票成功
        return {"result": "booked", "ticket_info": "E-Ticket info...", "code": f"T{task_id}{int(time.time()) % 1000}"}

# --- 結果回傳函式 ---

def update_server_status(task_id: str, result_data: Dict[str, Any]):
    """將訂票結果回傳給 Render 上的 app.py 伺服器。"""
    
    status = result_data.get("result", "unknown")
    payload = {
        "task_id": task_id,
        "status": status, 
        "details": result_data 
    }
    
    try:
        response = requests.post(UPDATE_URL, json=payload, timeout=SHORT_UPDATE_TIMEOUT)
        if response.status_code == 200:
            print(f"[{time.strftime('%H:%M:%S')}] ✅ Status updated for Task ID {task_id} to '{status}'.")
        else:
            print(f"[{time.strftime('%H:%M:%S')}] ❌ FAILED to update status for Task ID {task_id}. Server response: {response.status_code} {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ FAILED to update status for Task ID {task_id} (Connection Error): {e}")


# --- Long Polling Loop ---

def run_long_polling():
    
    print(f"[{time.strftime('%H:%M:%S')}] Starting client. Polling interval: {POLLING_INTERVAL}s. T1 Timeout: {CLIENT_TIMEOUT}s.")
    
    while True:
        
        request_start_time = datetime.now()
        
        print(f"[{time.strftime('%H:%M:%S')}] Client initiating request (POST). Request timeout: {CLIENT_TIMEOUT}s.")
        
        post_data: Dict[str, Any] = {
            "query_type" : "thsr_booking",
            "client_timeout_s": CLIENT_TIMEOUT,
            "timestamp": request_start_time.isoformat() 
        }
        
        # --- Long Poll Request ---
        try:
            response = requests.post(POLL_URL, json=post_data, timeout=CLIENT_TIMEOUT) 
            
            if response.status_code == 200:
                data = response.json()
                status = data.get("status")

                if status == "success":
                    # 🚀 RECEIVED INSTANT NOTIFICATION (New Task)
                    booking_data = data.get('data', {})
                    task_id = booking_data.get('id')
                    
                    print("="*50)
                    print(f"[{time.strftime('%H:%M:%S')}] **🚀 RECEIVED TASK ID {task_id}!** Data: {booking_data}")
                    
                    # 1. 執行訂票系統
                    booking_result = run_thsr_booking_system(booking_data)
                    
                    # 2. 回傳結果給 Server
                    update_server_status(task_id, booking_result)
                    
                    print("="*50)
                    # 立即進入下一輪 Long Poll
                
                elif status in ["timeout", "forced_reconnect"]:
                    # T2 Timeout (正常結束) 或 Server 要求重連
                    print(f"[{time.strftime('%H:%M:%S')}] Connection ended ({status}). Initiating next poll immediately.")
                    
                else: 
                    print(f"[{time.strftime('%H:%M:%S')}] Server returned unexpected status status: {status}. Initiating next poll immediately.")
            
            else:
                # Other server errors (404, 500, etc.)
                print(f"[{time.strftime('%H:%M:%S')}] Server returned unexpected status code: {response.status_code}. Initiating next poll immediately.")
        
        # --- Exception Handling ---
        except requests.exceptions.Timeout:
            # T1 Timeout (605s) 發生，表示 T3/Gunicorn 超時可能先發生了
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ UNEXPECTED TIMEOUT: Client request timed out ({CLIENT_TIMEOUT}s reached). Initiating next poll immediately.")
            
        except requests.exceptions.RequestException as e:
            # 連線失敗、DNS 錯誤等硬性網路問題
            print(f"[{time.strftime('%H:%M:%M')}] ⛔ CONNECTION ERROR: {e}. Retrying in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)
            
        except Exception as e:
            # 其他所有未知錯誤
            print(f"[{time.strftime('%H:%M:%S')}] ❌ UNKNOWN ERROR: {e}. Initiating next poll immediately.")

if __name__ == '__main__':
    run_long_polling()