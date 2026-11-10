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


def test_write_status_records_run(tmp_path):
    path = tmp_path / "docs" / "status.json"
    fq.write_status(path, 42, True)
    import json
    data = json.loads(path.read_text())
    assert data["entries"] == 42 and data["complete"] is True and data["checked_at"].endswith("Z")


def test_one_failing_repo_does_not_abort_the_run(tmp_path, monkeypatch):
    import json, urllib.error
    pr = lambda n, title: {"number": n, "title": title, "labels": [{"name": "New default repository"}], "state": "open",
                           "draft": False, "html_url": f"https://github.com/hacs/default/pull/{n}",
                           "user": {"login": "u"}, "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}
    monkeypatch.setattr(fq, "list_prs", lambda state, since: [pr(1, "Adds new integration [a/bad]"), pr(2, "Adds new integration [a/good]")] if state == "open" else [])
    def fake_enrich(entry):
        if entry["repo"] == "a/bad":
            raise urllib.error.URLError("boom")
        entry["fetched_at"] = fq.now_iso()
        entry["repo_status"] = "ok"
    monkeypatch.setattr(fq, "enrich", fake_enrich)
    out = tmp_path / "docs" / "queue.json"
    monkeypatch.setattr("sys.argv", ["fetch_queue.py", "--output", str(out)])
    assert fq.main() == 0
    entries = {e["repo"]: e for e in json.loads(out.read_text())["entries"]}
    assert set(entries) == {"a/bad", "a/good"} and "fetched_at" in entries["a/good"]
    assert json.loads(out.with_name("status.json").read_text())["complete"] is False


def test_request_retries_when_connection_drops_mid_reply(monkeypatch):
    """Regression: RemoteDisconnected is not a URLError and failed the 2026-11-10 nightly run."""
    import http.client

    calls = []

    class Reply:
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def read(self): return b"{}"

    def flaky(request, timeout):
        calls.append(1)
        if len(calls) < 3:
            raise http.client.RemoteDisconnected("Remote end closed connection without response")
        return Reply()

    monkeypatch.setattr(fq.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(fq.time, "sleep", lambda s: None)
    body, _ = fq._request("https://api.github.com/x")
    assert body == b"{}" and len(calls) == 3


def test_persistent_connection_drop_skips_only_that_repo(tmp_path, monkeypatch):
    import http.client, json
    monkeypatch.setattr(fq, "list_prs", lambda state, since: [{"number": 1, "title": "Adds new integration [a/x]", "labels": [], "state": "open",
        "draft": False, "html_url": "https://github.com/hacs/default/pull/1", "user": {"login": "u"},
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}] if state == "open" else [])
    def boom(entry):
        raise http.client.RemoteDisconnected("closed")
    monkeypatch.setattr(fq, "enrich", boom)
    out = tmp_path / "queue.json"
    monkeypatch.setattr("sys.argv", ["fetch_queue.py", "--output", str(out)])
    assert fq.main() == 0
    assert [e["repo"] for e in json.loads(out.read_text())["entries"]] == ["a/x"]
