import os

env_path = ".env"
if not os.path.exists(env_path):
    print(".env NOT FOUND")
else:
    print(f".env FOUND at {os.path.abspath(env_path)}")
    with open(env_path, 'r') as f:
        for line in f:
            if line.startswith("ADMIN_IDS"):
                print(f"RAW LINE: {line.strip()}")
                # Try to parse
                try:
                    val = line.split('=')[1].strip()
                    ids = [int(x.strip()) for x in val.split(',') if x.strip()]
                    print(f"PARSED IDS: {ids}")
                except Exception as e:
                    print(f"PARSE ERROR: {e}")
