# Abagram (آباگرام) — vendored copy for the NMarketing processing node

**What it is.** The owner's own Instagram reader (FastAPI site + a Playwright-driven browser session). The NM node agent
(`processing/abagram_jobs.py`) installs it, starts it as a local service on `127.0.0.1` and calls it for the job kind `ig.scrape`.
It is **never** started by hand and never runs on the office computer for this feature.

## Where it came from
- Source: the owner's office computer, folder `Desktop\instagramScrape` (the running instance there was **not touched**:
  not stopped, not restarted, not modified, and its `data/` was never read or copied). Copied on **2026-11-12**.
- The public GitHub repository `maniUZqqz/InstScr` (HEAD `2a3ec1a`) is **public** and is *older* than this copy.
  It was checked with `git ls-remote` without credentials. Because it is public, this folder is allowed to travel in the public
  Qasem repository; it was nevertheless cleaned of company-internal addresses (see below).

## What was copied
Code only: `app.py`, `ig_*.py`, `requirements.txt`, and the site's `static/` (css, js, fonts, `index.html`, `style.css`, `app.js`;
Vazirmatn font is OFL, see `static/fonts/OFL.txt`).

**Not copied:** `data/` (Instagram session, browser profile, users, tokens, other people's data), `growtech-data.json`,
`tests/` and its `fixtures/` (real Instagram replies), `sql/`, `docs/`, `static/legacy`, `static/aine.html`, logs, `__pycache__`,
`run.bat`, `start-copy.sh`, the README (it names internal servers).

## What was changed (all of it is in `NM-NODE.patch`, made against the untouched original)
1. `ig_common.py`, `ig_login.py` — `IGS_BROWSER_CHANNEL` (e.g. `msedge`, the Edge every Windows 11 has) and `IGS_BROWSER_EXE`
   choose the browser; unset = exactly as before (Playwright's own Chromium).
2. `app.py` — `IGS_NODE_MODE=1`: no AbaOne login; the site answers only with the key in `IGS_API_TOKEN`
   (`X-Igs-Token` header from the agent, or the cookie set by `http://127.0.0.1:<port>/?igs_key=<key>`, which is what
   `Open-Abagram.bat` opens). A key shorter than 32 characters answers nothing. Unset = exactly as before.
3. `ig_trend.py` + `GET /api/trend/<page>` — the recent posts of ONE page with their numbers and the page's public profile
   numbers; never the followers/following lists or anyone else's profile.
4. `tests/` — `test_trend_unit.py`, `test_node_mode.py` with **synthetic** data only (`nm_fixture.py`), and `nm_node_e2e.py`: the real
   Abagram in node mode + a mock Instagram (`mock_ig.py`, the original's own offline stand-in, synthetic accounts; its one masked
   e-mail address was replaced by an example.com one) + the node's real `abagram_jobs.scrape()`. Run it with a Python that has the
   packages of `requirements-node.lock.txt` and a browser: `cd processing/abagram && NM_JOBS_DIR=<processing dir> IGS_BROWSER_CHANNEL=msedge
   python tests/nm_node_e2e.py` (16 checks; 16/16 passed on Windows with Edge on 2026-11-13).

Apply to the original later: `cd <original instagramScrape> && patch -p1 < NM-NODE.patch`.

Cleaning (not in the patch): the office's internal addresses and user id were removed from defaults and comments
(`IGS_LOGIN_API`, `IGS_VPN_API`, `IGS_ADMINS` now default to empty; with an empty VPN gateway the VPN tab simply says it is not
configured). Nothing else differs from the original.

## Re-syncing with a newer original
Copy the new `app.py`, `ig_*.py`, `static/` again, re-apply `NM-NODE.patch` (and the cleaning above), run
`python tests/test_node_mode.py` and `python tests/test_trend_unit.py`, then publish with the site's usual processing update.

## Runtime layout on the node (nothing of it is in this folder)
`<node data folder>\abagram\` — `venv\` (Python packages, `requirements-node.lock.txt`), `data\` (session, profile, limits — the
Instagram login of **this** computer), `logs\`, `service.json` (port and key), `wheelhouse\`, `browser\` (only when Edge is absent).
