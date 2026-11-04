#!/usr/bin/env python3
"""Search the Marketplace (formerly HACS) queue snapshot from the command line.

    ./search.py sub-zero refrigerator
    ./search.py --category integration --state open water leak

Reads docs/queue.json next to this script, or the published copy with --online.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

LOCAL = Path(__file__).parent / "docs" / "queue.json"
ONLINE = "https://drderiv.github.io/marketplace_queue/queue.json"

# (field, weight); keep in sync with docs/index.html
FIELDS = (
    ("repo", 3),
    ("name", 3),
    ("domain", 3),
    ("topics", 3),
    ("description", 2),
    ("readme_excerpt", 1),
)


def squash(text: str) -> str:
    """Lowercase and drop punctuation so "Sub-Zero" matches "subzero"."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def field_text(entry: dict, field: str) -> str:
    value = entry.get(field, "")
    return " ".join(value) if isinstance(value, list) else str(value)


def score(entry: dict, terms: list[str]) -> int:
    """Sum of field weights for every query term found in the entry (0 = no match)."""
    total = 0
    squashed = {field: squash(field_text(entry, field)) for field, _ in FIELDS}
    for term in terms:
        total += sum(weight for field, weight in FIELDS if term in squashed[field])
    return total


def query_terms(query: list[str]) -> list[str]:
    terms = [squash(word) for word in query if squash(word)]
    if len(terms) > 1:
        terms.append("".join(terms))  # "sub zero" also tries "subzero"
    return terms


def latest_per_repo(entries: list[dict]) -> list[dict]:
    """One entry per repository: its newest PR (resubmissions create several)."""
    newest: dict[str, dict] = {}
    for entry in entries:
        key = entry["repo"].lower()
        if key not in newest or entry["pr"] > newest[key]["pr"]:
            newest[key] = entry
    return list(newest.values())


def state_matches(entry: dict, state: str | None) -> bool:
    if not state:
        return True
    if state == "pending":
        return entry["state"] in ("open", "draft")
    return entry["state"] == state


def search(entries: list[dict], query: list[str], category: str | None = None, state: str | None = None):
    terms = query_terms(query)
    hits = []
    for entry in latest_per_repo(entries):
        if category and entry.get("category") != category:
            continue
        if not state_matches(entry, state):
            continue
        if (points := score(entry, terms)):
            hits.append((points, entry))
    return [e for _, e in sorted(hits, key=lambda h: (-h[0], -h[1]["pr"]))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("query", nargs="+")
    parser.add_argument("--category", help="e.g. integration, plugin, theme")
    parser.add_argument("--state", choices=("pending", "open", "draft", "merged", "closed"), help="pending = open or draft")
    parser.add_argument("--online", action="store_true", help="use the published queue.json")
    parser.add_argument("--limit", type=int, default=15)
    args = parser.parse_args()

    if args.online:
        with urllib.request.urlopen(ONLINE, timeout=30) as resp:
            data = json.load(resp)
    else:
        data = json.loads(LOCAL.read_text())
    hits = search(data["entries"], args.query, args.category, args.state)
    print(f"Queue snapshot: {data['generated_at']}  ({len(data['entries'])} entries)\n")
    if not hits:
        print("No matches.")
    for entry in hits[: args.limit]:
        print(f"[{entry['state']}] {entry['repo']}  ({entry['category']}, PR #{entry['pr']})")
        if entry.get("description"):
            print(f"    {entry['description']}")
        print(f"    https://github.com/{entry['repo']}   {entry['pr_url']}")
    if len(hits) > args.limit:
        print(f"\n... and {len(hits) - args.limit} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
