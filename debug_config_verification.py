from config import ADMIN_IDS
import os

print(f"Loaded ADMIN_IDS: {ADMIN_IDS}")
print(f"Type of IDs: {[type(x) for x in ADMIN_IDS]}")

# Check content of .env raw
with open('.env', 'r') as f:
    print(f"Raw .env content:\n{f.read()}")
