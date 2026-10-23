from dotenv import load_dotenv
import os

load_dotenv()

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

print(f"URL:    [{url}]")
print(f"KEY:    [{key[:30] if key else 'MISSING'}...]")
print(f"URL len: {len(url) if url else 0}")

# Test direct HTTP request to the REST API
import httpx
test_url = f"{url}/rest/v1/nodes?select=id&limit=1"
print(f"\nTesting: {test_url}")
try:
    r = httpx.get(test_url, verify=False, headers={
        "apikey": key,
        "Authorization": f"Bearer {key}"
    })
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text[:200]}")
except Exception as e:
    print(f"Error: {e}")