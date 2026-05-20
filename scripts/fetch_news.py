#!/usr/bin/env python3
"""
Fetch Google News RSS for every company referenced in index.html
and write the aggregated result to news.json at the repo root.

Run locally:    python scripts/fetch_news.py
Run in CI:      see .github/workflows/fetch-news.yml
"""

import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "index.html"
OUTPUT = REPO_ROOT / "news.json"

# Tuning knobs
PER_COMPANY = 4          # max items kept per company
MAX_AGE_DAYS = 21        # drop anything older than this
HTTP_TIMEOUT = 20        # seconds


def extract_companies(html_text: str) -> list[str]:
    """Pull company names out of the PHASES JS literal in index.html."""
    # Matches: { name: "Company Name", badges: [...
    pattern = re.compile(r'\{\s*name:\s*"([^"]+)"\s*,\s*badges:')
    seen, out = set(), []
    for name in pattern.findall(html_text):
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def fetch_feed(company: str) -> bytes | None:
    q = urllib.parse.quote(company)
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (news-bot)"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.read()
    except Exception as e:
        print(f"  ! fetch failed for {company}: {e}", file=sys.stderr)
        return None


def parse_feed(xml_bytes: bytes | None, company: str) -> list[dict]:
    if not xml_bytes:
        return []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        print(f"  ! parse error for {company}: {e}", file=sys.stderr)
        return []

    items = []
    for item in root.findall(".//item")[:PER_COMPANY]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pubdate = (item.findtext("pubDate") or "").strip()

        source_el = item.find("source")
        source = (source_el.text or "").strip() if source_el is not None else ""

        try:
            dt = parsedate_to_datetime(pubdate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            dt = datetime.now(timezone.utc)

        # Google News appends " - Source" to titles; strip it
        title = re.sub(r"\s+-\s+[^-]+$", "", title)

        items.append({
            "company": company,
            "title": title,
            "link": link,
            "source": source,
            "published": dt.astimezone(timezone.utc).isoformat(),
        })
    return items


def main() -> int:
    if not INDEX_HTML.exists():
        print(f"index.html not found at {INDEX_HTML}", file=sys.stderr)
        return 1

    html_text = INDEX_HTML.read_text(encoding="utf-8")
    companies = extract_companies(html_text)
    print(f"Found {len(companies)} companies")

    all_items: list[dict] = []
    for i, company in enumerate(companies, 1):
        print(f"[{i}/{len(companies)}] {company}")
        all_items.extend(parse_feed(fetch_feed(company), company))

    cutoff = datetime.now(timezone.utc).timestamp() - MAX_AGE_DAYS * 86400
    all_items = [
        it for it in all_items
        if datetime.fromisoformat(it["published"]).timestamp() >= cutoff
    ]
    all_items.sort(key=lambda x: x["published"], reverse=True)

    payload = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "companies": len(companies),
        "items": all_items,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {len(all_items)} items to {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
