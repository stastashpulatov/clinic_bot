import requests
import json

url = "https://diason.uz/wp-json/clinic/v1/all-appointments"
base_url = "https://diason.uz/wp-json/clinic/v1"
api_key = "tg_bot_secret_key_8451" # Assuming this is the api_key used in the new requests
headers = {
    "x-api-key": api_key, # Keep for consistency, though new requests use it as param/data
    "User-Agent": "DebugScript/1.0"
}

# Тест обновления статуса
try:
    print(f"Requesting {base_url}/all-appointments to get an ID...")
    
    # Force test with Dummy ID to check if endpoint EXISTS (404 vs 200)
    apt_id = 999999
    
    # 2. Пытаемся обновить статус (фейковый апдейт, чтобы проверить endpoint)
    # Используем статус 1 (Confirmed) чтобы не портить данные
    payload = {
        'api_key': api_key, # API key sent as form data
        'appointment_id': apt_id,
        'status': 1 
    }
    
    print(f"Posting to {base_url}/update-status with payload: {payload}")
    update_resp = requests.post(
        f"{base_url}/update-status", 
        data=payload,
        verify=True # Keep verify=True for production
    )
    
    print(f"\nUpdate Status Code: {update_resp.status_code}")
    print(f"Update Response: {update_resp.text}")

except Exception as e:
    print(f"Error: {e}")
