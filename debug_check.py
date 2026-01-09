import requests
import json

url = "https://diason.uz/wp-json/clinic/v1/all-appointments"
base_url = "https://diason.uz/wp-json/clinic/v1"
api_key = "tg_bot_secret_key_8451" # Assuming this is the api_key used in the new requests
headers = {
    "x-api-key": api_key, # Keep for consistency, though new requests use it as param/data
    "User-Agent": "DebugScript/1.0"
}

# Тест получения списка (Debug)
try:
    print(f"Fetching appointments from {base_url}/all-appointments...")
    
    resp = requests.get(
        f"{base_url}/all-appointments", 
        headers=headers, 
        params={"limit": 10}, 
        verify=True
    )
    
    print(f"Status Code: {resp.status_code}")
    
    try:
        data = resp.json()
        print("Raw JSON Data:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except:
        print("Response text:", resp.text)
        
except Exception as e:
    print(f"Error: {e}")
