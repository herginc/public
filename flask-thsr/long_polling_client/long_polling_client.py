# long_polling_client.py - Python Client Code (T1=600s, POST, 無對齊)

import requests
import time
import sys
from datetime import datetime
from typing import Dict, Any

# --- Configuration ---

SERVER_URL = "https://flask-thsr.onrender.com/poll_for_update"

POLLING_INTERVAL = 600   # could be overwrite by command line parameter
MAX_NETWORK_LATENCY = 5  # could be overwrite by command line parameter

# T1: Client Base Timeout (600s)
CLIENT_TIMEOUT = POLLING_INTERVAL + MAX_NETWORK_LATENCY
# RETRY_DELAY (60s) 僅用於 requests.exceptions.RequestException
RETRY_DELAY = 60 

# --- Long Polling Loop ---

def run_long_polling():
    
    print(f"[{time.strftime('%H:%M:%S')}] Starting client. Polling interval: {POLLING_INTERVAL}s.")
    
    while True:
        
        # 1. 記錄請求開始時間 (用於 POST 數據)
        request_start_time = datetime.now()
        
        print(f"[{time.strftime('%H:%M:%S')}] Client initiating request (POST). Request timeout: {CLIENT_TIMEOUT}s.")
        
        # 2. 準備 POST 數據
        post_data: Dict[str, Any] = {
            "query_type" : "thsr_booking",
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

if __name__ == '__main__':
    run_long_polling()