import os
import ssl
import httpx
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL: str = os.environ.get("SUPABASE_URL")
SUPABASE_KEY: str = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase URL and Key must be set in .env file")

# Explicit SSL context that skips verification.
# Required for local dev — antivirus performs TLS interception causing
# hostname mismatch. Never use in production.
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

db = httpx.Client(
    base_url=f"{SUPABASE_URL}/rest/v1",
    verify=ssl_ctx,
    timeout=httpx.Timeout(30.0, connect=15.0),
    headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
)