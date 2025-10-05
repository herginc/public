# client.py - Python Client Code

import requests
import time
import sys
from datetime import datetime, timedelta

# --- Configuration (T1) ---
SERVER_URL = "https://flask-thsr.onrender.com/poll_for_update"
RETRY_DELAY = 10 

# T1: Client timeout. Set to 595s. Must be > T2 (590s) and < T3 (600s).
CLIENT_TIMEOUT = 595 

# --- Time Alignment Logic ---

def calculate_sleep_time(interval_minutes: int = 10) -> float:
    """
    Calculates the sleep time required to align the next operation 
    to the next 10-minute interval (e.g., 10:00, 10:10, 10:20).
    """
    now = datetime.now()
    
    # Calculate minutes to the next mark (e.g., 3 -> 7 minutes to 10)
    current_minute = now.minute
    minutes_to_add = interval_minutes - (current_minute % interval_minutes)
    
    # Set the target minute and reset seconds/microseconds
    target_time = now + timedelta(minutes=minutes_to_add)
    target_time = target_time.replace(second=0, microsecond=0)
    
    # Calculate the difference (seconds to sleep)
    sleep_seconds = (target_time - now).total_seconds()
    
    return max(0.0, sleep_seconds)

# --- Long Polling Loop ---

def run_long_polling():
    first_poll = True
    
    while True:
        # --- PHASE 1: Time Alignment (Skip for the very first poll) ---
        if not first_poll:
            sleep_time = calculate_sleep_time(interval_minutes=10)
            
            if sleep_time > 0:
                target_time = datetime.now() + timedelta(seconds=sleep_time)
                print(f"[{time.strftime('%H:%M:%S')}] Current poll finished. Aligning to next 10-min mark: {target_time.strftime('%H:%M:%S')}. Sleeping for {sleep_time:.2f} seconds.")
                time.sleep(sleep_time)
            
        print(f"[{time.strftime('%H:%M:%S')}] Client initiating request. Max patience: {CLIENT_TIMEOUT}s.")
        
        # --- PHASE 2: Long Poll Request ---
        try:
            # The request uses the new T1 = 595 seconds timeout.
            response = requests.get(SERVER_URL, timeout=CLIENT_TIMEOUT) 
            first_poll = False
            
            # --- Status Code Handling ---
            if response.status_code == 404:
                # 404 (Not Found) is a fatal error, terminating the program immediately.
                print("\n" + "="*70)
                print(f"[{time.strftime('%H:%M:%S')}] **FATAL ERROR: Server returned 404 (Not Found).**")
                print(f"Please check the URL: {SERVER_URL}")
                print("Program terminated due to incorrect path configuration.")
                print("="*70 + "\n")
                sys.exit(1)

            elif response.status_code == 200:
                data = response.json()
                status = data.get("status")

                if status == "success":
                    # Handle instant notification from the trigger_event endpoint (T < 590s).
                    print("="*50)
                    print(f"[{time.strftime('%H:%M:%S')}] **🚀 RECEIVED INSTANT NOTIFICATION!**")
                    print(f"Data: {data.get('data')}")
                    print("="*50)
                
                else:  # Handles "timeout" (T=590s) and "forced_reconnect" (new poll arrived).
                    # The action for both is to simply end the current poll cycle.
                    print(f"[{time.strftime('%H:%M:%S')}] Connection ended ({status}). Will align to next 10-min mark.")
                
            else:
                # Handle other unexpected non-200 server errors (e.g., 500, 502).
                print(f"[{time.strftime('%H:%M:%S')}] Server returned unexpected status code: {response.status_code}. Retrying in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
                # Note: Time alignment handles the schedule correction on the next loop.
        
        # --- 3. Exception Handling ---
        except requests.exceptions.Timeout:
            # Unexpected Client Timeout occurred (T > 595s).
            print(f"[{time.strftime('%H:%M:%S')}] Client request timed out ({CLIENT_TIMEOUT}s reached). Assuming network fault. Will align to next 10-min mark.")
            first_poll = False
            
        except requests.exceptions.RequestException as e:
            # Handle general connection errors.
            print(f"[{time.strftime('%H:%M:%S')}] Connection error occurred: {e}. Retrying in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)
            first_poll = False

if __name__ == '__main__':
    run_long_polling()