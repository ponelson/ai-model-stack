#!/usr/bin/env python3
"""
Generate a daily brief from news.json using heuristic grouping.

Reads news.json, filters to recent items, groups by stack layer (extracted from
index.html), dedupes near-duplicate stories, and writes brief.json.

No external API calls — runs entirely locally in the workflow.
"""

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NEWS_FILE = REPO_ROOT / "news.json"
INDEX_HTML = REPO_ROOT / "index.html"
OUTPUT = REPO_ROOT / "brief.json"

RECENT_HOURS = 30
STORIES_PER_SECTION = 5
MAX_SECTIONS = 10


def load_news() -> list:
    if not NEWS_FILE.exists():
        print("news.json not found; run fetch_news.py first.", file=sys.stderr)
        sys.exit(1)
    data = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    return data.get("items", [])


def extract_company_to_layer(html_text: str) -> dict:
    mapping = {}
    layer_starts = list(re.finditer(r'name:\s*"([^"]+)",\s*\n\s*def:', html_text))
    for i, m in enumerate(layer_starts):
        layer_name = m.group(1)
        start = m.end()
        end = layer_starts[i + 1].start() if i + 1 < len(layer_starts) else len(html_text)
        for cm in re.finditer(r'\{\s*name:\s*"([^"]+)"\s*,\s*badges:', html_text[start:end]):
            mapping[cm.group(1)] = layer_name
    return mapping


def filter_recent(items: list, hours: int) -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return [it for it in items if datetime.fromisoformat(it["published"]) >= cutoff]


def title_key(title: str) -> str:
    """Normalized fingerprint of a story title for dedup."""
    cleaned = re.sub(r"[^\w\s]", "", title.lower())
    return " ".join(cleaned.split()[:8])


def dedup(items: list) -> list:
    """Collapse near-duplicate stories; keep the newest version of each."""
    seen = {}
    for it in items:
        key = title_key(it["title"])
        if key not in seen or it["published"] > seen[key]["published"]:
            seen[key] = it
    return sorted(seen.values(), key=lambda x: x["published"], reverse=True)


def build_brief(items: list, layer_map: dict) -> dict:
    by_layer = defaultdict(list)
    for it in items:
        layer = layer_map.get(it["company"])
        if layer:
            by_layer[layer].append(it)

    # Dedup within each layer
    for layer in by_layer:
        by_layer[layer] = dedup(by_layer[layer])

    # Sort layers by story volume, descending
    ordered = sorted(by_layer.items(), key=lambda x: -len(x[1]))

    sections = []
    for layer_name, layer_items in ordered[:MAX_SECTIONS]:
        if not layer_items:
            continue
        # Summarize the most active companies in this layer
        counts = defaultdict(int)
        for it in layer_items:
            counts[it["company"]] += 1
        top = sorted(counts.items(), key=lambda x: -x[1])[:3]
        top_str = ", ".join(f"{c} ({n})" if n > 1 else c for c, n in top)
        story_word = "story" if len(layer_items) == 1 else "stories"

        sections.append({
            "title": layer_name,
            "analysis": (
                f"{len(layer_items)} {story_word} in the last 24 hours. "
                f"Most active: {top_str}."
            ),
            "stories": layer_items[:STORIES_PER_SECTION],
        })

    total = sum(len(v) for v in by_layer.values())
    top_layer = ordered[0][0] if ordered else "—"

    return {
        "headline": f"{total} stories across {len(by_layer)} layers — {top_layer} most active",
        "lede": (
            "Daily roundup of news across the AI infrastructure stack. "
            "Stories are grouped by layer, ordered by volume, with near-duplicate "
            "headlines collapsed. Click any item to read the source."
        ),
        "sections": sections,
        "date": datetime.now(timezone.utc).isoformat(),
        "item_count": total,
    }


def main() -> int:
    items = load_news()
    recent = filter_recent(items, RECENT_HOURS)
    if not recent:
        print("No recent news items. Skipping brief.")
        return 0
    layer_map = extract_company_to_layer(INDEX_HTML.read_text(encoding="utf-8"))
    brief = build_brief(recent, layer_map)
    OUTPUT.write_text(json.dumps(brief, indent=2), encoding="utf-8")
    print(f"Wrote brief: {brief['item_count']} items, {len(brief['sections'])} sections")
    return 0


if __name__ == "__main__":
    sys.exit(main())
