import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import fetch_queue as fq
import search


def test_parse_title_standard_and_variants():
    assert fq.parse_title("Adds new integration [drderiv/streamlabs_libre]", []) == ("integration", "drderiv/streamlabs_libre")
    assert fq.parse_title("Adds new plugin [MEbsen/GenvexFlowCard]", []) == ("plugin", "MEbsen/GenvexFlowCard")
    assert fq.parse_title("Add a new entry for foo/bar", []) == ("unknown", "foo/bar")
    assert fq.parse_title("Add drderiv/streamlabs_libre", []) == ("unknown", "drderiv/streamlabs_libre")
    assert fq.parse_title("Add a new theme: foo/bar please", ["New default repository"]) == ("theme", "foo/bar")


def test_parse_title_ignores_unrelated_prs():
    assert fq.parse_title("Remove stale entries", []) is None
    assert fq.parse_title("Adds a removed entry for [foo/bar]", ["New default repository"]) is None
    assert fq.parse_title("Fix typo in docs/readme", []) is None


def test_summarize_readme_strips_markup():
    text = "# Title\n[![badge](x.svg)](y)\n<img src='a'>\nControls your **Sub-Zero** refrigerator over the cloud API.\n```\ncode\n```"
    assert fq.summarize_readme(text) == "Controls your Sub-Zero refrigerator over the cloud API."


def test_summarize_readme_truncates():
    assert len(fq.summarize_readme("word " * 1000)) <= 600


ENTRIES = [
    {"repo": "orienw/ha-subzero", "pr": 5, "state": "merged", "category": "integration", "description": "Sub-Zero refrigerator control", "topics": ["fridge"]},
    {"repo": "a/water-meter", "pr": 9, "state": "open", "category": "integration", "description": "Leak detection", "readme_excerpt": "monitors a subzero freezer"},
    {"repo": "b/card", "pr": 7, "state": "open", "category": "plugin", "description": "Lovelace card"},
]


def test_search_ignores_punctuation_and_ranks_by_field():
    hits = search.search(ENTRIES, ["sub", "zero"])
    assert [e["repo"] for e in hits] == ["orienw/ha-subzero", "a/water-meter"]


def test_search_filters():
    assert search.search(ENTRIES, ["card"], category="integration") == []
    assert [e["pr"] for e in search.search(ENTRIES, ["leak"], state="open")] == [9]
    assert search.search(ENTRIES, ["nothing-matches"]) == []


def test_needs_refresh_uses_updated_at_and_age():
    entry = {"updated_at": "2026-01-01T00:00:00Z"}
    fresh = {"updated_at": "2026-01-01T00:00:00Z", "fetched_at": fq.now_iso()}
    assert not fq.needs_refresh(fresh, entry)
    assert fq.needs_refresh(None, entry)
    assert fq.needs_refresh({**fresh, "updated_at": "2025-12-01T00:00:00Z"}, entry)
    assert fq.needs_refresh({**fresh, "fetched_at": "2020-01-01T00:00:00Z"}, entry)


def test_search_one_entry_per_repo_and_pending_filter():
    entries = [
        {"repo": "x/fridge", "pr": 1, "state": "closed", "category": "integration", "description": "fridge"},
        {"repo": "X/Fridge", "pr": 3, "state": "open", "category": "integration", "description": "fridge"},
    ]
    assert [e["pr"] for e in search.search(entries, ["fridge"])] == [3]
    assert [e["pr"] for e in search.search(entries, ["fridge"], state="pending")] == [3]
    assert search.search(entries, ["fridge"], state="merged") == []


def test_finalize_infers_category():
    manifest = {"category": "unknown", "repo": "a/b", "repo_status": "ok", "domain": "b"}
    card = {"category": "unknown", "repo": "a/foo-card", "repo_status": "ok"}
    missing = {"category": "unknown", "repo": "a/c", "repo_status": "missing"}
    for entry in (manifest, card, missing):
        fq.finalize(entry)
    assert (manifest["category"], card["category"], missing["category"]) == ("integration", "plugin", "unknown")
