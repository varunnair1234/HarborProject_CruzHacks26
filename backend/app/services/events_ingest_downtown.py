import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Set
from urllib.parse import urljoin

import requests


DOWNTOWN_BASE = "https://downtownsantacruz.com"
SITEMAP_URL = urljoin(DOWNTOWN_BASE, "/sitemap.xml")


@dataclass
class RawEvent:
    source: str               # "downtownsantacruz"
    source_id: str            # stable-ish, e.g. url path
    title: str
    description: str
    start_time_text: str      # keep as text for hackathon; parse later if needed
    location: str
    url: str
    fetched_at_utc: str


def _app_env() -> str:
    return os.getenv("APP_ENV", "dev").lower()


def _http_get(url: str, timeout_s: int = 20) -> str:
    r = requests.get(url, timeout=timeout_s, headers={"User-Agent": "HarborShoplineBot/1.0"})
    r.raise_for_status()
    return r.text


def discover_event_urls(
    limit: int = 200,
    seed_urls: Optional[List[str]] = None,
) -> List[str]:
    """
    Best-effort URL discovery.
    1) Parse sitemap.xml and pull /do/ URLs
    2) Merge seed_urls (optional)
    """
    urls: Set[str] = set()

    # 1) sitemap best-effort
    try:
        xml = _http_get(SITEMAP_URL)
        # naive extraction of <loc>...</loc>
        locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", xml)
        for u in locs:
            if "/do/" in u:
                urls.add(u.strip())
    except Exception:
        # If sitemap changes/fails, we still can rely on seeds
        pass

    # 2) seeds
    if seed_urls:
        for u in seed_urls:
            if u.startswith("/"):
                urls.add(urljoin(DOWNTOWN_BASE, u))
            else:
                urls.add(u)

    # Return a stable list
    out = sorted(urls)
    return out[:limit]


def parse_do_event_page(url: str) -> Optional[RawEvent]:
    """
    Parse an individual DowntownSantaCruz /do/... page.
    This is heuristic: HTML structure can vary.
    """
    try:
        html = _http_get(url)
    except Exception:
        return None

    # Title: <h1 ...>Title</h1>
    m_title = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    title = _strip_tags(m_title.group(1)).strip() if m_title else ""

    # Description: try meta description first, then fallback to first long-ish paragraph
    m_desc = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', html, re.IGNORECASE)
    description = (m_desc.group(1).strip() if m_desc else "")
    if not description:
        # fallback: first <p> with some length
        ps = re.findall(r"<p[^>]*>(.*?)</p>", html, re.IGNORECASE | re.DOTALL)
        for p in ps:
            text = _strip_tags(p).strip()
            if len(text) >= 80:
                description = text
                break

    # Time-ish: look for common “When” labels or datetime strings
    start_time_text = ""
    # common patterns: "When:" ... or "Date:" ...
    m_when = re.search(r"(When|Date)\s*:</strong>\s*(.*?)<", html, re.IGNORECASE | re.DOTALL)
    if m_when:
        start_time_text = _strip_tags(m_when.group(2)).strip()
    if not start_time_text:
        # fallback: any "Jan 1, 2026" etc
        m_date = re.search(
            r"([A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4}(?:\s+at\s+[^<]+)?)",
            html,
        )
        if m_date:
            start_time_text = m_date.group(1).strip()

    # Location-ish: look for "Where:" or address-like blocks
    location = ""
    m_where = re.search(r"(Where|Location)\s*:</strong>\s*(.*?)<", html, re.IGNORECASE | re.DOTALL)
    if m_where:
        location = _strip_tags(m_where.group(2)).strip()

    if not location:
        # fallback: try to find a street-ish line
        m_addr = re.search(r"(\d{2,5}\s+[A-Za-z0-9 .'-]+,\s*Santa\s*Cruz[^<]*)", html, re.IGNORECASE)
        if m_addr:
            location = m_addr.group(1).strip()

    if not title:
        return None

    fetched_at_utc = datetime.now(timezone.utc).isoformat()
    source_id = url.replace(DOWNTOWN_BASE, "").strip() or url

    return RawEvent(
        source="downtownsantacruz",
        source_id=source_id,
        title=title,
        description=description,
        start_time_text=start_time_text,
        location=location,
        url=url,
        fetched_at_utc=fetched_at_utc,
    )


def ingest_downtown_events(
    limit_urls: int = 200,
    seed_urls: Optional[List[str]] = None,
) -> List[RawEvent]:
    """
    In dev/test, you can optionally allow fixtures (not implemented here).
    In prod, we enforce real sources only.
    """
    env = _app_env()
    if env == "prod":
        # enforce: no fixtures; only real sources
        pass

    urls = discover_event_urls(limit=limit_urls, seed_urls=seed_urls)
    events: List[RawEvent] = []
    for u in urls:
        ev = parse_do_event_page(u)
        if ev:
            events.append(ev)
    return events


def _strip_tags(s: str) -> str:
    # very small HTML -> text helper
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"&nbsp;", " ", s)
    s = re.sub(r"&amp;", "&", s)
    s = re.sub(r"&quot;", '"', s)
    s = re.sub(r"&#39;", "'", s)
    return s
