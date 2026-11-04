# Marketplace Queue Search

## ➡️ [Search the queue now: drderiv.github.io/marketplace_queue](https://drderiv.github.io/marketplace_queue/)

Unofficial search over the pending submissions to the Home Assistant
[Marketplace](https://www.home-assistant.io/integrations/marketplace/) (formerly HACS) default
catalog, so developers can check whether someone is already building the integration they have
in mind **before** writing it. The queue is the open pull requests on
[hacs/default](https://github.com/hacs/default/pulls), which is still where submissions go.
Entries are unreviewed pull requests; nothing here is endorsed by Home Assistant or the
Marketplace team. If one looks promising, add its repository as a *custom repository*
(Settings → Marketplace → **Add from link**) and test it.

**Test in isolation.** An integration runs with full access to your Home Assistant, including
its credentials and network. A pending entry has not been approved, and a reviewer may or may
not already have looked at it, so it is best to try one in a separate, disposable instance
(for example a throwaway Docker container that you delete afterwards), never on your
production system. Step-by-step instructions are in [TESTING.md](TESTING.md).

* **Web:** `docs/index.html`, served by GitHub Pages (Settings → Pages → deploy from
  branch `main`, folder `/docs`).
* **Command line:** `./search.py sub-zero refrigerator` (`--online` uses the published copy).
* **Data:** `docs/queue.json`, rebuilt nightly by `.github/workflows/nightly.yml`.

## How it works

`fetch_queue.py` lists open PRs (and ones closed or merged in the last 90 days) on
`hacs/default`, takes the submitted repo from the PR title, and enriches each repo with its
GitHub description, topics, Home Assistant `manifest.json` and a plain-text README excerpt.
Searching ignores punctuation, so "sub zero" finds "Sub-Zero". Third-party text is only ever
stored and shown with `textContent`, never executed or rendered as HTML.

**Time window.** Pending submissions (open and draft) are always included. The *Recently merged
into the Marketplace* and *Recently closed without merging* filters cover only the last **90 days**,
judged by when the PR was last updated, so they are a recent-activity view, not the whole catalog.
Check the Marketplace itself for anything older. To change the window, edit `CLOSED_WINDOW_DAYS` at the top
of `fetch_queue.py` (a longer window makes `docs/queue.json` larger).

Unauthenticated GitHub allows 60 API calls an hour, the workflow's token 1,000. A full first
build needs about 2 calls per repo, so it fills in over a few runs (each run resumes from the
cache and the page says "still filling in repository details"). After that only changed
submissions are refetched, and details are refreshed weekly. Trigger extra runs from the
Actions tab (*Run workflow*) to speed up the first fill.

```
python3 -m pytest -q          # tests
python3 fetch_queue.py        # rebuild docs/queue.json (set GITHUB_TOKEN for a higher limit)
```
