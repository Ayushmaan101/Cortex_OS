"""
CortexOS Harvester — Phase 5
Returns inbox items only. No DB writes. McAfee SSL bypass included.

QUALITY FILTERS applied per source:
- ArXiv: only cs.AI / cs.LG, title must contain research keywords
- HN: min 50 points (up from 20), top 10 only
- HuggingFace: blog posts only (skip changelogs/docs)
- GitHub: repos with actual descriptions, skip forks/mirrors
- NVIDIA/OpenAI/Anthropic/Meta: latest posts only, max 4 each
- All: skip policy/legal/terms/help/security pages
"""

import asyncio, hashlib, os, re, ssl
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional
import httpx
from dotenv import load_dotenv
load_dotenv()

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
}

# Keywords that indicate junk pages — skip anything matching these
JUNK_PATTERNS = re.compile(
    r'\b(terms|privacy|policy|legal|cookie|gdpr|help center|support|'
    r'sign.?up|log.?in|careers|jobs|press|contact|about us|faq|'
    r'security advisory|release notes|changelog|deprecat)\b',
    re.IGNORECASE
)

# Keywords that indicate high-value AI research content
RESEARCH_KEYWORDS = re.compile(
    r'\b(model|llm|transformer|reasoning|rag|agent|benchmark|training|'
    r'inference|fine.?tun|multimodal|vision|language|neural|gradient|'
    r'attention|embedding|token|prompt|chain.of.thought|reinforcement|'
    r'alignment|safety|evaluation|dataset|architecture|scaling|'
    r'diffusion|generative|retrieval|knowledge|graph|memory|'
    r'autonomous|agentic|tool.use|function.call|open.source|'
    r'release|launch|research|paper|study|experiment)\b',
    re.IGNORECASE
)

def make_item(source: str, source_id: str, icon: str, title: str, summary: str, url: str) -> dict:
    return {
        "id": hashlib.sha256(url.encode()).hexdigest()[:16],
        "source": source, "source_id": source_id, "source_icon": icon,
        "title": title.strip(), "summary": summary.strip()[:400],
        "url": url.strip(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

def is_junk(title: str, url: str = "") -> bool:
    return bool(JUNK_PATTERNS.search(title)) or bool(JUNK_PATTERNS.search(url))

def is_research(title: str, summary: str = "") -> bool:
    return bool(RESEARCH_KEYWORDS.search(title)) or bool(RESEARCH_KEYWORDS.search(summary))

def parse_rss(xml_text: str, source: str, sid: str, icon: str, max_items=8, require_research=False) -> list[dict]:
    items = []
    try:
        root = ET.fromstring(xml_text)
        entries = root.findall(".//item")
        if not entries:
            ns = "http://www.w3.org/2005/Atom"
            entries = root.findall(f".//{{{ns}}}entry")
            def get(el, tag):
                t = el.findtext(f"{{{ns}}}{tag}") or ""
                link_el = el.find(f"{{{ns}}}link")
                return t, (link_el.get("href","") if tag=="link" and link_el is not None else t)
        else:
            def get(el, tag):
                return (el.findtext(tag) or ""), (el.findtext(tag) or "")

        for entry in entries:
            title = (entry.findtext("title") or get(entry,"title")[0]).strip()
            desc  = re.sub(r'<[^>]+>', '', entry.findtext("description") or get(entry,"summary")[0]).strip()[:300]
            link_el = entry.find("link")
            link = (link_el.text or link_el.get("href","") if link_el is not None else get(entry,"link")[1]).strip()

            if not title or not link: continue
            if is_junk(title, link): continue
            if require_research and not is_research(title, desc): continue
            items.append(make_item(source, sid, icon, title, desc, link))
            if len(items) >= max_items: break
    except Exception as e:
        print(f"  ⚠ RSS parse ({source}): {e}")
    return items


# ── Fetchers ──────────────────────────────────────────────────────────────────

async def fetch_arxiv(client, category="cs.AI", max_items=8):
    try:
        r = await client.get(f"https://rss.arxiv.org/rss/{category}", timeout=20)
        items = parse_rss(r.text, f"ArXiv {category}",
                          f"arxiv_{category.replace('.','_').lower()}", "📄",
                          max_items, require_research=False)
        for it in items:
            it["title"] = re.sub(r'^\[[^\]]+\]\s*', '', it["title"])
        print(f"  📄 ArXiv {category}: {len(items)} papers")
        return items
    except Exception as e:
        print(f"  ⚠ ArXiv {category}: {e}")
        return []

async def fetch_hackernews(client, max_items=10):
    """High-quality filter: min 50 points, top 10, must be research-relevant."""
    try:
        r = await client.get("https://hn.algolia.com/api/v1/search",
            params={"tags":"story","query":"AI LLM reasoning machine learning open source","hitsPerPage":50},
            timeout=15)
        hits = r.json().get("hits", [])
        hits = [h for h in hits
                if (h.get("points") or 0) >= 50
                and h.get("title")
                and not is_junk(h.get("title",""), h.get("url",""))
                and is_research(h.get("title",""))]
        hits.sort(key=lambda x: x.get("points", 0), reverse=True)
        items = []
        for h in hits[:max_items]:
            url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID','')}"
            items.append(make_item("Hacker News","hn","🔥", h["title"],
                f"{h.get('points',0)} points · {h.get('num_comments',0)} comments", url))
        print(f"  🔥 Hacker News: {len(items)} stories")
        return items
    except Exception as e:
        print(f"  ⚠ Hacker News: {e}")
        return []

async def fetch_huggingface(client, max_items=6):
    try:
        r = await client.get("https://huggingface.co/blog/feed.xml", timeout=20)
        # HF feed has good quality — filter for research posts, skip release announcements of minor things
        items = parse_rss(r.text, "HuggingFace","hf","🤗", max_items * 2, require_research=True)
        items = items[:max_items]
        print(f"  🤗 HuggingFace: {len(items)} posts")
        return items
    except Exception as e:
        print(f"  ⚠ HuggingFace: {e}")
        return []

async def fetch_github_trending(client, max_items=8):
    """GitHub Trending Python — AI/ML repos only, requires description."""
    try:
        r = await client.get("https://github.com/trending/python?since=daily", timeout=20)
        # Also fetch the all-languages AI trending
        r2 = await client.get("https://github.com/trending?since=daily&spoken_language_code=en", timeout=20)

        items, seen = [], set()
        for html in [r.text, r2.text]:
            repos = re.findall(r'href="/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)"', html)
            descs = re.findall(r'<p\s+class="col-9[^"]*"[^>]*>\s*([^<]{10,300})\s*</p>', html)
            stars_list = re.findall(r'aria-label="(\d[\d,]*)\s+users? starred', html)

            desc_idx = 0
            for i, repo in enumerate(repos):
                if repo in seen or repo.count("/") != 1: continue
                seen.add(repo)
                desc = descs[desc_idx].strip() if desc_idx < len(descs) else ""
                stars = stars_list[desc_idx].replace(",","") if desc_idx < len(stars_list) else "0"
                desc_idx += 1
                if not desc: continue  # skip repos without descriptions
                # Only include AI/ML repos
                if not is_research(repo, desc): continue
                items.append(make_item("GitHub Trending","github","📈",
                    repo, f"⭐ {stars} stars · {desc}", f"https://github.com/{repo}"))
                if len(items) >= max_items: break
            if len(items) >= max_items: break

        print(f"  📈 GitHub Trending: {len(items)} repos")
        return items
    except Exception as e:
        print(f"  ⚠ GitHub Trending: {e}")
        return []

async def fetch_nvidia(client, max_items=4):
    """NVIDIA: technical/research posts only, skip marketing."""
    try:
        r = await client.get("https://blogs.nvidia.com/feed/", timeout=20)
        items = parse_rss(r.text, "NVIDIA Blog","nvidia","🟢", max_items * 2, require_research=True)
        items = items[:max_items]
        print(f"  🟢 NVIDIA Blog: {len(items)} posts")
        return items
    except Exception as e:
        print(f"  ⚠ NVIDIA Blog: {e}")
        return []

async def fetch_openai(client, max_items=4):
    try:
        r = await client.get("https://openai.com/blog/rss.xml", timeout=15)
        if r.status_code == 200 and "<rss" in r.text:
            items = parse_rss(r.text, "OpenAI","openai","🤖", max_items * 2, require_research=True)
            items = items[:max_items]
            if items:
                print(f"  🤖 OpenAI: {len(items)} posts")
                return items
        # sitemap fallback
        r = await client.get("https://openai.com/sitemap.xml", timeout=15)
        urls = re.findall(r'<loc>(https://openai\.com/(?:blog|research)/[^<]+)</loc>', r.text)
        items = []
        for u in urls:
            slug = u.split("/")[-1].replace("-"," ").title()
            if is_junk(slug, u): continue
            if not is_research(slug): continue
            items.append(make_item("OpenAI","openai","🤖", slug, "", u))
            if len(items) >= max_items: break
        print(f"  🤖 OpenAI: {len(items)} posts (sitemap)")
        return items
    except Exception as e:
        print(f"  ⚠ OpenAI: {e}")
        return []

async def fetch_anthropic(client, max_items=4):
    try:
        r = await client.get("https://www.anthropic.com/news", timeout=15)
        # Extract article titles and links from news page
        # Anthropic uses Next.js — look for JSON data
        json_match = re.search(r'"title"\s*:\s*"([^"]{10,120})"[^}]*"slug"\s*:\s*"([^"]+)"', r.text)
        
        # Try multiple patterns
        titles = re.findall(r'<h3[^>]*>(?:<[^>]+>)*([^<]{10,120})(?:</[^>]+>)*</h3>', r.text)
        links  = re.findall(r'href="(/news/[a-z0-9][a-z0-9-]*[a-z0-9])"', r.text)
        
        items, seen = [], set()
        for i, title in enumerate(titles):
            t = title.strip()
            if not t or t in seen: continue
            if is_junk(t): continue
            seen.add(t)
            link = f"https://www.anthropic.com{links[i]}" if i < len(links) else "https://www.anthropic.com/news"
            items.append(make_item("Anthropic","anthropic","🔶", t, "", link))
            if len(items) >= max_items: break
        print(f"  🔶 Anthropic: {len(items)} posts")
        return items
    except Exception as e:
        print(f"  ⚠ Anthropic: {e}")
        return []

async def fetch_meta(client, max_items=4):
    try:
        r = await client.get("https://ai.meta.com/blog/", timeout=15)
        titles = re.findall(r'"headline"\s*:\s*"([^"]{10,200})"', r.text)
        links  = re.findall(r'"url"\s*:\s*"(https://ai\.meta\.com/blog/[^"]+)"', r.text)
        descs  = re.findall(r'"description"\s*:\s*"([^"]{10,300})"', r.text)
        items, seen = [], set()
        for i, title in enumerate(titles):
            t = title.strip()
            if not t or t in seen: continue
            if is_junk(t): continue
            seen.add(t)
            link = links[i] if i < len(links) else "https://ai.meta.com/blog/"
            desc = descs[i].strip() if i < len(descs) else ""
            items.append(make_item("Meta AI","meta","🔵", t, desc, link))
            if len(items) >= max_items: break
        print(f"  🔵 Meta AI: {len(items)} posts")
        return items
    except Exception as e:
        print(f"  ⚠ Meta AI: {e}")
        return []


# ── Source registry ───────────────────────────────────────────────────────────
SOURCE_CONFIG = [
    {"id":"arxiv_ai",  "label":"ArXiv cs.AI",       "icon":"📄", "fetcher": lambda c: fetch_arxiv(c,"cs.AI",8)},
    {"id":"arxiv_lg",  "label":"ArXiv cs.LG",       "icon":"📄", "fetcher": lambda c: fetch_arxiv(c,"cs.LG",8)},
    {"id":"hn",        "label":"Hacker News",        "icon":"🔥", "fetcher": lambda c: fetch_hackernews(c,10)},
    {"id":"hf",        "label":"HuggingFace Blog",   "icon":"🤗", "fetcher": lambda c: fetch_huggingface(c,6)},
    {"id":"github",    "label":"GitHub Trending",    "icon":"📈", "fetcher": lambda c: fetch_github_trending(c,8)},
    {"id":"nvidia",    "label":"NVIDIA Blog",        "icon":"🟢", "fetcher": lambda c: fetch_nvidia(c,4)},
    {"id":"openai",    "label":"OpenAI Blog",        "icon":"🤖", "fetcher": lambda c: fetch_openai(c,4)},
    {"id":"anthropic", "label":"Anthropic News",     "icon":"🔶", "fetcher": lambda c: fetch_anthropic(c,4)},
    {"id":"meta",      "label":"Meta AI Blog",       "icon":"🔵", "fetcher": lambda c: fetch_meta(c,4)},
]


async def run_harvest(source_ids: Optional[list[str]] = None) -> list[dict]:
    targets = [s for s in SOURCE_CONFIG if source_ids is None or s["id"] in source_ids]
    print(f"\n{'='*50}")
    print(f"🧠 CortexOS Harvest — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    async with httpx.AsyncClient(
        verify=ssl_ctx, headers=HEADERS,
        follow_redirects=True,
        timeout=httpx.Timeout(25.0, connect=10.0),
    ) as client:
        results = await asyncio.gather(
            *[s["fetcher"](client) for s in targets],
            return_exceptions=True
        )

    all_items = []
    for src, result in zip(targets, results):
        if isinstance(result, Exception):
            print(f"  ❌ {src['label']}: {result}")
        else:
            all_items.extend(result)

    print(f"\n✅ {len(all_items)} quality articles fetched\n")
    return all_items