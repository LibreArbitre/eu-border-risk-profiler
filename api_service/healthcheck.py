import os
import sys
import requests

url = os.getenv('API_HEALTH_URL', 'http://localhost:8000/health')
try:
    resp = requests.get(url, timeout=2)
    sys.exit(0 if resp.status_code == 200 else 1)
except Exception as exc:
    print(exc)
    sys.exit(1)
