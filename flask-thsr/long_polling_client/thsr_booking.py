# =======================================================
# thsr_booking.py - 模擬訂票系統
# 負責實際的訂票邏輯 (50% 成功率)
# =======================================================
import time
import random
from typing import Dict, Any

def simulate_booking(task: Dict[str, Any]) -> (str, str):
    """
    模擬實際的訂票邏輯，成功率為 50%。
    
    Args:
        task: 包含任務資訊的字典 (例如: {"id": 1, "name": "Taipei to Kaohsiung"})
        
    Returns:
        (new_status, booking_code) 元組。
    """
    task_id = task.get("id")
    task_name = task.get("name", "Unknown Task")
    
    print(f"[Booking Engine] ⏳ TASK {task_id}: Simulating booking for {task_name}...")
    
    # 模擬隨機延遲 (0.5 到 3 秒)
    time.sleep(1 + random.uniform(0.5, 2.0)) 
    
    # 模擬 50% 成功率
    if random.random() < 0.5: 
        new_status = "booked"
        # 根據 ID 模擬一個訂位代號
        booking_code = f"T{task_id:04d}A{random.randint(10, 99)}"
        print(f"[Booking Engine] ✅ TASK {task_id}: Booking SUCCESS. Code: {booking_code}")
    else:
        new_status = "failed"
        booking_code = None
        print(f"[Booking Engine] ❌ TASK {task_id}: Booking FAILED (50% chance).")

    return new_status, booking_code