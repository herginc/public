# client.py - Python Client Code (T1=299s, 每 5 分鐘對齊)

import requests
import time
import sys
from datetime import datetime, timedelta

# --- Configuration (T1) ---

SERVER_URL = "https://flask-thsr.onrender.com/poll_for_update" # 替換為您的 Render URL
RETRY_DELAY = 10 

# T1: Client timeout. 299秒。必須介於 T2 (298s) 和 T3 (300s) 之間。
CLIENT_TIMEOUT = 299 

# --- Polling Frequency Setting ---
POLL_INTERVAL_MINUTES = 5 # 每 5 分鐘發送一次請求，並對齊時鐘

# --- Time Alignment Logic ---

def calculate_sleep_time(interval_minutes: int = POLL_INTERVAL_MINUTES) -> float:
    """
    計算需要等待多久，才能使下一個請求準時在每 5 分鐘的整點啟動 (例如 HH:05:00)。
    """
    now = datetime.now()
    
    # 1. 找到當前分鐘數距離下一個 5 分鐘整點還有多少分鐘 
    current_minute = now.minute
    minutes_to_add = interval_minutes - (current_minute % interval_minutes)
    
    # 2. 計算目標時間
    target_time = now + timedelta(minutes=minutes_to_add)
    # 將秒數和微秒數歸零，實現精準對齊
    target_time = target_time.replace(second=0, microsecond=0)
    
    # 3. 計算需要等待的秒數
    sleep_seconds = (target_time - now).total_seconds()
    
    # 如果計算結果小於 1 秒 (代表程式剛好在整點前幾毫秒執行)，則跳到下一個週期
    if sleep_seconds < 1: 
        target_time += timedelta(minutes=interval_minutes)
        sleep_seconds = (target_time - now).total_seconds()
    
    return max(0.0, sleep_seconds)

# --- Long Polling Loop ---

def run_long_polling():
    first_poll = True
    
    while True:
        # --- PHASE 1: Time Alignment ---
        if not first_poll:
            sleep_time = calculate_sleep_time()
            target_time = datetime.now() + timedelta(seconds=sleep_time)
            
            print(f"[{time.strftime('%H:%M:%S')}] Current poll finished. Aligning to next {POLL_INTERVAL_MINUTES}-min mark: {target_time.strftime('%H:%M:%S')}. Sleeping for {sleep_time:.2f} seconds.")
            time.sleep(sleep_time)
            
        print(f"[{time.strftime('%H:%M:%S')}] Client initiating request. Max patience: {CLIENT_TIMEOUT}s.")
        
        # --- PHASE 2: Long Poll Request ---
        try:
            # 使用 T1 = 299 秒超時
            response = requests.get(SERVER_URL, timeout=CLIENT_TIMEOUT) 
            first_poll = False
            
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
                    # Instant notification received (T < 298s)
                    print("="*50)
                    print(f"[{time.strftime('%H:%M:%S')}] **🚀 RECEIVED INSTANT NOTIFICATION!**")
                    print(f"Data: {data.get('data')}")
                    print("="*50)
                
                else:  # Handles "timeout" (T=298s) and "forced_reconnect"
                    print(f"[{time.strftime('%H:%M:%S')}] Connection ended ({status}). Will align to next {POLL_INTERVAL_MINUTES}-min mark.")
                
            else:
                # Other server errors (500, 502, etc.)
                print(f"[{time.strftime('%H:%M:%S')}] Server returned unexpected status code: {response.status_code}. Retrying in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
        
        # --- 3. Exception Handling ---
        except requests.exceptions.Timeout:
            # Unexpected Client Timeout occurred (T > 299s)
            print(f"[{time.strftime('%H:%M:%S')}] Client request timed out ({CLIENT_TIMEOUT}s reached). Assuming network fault. Will align to next {POLL_INTERVAL_MINUTES}-min mark.")
            first_poll = False
            
        except requests.exceptions.RequestException as e:
            # General connection errors
            print(f"[{time.strftime('%H:%M:%S')}] Connection error occurred: {e}. Retrying in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)
            first_poll = False

if __name__ == '__main__':
    run_long_polling()