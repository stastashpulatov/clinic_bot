import requests
import json

url = "https://diason.uz/wp-json/clinic/v1/all-appointments"
headers = {
    "x-api-key": "tg_bot_secret_key_8451",
    "User-Agent": "DebugScript/1.0"
}

try:
    print(f"Requesting {url}...")
    response = requests.get(url, headers=headers, verify=True, params={"limit": 10})
    
    print(f"Status Code: {response.status_code}")
    print(f"Response Headers: {response.headers}")
    
    try:
        data = response.json()
        print("JSON Response:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except json.JSONDecodeError:
        print("Response is not JSON. Raw text:")
        print(response.text)

except Exception as e:
    print(f"Error: {e}")
