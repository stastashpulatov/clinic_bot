import logging
from datetime import datetime, timedelta
from wordpress_api import calculate_available_slots
from config import WORKING_HOURS, APPOINTMENT_DURATION

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger('check_slots')

def main():
    print(f"DEBUG: Configured Working Hours: {WORKING_HOURS}")
    print(f"DEBUG: Configured Slot Duration: {APPOINTMENT_DURATION} min")

    # Generate slots for a hypothetical empty day
    slots = calculate_available_slots(
        occupied_slots=[],
        start_time=WORKING_HOURS.get('start', '09:00'),
        end_time=WORKING_HOURS.get('end', '18:00'),
        lunch_start=WORKING_HOURS.get('lunch_start', '00:00'),
        lunch_end=WORKING_HOURS.get('lunch_end', '00:00'),
        slot_duration=APPOINTMENT_DURATION
    )
    
    print("\nGenerated Slots:")
    for slot in slots:
        print(f" - {slot}")

    expected_last_slot = "13:30"
    if slots and slots[-1] == expected_last_slot:
        print(f"\nSUCCESS: Last slot is {expected_last_slot}")
    else:
        print(f"\nFAILURE: Last slot is {slots[-1] if slots else 'None'}, expected {expected_last_slot}")

if __name__ == '__main__':
    main()
