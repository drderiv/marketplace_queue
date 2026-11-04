#!/usr/bin/env python3
"""Build docs/queue.json: a searchable snapshot of the Home Assistant Marketplace (formerly HACS) default-repository queue.

Lists the open (and recently closed/merged) "new default repository" pull requests
on hacs/default, then enriches each submitted repo with its GitHub description,
topics, Home Assistant manifest and a README excerpt.

Standard library only. Set GITHUB_TOKEN for a usable API rate limit (the Actions
workflow does this automatically). Everything fetched from third-party repos is
treated as untrusted text: it is truncated and stored, never executed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
QUEUE_REPO = "hacs/default"
OUTPUT = Path(__file__).parent / "docs" / "queue.json"

CLOSED_WINDOW_DAYS = 90  # keep closed/merged PRs searchable for this long
REFRESH_DAYS = 7  # re-fetch repo details at least this often
MIN_API_REMAINING = 30  # stop enriching when the API budget drops to this

TITLE_RE = re.compile(
    r"^\s*add(?:s)?\s+(?:new\s+)?(?P<cat>[\w ]*?)\s*\[?(?P<repo>[\w.-]+/[\w.-]+)\]?\s*$",
    re.IGNORECASE,
)
REPO_RE = re.compile(r"(?P<repo>[\w.-]+/[\w.-]+)")
CATEGORIES = (
    "integration",
    "plugin",
    "theme",
    "appdaemon",
    "python_script",
    "template",
    "netdaemon",
)

TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
rate_remaining: int | None = None


class OutOfBudget(Exception):
    """GitHub API budget exhausted; remaining work is deferred to the next run."""


def _request(url: str, *, api: bool = True, accept: str | None = None) -> tuple[bytes, dict]:
    """GET a URL and return (body, headers). Raises urllib.error.HTTPError on failure."""
    global rate_remaining
    headers = {"User-Agent": "marketplace-queue-search", "Accept": accept or "application/vnd.github+json"}
    if TOKEN and api:
        headers["Authorization"] = f"Bearer {TOKEN}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as resp:
                if api and resp.headers.get("X-RateLimit-Remaining"):
                    rate_remaining = int(resp.headers["X-RateLimit-Remaining"])
                return resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as err:
            if err.code in (403, 429) and api and err.headers.get("X-RateLimit-Remaining") == "0":
                rate_remaining = 0
                raise OutOfBudget from err
            if err.code >= 500 and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def api_json(path: str):
    if rate_remaining is not None and rate_remaining <= MIN_API_REMAINING:
        raise OutOfBudget
    body, headers = _request(f"{API}{path}")
    return json.loads(body), headers


def raw_text(repo: str, path: str, limit: int = 200_000) -> str | None:
    """Fetch a file from the repo's default branch; None when missing."""
    try:
        body, _ = _request(f"{RAW}/{repo}/HEAD/{path}", api=False, accept="text/plain")
    except urllib.error.HTTPError:
        return None
    return body[:limit].decode("utf-8", errors="replace")


def parse_title(title: str, labels: list[str]) -> tuple[str, str] | None:
    """Return (category, "owner/repo") for a new-repository PR title, else None."""
    if re.search(r"\bremov", title, re.IGNORECASE):
        return None  # entries for the removed-repositories list are not new submissions
    match = TITLE_RE.match(title)
    if match:
        category = match["cat"].strip().lower().replace(" ", "_")
        return (category if category in CATEGORIES else "unknown"), match["repo"]
    if "New default repository" in labels:
        found = REPO_RE.search(title)
        if found:
            lowered = title.lower()
            category = next((c for c in CATEGORIES if c in lowered), "unknown")
            return category, found["repo"]
    return None


def summarize_readme(text: str, limit: int = 600) -> str:
    """Plain-text excerpt of a README: no HTML, images, links, headings or badges."""
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[[^\]]*\]:\s*\S+", " ", text)
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^[#>*\-\s|]+", "", line).strip()
        line = re.sub(r"[`*_]{1,3}", "", line)
        if len(line) > 25:  # skip titles, badges, table fragments
            lines.append(line)
    return " ".join(" ".join(lines).split())[:limit]


def list_prs(state: str, since: datetime | None) -> list[dict]:
    prs, page = [], 1
    while True:
        data, _ = api_json(
            f"/repos/{QUEUE_REPO}/pulls?state={state}&sort=updated&direction=desc&per_page=100&page={page}"
        )
        if not data:
            break
        for pr in data:
            if since and datetime.fromisoformat(pr["updated_at"].replace("Z", "+00:00")) < since:
                return prs
            prs.append(pr)
        page += 1
    return prs


def pr_entry(pr: dict) -> dict | None:
    labels = [label["name"] for label in pr["labels"]]
    parsed = parse_title(pr["title"], labels)
    if not parsed:
        return None
    category, repo = parsed
    if pr["state"] == "open":
        state = "draft" if pr.get("draft") else "open"
    else:
        state = "merged" if pr.get("merged_at") else "closed"
    return {
        "repo": repo,
        "category": category,
        "pr": pr["number"],
        "pr_url": pr["html_url"],
        "title": pr["title"][:200],
        "state": state,
        "submitter": pr["user"]["login"],
        "created_at": pr["created_at"],
        "updated_at": pr["updated_at"],
    }


def enrich(entry: dict) -> None:
    """Add GitHub repo details and, for integrations, the HA manifest + README excerpt."""
    repo = entry["repo"]
    try:
        info, _ = api_json(f"/repos/{repo}")
    except urllib.error.HTTPError as err:
        entry["repo_status"] = "missing" if err.code in (404, 451) else f"error {err.code}"
        entry["fetched_at"] = now_iso()
        return
    entry.update(
        repo_status="archived" if info.get("archived") else "ok",
        description=(info.get("description") or "")[:300],
        topics=info.get("topics", [])[:20],
        stars=info.get("stargazers_count", 0),
        pushed_at=info.get("pushed_at"),
        homepage=(info.get("homepage") or "")[:200],
    )
    full_name = info["full_name"]
    readme = raw_text(full_name, "README.md") or raw_text(full_name, "readme.md")
    entry["readme_excerpt"] = summarize_readme(readme) if readme else ""
    if entry["category"] in ("integration", "unknown"):
        try:
            listing, _ = api_json(f"/repos/{full_name}/contents/custom_components")
        except urllib.error.HTTPError:
            listing = []
        domains = [item["name"] for item in listing if isinstance(item, dict) and item.get("type") == "dir"]
        if domains:
            manifest = raw_text(full_name, f"custom_components/{domains[0]}/manifest.json", 20_000)
            try:
                data = json.loads(manifest) if manifest else {}
            except ValueError:
                data = {}
            entry["domain"] = domains[0]
            entry["name"] = str(data.get("name", ""))[:100]
            entry["iot_class"] = str(data.get("iot_class", ""))[:40]
            entry["version"] = str(data.get("version", ""))[:40]
    entry["fetched_at"] = now_iso()


def finalize(entry: dict) -> None:
    """Infer a missing category from what enrich() found (no API calls)."""
    if entry["category"] == "unknown" and entry.get("repo_status") in ("ok", "archived"):
        if entry.get("domain"):
            entry["category"] = "integration"
        elif "card" in entry["repo"].lower():
            entry["category"] = "plugin"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def needs_refresh(old: dict | None, entry: dict) -> bool:
    if not old or "fetched_at" not in old:
        return True
    if old.get("updated_at") != entry["updated_at"]:
        return True
    age = datetime.now(timezone.utc) - datetime.fromisoformat(old["fetched_at"].replace("Z", "+00:00"))
    return age > timedelta(days=REFRESH_DAYS)


def significant(data: dict) -> str:
    """Serialised data without the volatile timestamps, to decide whether to rewrite."""
    return json.dumps({k: v for k, v in data.items() if k not in ("generated_at", "complete")}, sort_keys=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-repos", type=int, default=0, help="enrich at most N repos (0 = until budget runs out)")
    parser.add_argument("--no-closed", action="store_true", help="skip recently closed/merged PRs")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    previous = {}
    if args.output.exists():
        try:
            previous = {e["pr"]: e for e in json.loads(args.output.read_text())["entries"]}
        except (ValueError, KeyError):
            previous = {}

    entries: dict[int, dict] = {}
    complete = True
    try:
        prs = list_prs("open", None)
        if not args.no_closed:
            prs += list_prs("closed", datetime.now(timezone.utc) - timedelta(days=CLOSED_WINDOW_DAYS))
    except OutOfBudget:
        print("Rate limit hit while listing PRs; keeping previous data.", file=sys.stderr)
        return 1
    for pr in prs:
        entry = pr_entry(pr)
        if entry:
            old = previous.get(entry["pr"])
            if old and not needs_refresh(old, entry):
                entry = {**old, **{k: entry[k] for k in ("state", "updated_at", "title")}}
            elif old:
                # keep stale details searchable until the refresh succeeds
                entry = {**old, **entry}
            entries[entry["pr"]] = entry

    todo = sorted(
        (e for e in entries.values() if needs_refresh(previous.get(e["pr"]), e)),
        key=lambda e: (e["state"] not in ("open", "draft"), -e["pr"]),
    )
    enriched = 0
    try:
        for entry in todo:
            if args.max_repos and enriched >= args.max_repos:
                complete = False
                break
            enrich(entry)
            enriched += 1
    except OutOfBudget:
        complete = False
        print(f"API budget exhausted after {enriched} repos; the rest is deferred to the next run.", file=sys.stderr)

    for entry in entries.values():
        finalize(entry)
    result = {
        "generated_at": now_iso(),
        "complete": complete,
        "source": f"https://github.com/{QUEUE_REPO}/pulls",
        "entries": sorted(entries.values(), key=lambda e: -e["pr"]),
    }
    if args.output.exists() and previous and significant(json.loads(args.output.read_text())) == significant(result):
        print("No changes.")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(entries)} entries ({enriched} refreshed, {len(todo) - enriched} deferred); API remaining: {rate_remaining}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
