# =======================================================
# long_polling_client.py - Long Polling 客戶端 (最終版本)
# =======================================================
import requests
import json
import time
from datetime import datetime
from typing import List, Dict, Any

# 🚀 導入獨立的模擬函式
from thsr_booking import simulate_booking

# 伺服器網址
SERVER_URL = 'https://flask-thsr.onrender.com' 

# 客戶端設定
CLIENT_TIMEOUT_S = 605 
MAX_RETRIES = 5 
RETRY_DELAY_SECONDS = 60 # ⚠️ 已更新：重試延遲時間改為 60 秒

# --- 輔助函式 ---

def update_server_status(task_id: int, status: str, code: str = None) -> bool:
    """
    將訂票結果回傳給伺服器，以便從待處理佇列中移除任務。
    """
    url = f'{SERVER_URL}/update_status'
    details = {"code": code} if code else {}
    
    update_payload = {
        "task_id": task_id,
        "status": status,
        "details": details
    }
    
    try:
        response = requests.post(url, json=update_payload, timeout=5) 
        response.raise_for_status() 
        
        result = response.json()
        if result.get("status") == "success":
            return True
        else:
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ SERVER ERROR: Update failed for Task {task_id}. Message: {result.get('message')}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"[{time.strftime('%H:%M:%S')}] 🚨 NETWORK ERROR: Failed to update status for Task {task_id}. {e}")
        return False


def process_and_report_tasks(tasks_list: List[Dict[str, Any]]):
    """
    遍歷任務列表，處理每一筆任務並回傳結果。
    """
    for task in tasks_list:
        task_id = task.get("id")
        
        # 1. 執行模擬訂票 (從 thsr_booking 模組導入)
        new_status, booking_code = simulate_booking(task)
        
        # 2. 回傳狀態給伺服器
        if not update_server_status(task_id, new_status, booking_code):
            print(f"[{time.strftime('%H:%M:%S')}] 🚨 CRITICAL: Task {task_id} result not confirmed by server. It remains in the queue.")


# --- 核心 Long Polling 邏輯 ---

def start_polling():
    poll_url = f'{SERVER_URL}/poll_for_update'
    retry_count = 0
    
    print(f"[{time.strftime('%H:%M:%S')}] 🚀 Client starting Long Polling loop for server: {SERVER_URL}")

    while retry_count < MAX_RETRIES:
        try:
            # 1. 準備請求 payload
            payload = {
                "client_timeout_s": CLIENT_TIMEOUT_S,
                "timestamp": datetime.now().isoformat() 
            }

            print(f"[{time.strftime('%H:%M:%S')}] Client initiating request (POST). Request timeout: {CLIENT_TIMEOUT_S}s.")
            
            # 2. 發起 Long Polling 請求
            response = requests.post(
                poll_url, 
                json=payload, 
                timeout=CLIENT_TIMEOUT_S + 5 
            )
            response.raise_for_status() 
            
            # 3. 解析響應
            data = response.json()
            status = data.get('status')
            
            # ⚠️ 依要求：立即印出回傳的 status
            if status:
                print(f"[{time.strftime('%H:%M:%S')}] ➡️ SERVER STATUS: {status}")
            
            # --- 處理不同狀態 ---
            
            if status == "initial_sync":
                pending_tasks = data.get('data', [])
                if pending_tasks:
                    print(f"[{time.strftime('%H:%M:%S')}] 🔄 SYNC: Received {len(pending_tasks)} pending tasks for initial processing.")
                    process_and_report_tasks(pending_tasks)
                
                retry_count = 0 
                
            elif status == "success":
                new_task = data.get('data')
                if new_task:
                    print(f"[{time.strftime('%H:%M:%S')}] ⭐ PUSH: Received new task via push.")
                    process_and_report_tasks([new_task])
                    
                retry_count = 0
                
            elif status == "timeout" or status == "forced_reconnect":
                retry_count = 0
                pass 
                
            else:
                print(f"[{time.strftime('%H:%M:%S')}] ❓ UNKNOWN STATUS: {status}. Server response: {data}")
                retry_count += 1
                time.sleep(RETRY_DELAY_SECONDS)
                
        except requests.exceptions.Timeout:
            # 正常 Long Polling 超時
            retry_count = 0
            print(f"[{time.strftime('%H:%M:%S')}] 😴 TIMEOUT: Long polling request timed out. Reconnecting immediately.")
            pass
            
        except requests.exceptions.RequestException as e:
            # 網路或其他致命錯誤
            print(f"[{time.strftime('%H:%M:%S')}] ❌ FATAL ERROR: Connection failed: {e}")
            retry_count += 1
            print(f"[{time.strftime('%H:%M:%S')}] Waiting {RETRY_DELAY_SECONDS}s before retrying. ({retry_count}/{MAX_RETRIES})")
            time.sleep(RETRY_DELAY_SECONDS)

    print(f"[{time.strftime('%H:%M:%S')}] 🛑 Max retries reached. Shutting down client.")


if __name__ == "__main__":
    start_polling()