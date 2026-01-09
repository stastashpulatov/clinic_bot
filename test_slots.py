from wordpress_api import generate_day_slots
from datetime import datetime

# Config simulation
start = "09:00"
end = "18:00"
lunch_start = "00:00"
lunch_end = "00:00"
duration = 15

# Test 1: Future date (Tomorrow)
print("--- Check Tomorrow ---")
tomorrow = "2026-01-10"
slots = generate_day_slots(start, end, lunch_start, lunch_end, duration, tomorrow)
print(f"Date: {tomorrow}")
print(f"Count: {len(slots)}")
print(f"Slots: {slots[:5]} ... {slots[-5:]}")

# Test 2: Today
print("\n--- Check Today ---")
today = datetime.now().strftime("%Y-%m-%d")
slots_today = generate_day_slots(start, end, lunch_start, lunch_end, duration, today)
print(f"Date: {today}")
print(f"Count: {len(slots_today)}")
print(f"Slots: {slots_today}")
