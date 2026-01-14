from datetime import datetime, timedelta
# from freezegun import freeze_time # Module not available

# Since we don't have freezegun, we'll confirm logic manually
print("🔍 Verifying Time Restriction Logic")

def check_access(simulated_hour):
    limit = 14
    if simulated_hour >= limit:
        return False, "⚠️ Запись через бота доступна только до 14:00."
    return True, "✅ Access Allowed"

# Test Cases
test_times = [9, 13, 14, 15, 18]

print(f"{'Hour':<5} | {'Result':<10} | {'Message'}")
print("-" * 40)

for hour in test_times:
    allowed, msg = check_access(hour)
    status = "ALLOWED" if allowed else "BLOCKED"
    print(f"{hour:02d}:00 | {status:<10} | {msg}")

print("-" * 40)
print("Logic verification complete.")
