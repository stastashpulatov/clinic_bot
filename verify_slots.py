import logging
import sys
from datetime import datetime, timedelta
from wordpress_api import WordPressAPI, calculate_available_slots
from config import WORDPRESS_CONFIG, WORKING_HOURS, APPOINTMENT_DURATION

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('verify_slots')

def main():
    logger.info("Starting verification of slot availability logic...")
    
    # 1. Initialize API
    api = WordPressAPI(
        site_url=WORDPRESS_CONFIG['site_url'],
        username=WORDPRESS_CONFIG['username'],
        password=WORDPRESS_CONFIG['password'],
        api_key=WORDPRESS_CONFIG.get('api_key'),
        verify_ssl=WORDPRESS_CONFIG.get('verify_ssl', True)
    )
    
    success, msg = api.test_connection()
    if not success:
        logger.error(f"Failed to connect to WordPress API: {msg}")
        return

    logger.info("WordPress API connected successfully.")

    # 2. Pick a test doctor and date
    test_doctor_id = 6  # Example doctor ID (Dmitry Zeberg from hardcoded list)
    test_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d') # Tomorrow
    logger.info(f"Testing for Doctor ID: {test_doctor_id} on Date: {test_date}")

    # 3. Get initial occupied slots
    occupied_before = api.get_occupied_slots(doctor_id=test_doctor_id, date=test_date)
    logger.info(f"Occupied slots BEFORE booking: {occupied_before}")
    
    # 4. Calculate available slots
    available_before = calculate_available_slots(
        occupied_slots=occupied_before,
        start_time=WORKING_HOURS.get('start', '09:00'),
        end_time=WORKING_HOURS.get('end', '18:00'),
        lunch_start=WORKING_HOURS.get('lunch_start', '13:00'),
        lunch_end=WORKING_HOURS.get('lunch_end', '14:00'),
        slot_duration=APPOINTMENT_DURATION
    )
    
    if not available_before:
        logger.error("No available slots to test booking! choose another date or doctor.")
        return

    test_time = available_before[0]
    logger.info(f"Selected test slot: {test_time}")

    # 5. Create a test appointment
    logger.info(f"Creating test appointment for {test_time}...")
    success, apt_id = api.create_appointment(
        doctor_id=test_doctor_id,
        date=test_date,
        time=test_time,
        patient_name="Test Verification Bot",
        patient_phone="+998000000000",
        telegram_id=123456789
    )

    if not success:
        logger.error("Failed to create test appointment!")
        return
    
    logger.info(f"Appointment created successfully! ID: {apt_id}")

    # 6. Verify the slot is now occupied
    occupied_after = api.get_occupied_slots(doctor_id=test_doctor_id, date=test_date)
    logger.info(f"Occupied slots AFTER booking: {occupied_after}")

    is_occupied = test_time in occupied_after
    if is_occupied:
        logger.info(f"SUCCESS: Slot {test_time} is now marked as occupied.")
    else:
        logger.error(f"FAILURE: Slot {test_time} is NOT in occupied list after booking!")

    # 7. Check calculation again
    available_after = calculate_available_slots(
        occupied_slots=occupied_after,
        start_time=WORKING_HOURS.get('start', '09:00'),
        end_time=WORKING_HOURS.get('end', '18:00'),
        lunch_start=WORKING_HOURS.get('lunch_start', '13:00'),
        lunch_end=WORKING_HOURS.get('lunch_end', '14:00'),
        slot_duration=APPOINTMENT_DURATION
    )
    
    is_available = test_time in available_after
    if not is_available:
        logger.info(f"SUCCESS: Slot {test_time} is NOT in available list anymore.")
    else:
        logger.error(f"FAILURE: Slot {test_time} IS still in available list!")
        
    # Optional cleanup (cancel appointment if method exists, though not critical for test env)
    # api.cancel_appointment(apt_id)

if __name__ == '__main__':
    main()
