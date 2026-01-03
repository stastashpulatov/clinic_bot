import requests
import json
from config import WORDPRESS_CONFIG

API_URL = WORDPRESS_CONFIG['site_url'] + "/wp-json/clinic/v1"
API_KEY = WORDPRESS_CONFIG.get('api_key')

HEADERS = {
    'x-api-key': API_KEY,
    'User-Agent': 'DebugScript/1.0'
}

TEST_ID = 123456789
TEST_DATE = "2026-02-01" # Future date
TEST_TIME = "10:00"

def test_flow():
    print(f"Testing API at {API_URL}")
    
    # 1. Create Appointment
    print("\n1. Creating appointment...")
    payload = {
        'doctor_id': 6, # Дмитрий Зеберг
        'appointment_date': TEST_DATE,
        'appointment_time': TEST_TIME,
        'user_name': 'Test User',
        'user_phone': '+998900000000',
        'telegram_id': TEST_ID
    }
    
    try:
        resp = requests.post(f"{API_URL}/appointments", json=payload, headers=HEADERS, verify=False)
        print(f"Create Status: {resp.status_code}")
        print(f"Create Response: {resp.text}")
        
        if resp.status_code != 200:
            return
            
        data = resp.json()
        if not data.get('success'):
            print("Failed to create")
            return
            
        apt_id = data.get('id')
        print(f"Created Appointment ID: {apt_id}")
        
        # 2. Get Appointments
        print("\n2. Getting appointments...")
        resp = requests.get(f"{API_URL}/my-appointments", params={'telegram_id': TEST_ID}, headers=HEADERS, verify=False)
        print(f"Get Status: {resp.status_code}")
        print(f"Get Response: {resp.text}")
        
        appointments = resp.json()
        found = False
        for apt in appointments:
            if str(apt['id']) == str(apt_id):
                print(f"✅ Found our appointment: {apt}")
                found = True
                break
        
        if not found:
            print("❌ Appointment NOT found in list!")
        
        # 3. Clean up (Cancel)
        if found:
            print("\n3. Cancelling appointment...")
            # Note: The server API expects POST to /cancel-appointment with appointment_id param?
            # Let's check the code: register_rest_route... callback 'clinic_cancel_kivi_appointment'
            # clinic-telegram-bot-api.php: $appointment_id = $request->get_param('appointment_id');
            
            resp = requests.post(f"{API_URL}/cancel-appointment", params={'appointment_id': apt_id}, headers=HEADERS, verify=False)
            print(f"Cancel Response: {resp.text}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_flow()
