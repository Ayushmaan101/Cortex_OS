"""
CortexOS Digest — Resend email, user-centric automated notification system.
Sends curated articles to subscribers at their chosen frequency.
"""

import os, ssl, re, httpx, asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional
from dotenv import load_dotenv
load_dotenv()

RESEND_API_KEY = os.environ.get("RESEND_API_KEY","")
DIGEST_FROM    = os.environ.get("DIGEST_FROM","CortexOS <digest@yourdomain.com>")
DIGEST_EMAIL   = os.environ.get("DIGEST_EMAIL","")
SUPABASE_URL   = os.environ.get("SUPABASE_URL","")
SUPABASE_KEY   = os.environ.get("SUPABASE_KEY","")
CORTEX_URL     = os.environ.get("CORTEX_URL","http://localhost:3000")

# Max articles per source in the digest email — keeps it tight
DIGEST_MAX_PER_SOURCE = 3
DIGEST_TOTAL_MAX = 15

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

RESEARCH_KEYWORDS = re.compile(
    r'\b(model|llm|reasoning|rag|agent|benchmark|training|inference|'
    r'fine.?tun|multimodal|neural|attention|embedding|alignment|'
    r'safety|dataset|architecture|scaling|diffusion|generative|'
    r'retrieval|autonomous|agentic|open.source|release|research|paper)\b',
    re.IGNORECASE
)

def curate_for_digest(items: list[dict], max_total=DIGEST_TOTAL_MAX) -> list[dict]:
    """
    From the full inbox, pick the best articles for the digest:
    1. Prioritise research-keyword matches
    2. Max DIGEST_MAX_PER_SOURCE per source to avoid one source dominating
    3. Cap total at max_total
    """
    # Score each item
    scored = []
    for item in items:
        score = 0
        text = f"{item.get('title','')} {item.get('summary','')}"
        score += len(RESEARCH_KEYWORDS.findall(text)) * 2
        # Bonus for high-signal sources
        if item.get("source_id") in ("arxiv_ai","arxiv_lg","hn"): score += 3
        if item.get("source_id") in ("hf","github"): score += 2
        scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Apply per-source cap
    counts: dict[str,int] = {}
    curated = []
    for score, item in scored:
        sid = item.get("source_id","other")
        if counts.get(sid, 0) >= DIGEST_MAX_PER_SOURCE: continue
        counts[sid] = counts.get(sid, 0) + 1
        curated.append(item)
        if len(curated) >= max_total: break

    return curated


async def get_recipients() -> list[dict]:
    """
    Fetch all active subscribers (not interval-filtered).
    Used for manual digest triggers.
    """
    try:
        async with httpx.AsyncClient(verify=ssl_ctx, timeout=10) as client:
            r = await client.get(
                f"{SUPABASE_URL}/rest/v1/profiles",
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
                params={"select": "id,email,name,digest_interval", "digest_enabled": "eq.true"},
            )
            if r.status_code == 200:
                profiles = r.json()
                if profiles:
                    print(f"📬 {len(profiles)} subscribers from profiles table")
                    return profiles
    except Exception as e:
        print(f"⚠ profiles fetch failed: {e}")

    if DIGEST_EMAIL:
        print(f"📬 Falling back to .env: {DIGEST_EMAIL}")
        return [{"email": DIGEST_EMAIL, "name": ""}]
    return []


async def get_due_recipients(adb_func) -> list[dict]:
    """
    Fetch subscribers who are 'due' for a digest based on their digest_interval.
    
    Rules:
    - If last_digest_sent_at is NULL, they are due (new subscriber)
    - If due based on digest_interval (daily=1d, weekly=7d, monthly=30d), include them
    """
    try:
        async with httpx.AsyncClient(verify=ssl_ctx, timeout=10) as client:
            r = await client.get(
                f"{SUPABASE_URL}/rest/v1/profiles",
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
                params={
                    "select": "id,email,name,digest_interval,last_digest_sent_at",
                    "digest_enabled": "eq.true",
                    "order": "created_at.asc"
                },
            )
            if r.status_code == 200:
                profiles = r.json()
                now = datetime.now(timezone.utc)
                due = []

                for profile in profiles:
                    email = profile.get("email", "").strip()
                    if not email:
                        continue

                    last_sent = profile.get("last_digest_sent_at")
                    interval = profile.get("digest_interval", "daily").lower()

                    # New subscriber (never sent) — always due
                    if not last_sent:
                        due.append(profile)
                        continue

                    # Parse last_sent timestamp
                    try:
                        if isinstance(last_sent, str):
                            last_sent_dt = datetime.fromisoformat(last_sent.replace('Z', '+00:00'))
                        else:
                            last_sent_dt = last_sent
                    except Exception as e:
                        print(f"⚠ Couldn't parse last_digest_sent_at for {email}: {e}")
                        continue

                    elapsed = now - last_sent_dt

                    # Check interval thresholds
                    if interval == "daily" and elapsed >= timedelta(days=1):
                        due.append(profile)
                    elif interval == "weekly" and elapsed >= timedelta(days=7):
                        due.append(profile)
                    elif interval == "monthly" and elapsed >= timedelta(days=30):
                        due.append(profile)

                if due:
                    print(f"📬 {len(due)} subscribers due for digest")
                return due
    except Exception as e:
        print(f"⚠ get_due_recipients failed: {e}")
    return []


def build_welcome_html(name: str = "") -> str:
    """Build welcome email HTML with dark-mode CortexOS aesthetic."""
    greeting = f"Welcome to CortexOS, {name}!" if name else "Welcome to CortexOS!"
    
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#060608;font-family:monospace;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#060608;">
<tr><td align="center" style="padding:40px 20px;">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">
  <tr><td style="background:linear-gradient(135deg,rgba(168,85,247,0.15),rgba(6,182,212,0.08));
    border:1px solid rgba(168,85,247,0.2);border-radius:20px;padding:32px;text-align:center;">
    <div style="font-size:26px;font-weight:900;color:#a855f7;letter-spacing:-0.04em;margin-bottom:4px;">CORTEX OS</div>
    <div style="color:rgba(148,163,184,0.5);font-size:10px;letter-spacing:0.3em;
      text-transform:uppercase;margin-bottom:16px;">Intelligence Platform</div>
    <div style="color:#e2e8f0;font-size:14px;line-height:1.6;">
      <p>{greeting}</p>
      <p style="color:rgba(148,163,184,0.8);font-size:12px;margin-top:16px;">
        You've joined the network. Curated AI research will arrive in your inbox according to your chosen frequency.<br><br>
        <strong style="color:#a855f7;">What happens next:</strong><br>
        • Our intelligence feeds run 24/7<br>
        • Research is filtered for signal<br>
        • Your digest arrives on schedule<br>
        • One click to inject articles into your graph
      </p>
    </div>
  </td></tr>
  <tr><td style="padding:20px 0;text-align:center;">
    <a href="{CORTEX_URL}" style="color:rgba(168,85,247,0.6);font-size:10px;
      letter-spacing:0.15em;text-transform:uppercase;text-decoration:none;">
      Open CortexOS →
    </a>
  </td></tr>
  <tr><td style="padding:20px 0;text-align:center;border-top:1px solid rgba(255,255,255,0.06);">
    <div style="color:rgba(148,163,184,0.5);font-size:9px;letter-spacing:0.1em;">
      You're receiving this because you signed up for the CortexOS digest.<br>
      Adjust your preferences anytime.
    </div>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


async def send_welcome_email(email: str, name: str = "") -> dict:
    """Send welcome email to new subscriber using Resend."""
    if not RESEND_API_KEY:
        print(f"⚠ RESEND_API_KEY not set, skipping welcome email for {email}")
        return {"ok": False, "error": "RESEND_API_KEY not set"}

    email = email.strip().lower()
    subject = "Welcome to CortexOS"
    html = build_welcome_html(name)

    try:
        async with httpx.AsyncClient(verify=ssl_ctx, timeout=15) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                json={"from": DIGEST_FROM, "to": [email], "subject": subject, "html": html},
            )
            if r.status_code in (200, 201):
                print(f"  ✅ Welcome email sent to {email}")
                return {"ok": True, "email": email}
            else:
                print(f"  ❌ Welcome email failed for {email}: {r.status_code} {r.text[:200]}")
                return {"ok": False, "email": email, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        print(f"  ❌ Welcome email exception for {email}: {e}")
        return {"ok": False, "email": email, "error": str(e)}


def build_html(items: list[dict], name: str = "") -> str:
    date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    greeting = f"Hey {name}," if name else "Hey,"

    by_source: dict[str,list] = {}
    for item in items:
        by_source.setdefault(item.get("source","Other"), []).append(item)

    sections = ""
    for source, arts in by_source.items():
        icon = arts[0].get("source_icon","◆")
        rows = ""
        for a in arts:
            summary_html = (f'<p style="color:#64748b;font-size:12px;margin:4px 0 8px;'
                           f'font-family:monospace;line-height:1.5;">{a["summary"]}</p>'
                           if a.get("summary") else "")
            cortex_link = f"{CORTEX_URL}?inject={a['url']}&title={a['title']}"
            rows += f"""
            <tr><td style="padding:12px 0;border-bottom:1px solid #0f0f1a;">
              <a href="{a['url']}" style="color:#c084fc;font-size:14px;font-weight:600;
                text-decoration:none;font-family:monospace;line-height:1.4;display:block;
                margin-bottom:4px;">{a['title']}</a>
              {summary_html}
              <div style="margin-top:6px;">
                <a href="{a['url']}" style="color:#475569;font-size:11px;font-family:monospace;
                  text-decoration:none;background:#0f0f1a;border:1px solid #1e1e3a;
                  border-radius:6px;padding:3px 10px;margin-right:8px;">↗ Source</a>
                <a href="{cortex_link}" style="color:#a855f7;font-size:11px;font-family:monospace;
                  text-decoration:none;background:#1a0a2e;border:1px solid #4c1d95;
                  border-radius:6px;padding:3px 10px;">⚡ Open in CortexOS</a>
              </div>
            </td></tr>"""
        sections += f"""
        <tr><td style="padding:20px 0 6px;">
          <span style="font-size:14px;">{icon}</span>
          <span style="color:#7c3aed;font-size:9px;letter-spacing:0.2em;text-transform:uppercase;
            font-family:monospace;font-weight:700;margin-left:8px;">{source}</span>
          <div style="height:1px;background:linear-gradient(90deg,#4c1d95,transparent);margin-top:4px;"></div>
        </td></tr>{rows}"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#060608;font-family:monospace;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#060608;">
<tr><td align="center" style="padding:40px 20px;">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">
  <tr><td style="background:linear-gradient(135deg,rgba(168,85,247,0.15),rgba(6,182,212,0.08));
    border:1px solid rgba(168,85,247,0.2);border-radius:20px;padding:32px;text-align:center;">
    <div style="font-size:26px;font-weight:900;color:#a855f7;letter-spacing:-0.04em;margin-bottom:4px;">CORTEX OS</div>
    <div style="color:rgba(148,163,184,0.5);font-size:10px;letter-spacing:0.3em;
      text-transform:uppercase;margin-bottom:12px;">Intelligence Digest · {date_str}</div>
    <div style="color:rgba(148,163,184,0.5);font-size:12px;">
      {greeting} Here are today's top {len(items)} picks — curated for AI research signal.
    </div>
  </td></tr>
  <tr><td style="height:12px;"></td></tr>
  <tr><td style="background:#0a0a0f;border:1px solid rgba(255,255,255,0.06);
    border-radius:16px;padding:8px 24px;">
    <table width="100%" cellpadding="0" cellspacing="0">{sections}</table>
  </td></tr>
  <tr><td style="padding:20px 0;text-align:center;">
    <a href="{CORTEX_URL}" style="color:rgba(168,85,247,0.4);font-size:10px;
      letter-spacing:0.15em;text-transform:uppercase;text-decoration:none;">
      Open CortexOS →
    </a>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


async def send_digest(inbox_items: list[dict], recipient_list: list[dict], subject: Optional[str] = None) -> dict:
    """
    Curate articles, then send to specific recipients.
    
    Args:
        inbox_items: List of articles from the inbox
        recipient_list: Pre-filtered list of recipient dicts with email, name, etc.
        subject: Optional custom subject line
    """
    if not RESEND_API_KEY:
        return {"sent": 0, "failed": 0, "error": "RESEND_API_KEY not set"}

    curated = curate_for_digest(inbox_items)
    if not curated:
        return {"sent": 0, "failed": 0, "error": "No qualifying articles after curation"}

    if not recipient_list:
        return {"sent": 0, "failed": 0, "error": "No recipients provided"}

    date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    subject = subject or f"CortexOS · {len(curated)} AI picks · {date_str}"

    sent, failed = 0, []
    async with httpx.AsyncClient(verify=ssl_ctx, timeout=15) as client:
        for rec in recipient_list:
            email = rec.get("email", "").strip().lower()
            name = rec.get("name", "") or ""
            if not email:
                continue
            try:
                r = await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                    json={"from": DIGEST_FROM, "to": [email], "subject": subject, "html": build_html(curated, name)},
                )
                if r.status_code in (200, 201):
                    print(f"  ✅ {email}")
                    sent += 1
                else:
                    print(f"  ❌ {email}: {r.status_code}")
                    failed.append(email)
            except Exception as e:
                print(f"  ❌ {email}: {e}")
                failed.append(email)

    print(f"📧 Digest: {sent} sent, {len(failed)} failed, {len(curated)} articles curated from {len(inbox_items)} inbox items")
    return {"sent": sent, "failed": len(failed), "curated": len(curated), "total_inbox": len(inbox_items)}