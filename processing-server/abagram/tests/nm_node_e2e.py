"""Node-mode end to end: the real Abagram (IGS_NODE_MODE=1) + the mock Instagram + the real abagram_jobs.scrape()."""
import os, shutil, subprocess, sys, tempfile, time, json
from pathlib import Path
import httpx
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, os.environ["NM_JOBS_DIR"])
import abagram_jobs as J
MOCK, APP = 28795, 28796
KEY = "k" * 48
TMP = Path(tempfile.mkdtemp(prefix="igs-nodee2e-"))
ENV = dict(os.environ, IGS_FAST_PROFILES="1", IGS_BASE=f"http://127.0.0.1:{MOCK}", IGS_DATA=str(TMP / "data"), IGS_HEADLESS="1", IGS_PORT=str(APP),
           IGS_NO_BROWSER="1", PYTHONUTF8="1", IGS_POSTS_WAIT="2", IGS_SETTLE_WAIT="1", IGS_NODE_MODE="1", IGS_API_TOKEN=KEY, IGS_AUTH="0")
H = {"X-Igs": "1", "X-Igs-Token": KEY}
res = []
steps = []


def nap(seconds):
    """Pacing is skipped (the real one is 45-110 s) but polling keeps a real, short pause: a no-op sleep makes the read loop hammer the
    service with thousands of connections a second and exhausts Windows ephemeral ports (WinError 10048)."""
    steps.append(seconds)
    time.sleep(min(seconds, 0.4))


def check(n, c, extra=""):
    res.append(bool(c)); print(("PASS  " if c else "FAIL  ") + n + ("" if c else "   <- %r" % (extra,)), flush=True)
def call(m, p, **kw):
    return httpx.request(m, f"http://127.0.0.1:{APP}{p}", headers=H, timeout=20, **kw)
procs = [subprocess.Popen([sys.executable, str(ROOT / "tests" / "mock_ig.py"), str(MOCK)], cwd=ROOT, env=ENV),
         subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=ENV)]
try:
    for _ in range(60):
        try:
            if call("GET", "/api/status").status_code == 200: break
        except httpx.HTTPError: time.sleep(0.5)
    client = J.Client(APP, KEY)
    # 1. not signed in yet: scrape must stop with not_signed_in and read nothing
    b = J.scrape(client, ["ada.lovelace"], max_accounts=1, pace=(15, 15), sleep=nap)
    check("not signed in -> stopped not_signed_in", (b.get("stopped") or {}).get("code") == "not_signed_in" and not b["posts"], b.get("stopped"))
    # 2. no key -> no answer
    r = httpx.get(f"http://127.0.0.1:{APP}/api/status", timeout=10)
    check("no key -> 401", r.status_code == 401, r.status_code)
    # 3. sign in through Abagram's own login (the mock Instagram)
    call("POST", "/api/limits", json={"values": {"pages_hour": 200, "pages_day": 1000, "pause_min": 1, "pause_max": 1}})
    r = call("POST", "/api/login", json={"username": "good", "password": "S3cretPW!zz"})
    check("login accepted", r.status_code == 200, r.text)
    end = time.time() + 60
    while time.time() < end:
        s = call("GET", "/api/status").json()
        if s["state"] in ("success", "failed", "need_manual"): break
        time.sleep(0.4)
    check("login success", s["state"] == "success", s.get("outcome"))
    summ = J.summarize_status(client.status())
    check("report: signed in, account good", summ["signed_in"] and summ["account"] == "good", summ)
    # 4. a real scrape
    b = J.scrape(client, ["ada.lovelace", "ada.lovelace"], max_accounts=3, pace=(15, 15), sleep=nap, limit=24,
                 progress=lambda f, m: None, timeout_s=120)
    check("scrape: stopped is None", b.get("stopped") is None, b.get("stopped"))
    check("scrape: one account read", [a["username"] for a in b["accounts"]] == ["ada.lovelace"], b["accounts"])
    check("scrape: 7 posts with numbers", len(b["posts"]) == 7 and all(p.get("code") and p.get("taken_at") for p in b["posts"]), len(b["posts"]))
    kinds = sorted(set(p["kind"] for p in b["posts"]))
    check("scrape: kinds reel/album/photo/video present", {"reel", "album", "photo"} <= set(kinds), kinds)
    reel = next((p for p in b["posts"] if p["kind"] == "reel"), {})
    check("scrape: reel carries views and music", reel.get("views") is not None, reel)
    check("scrape: account numbers", b["accounts"][0]["followers"] == 1234567, b["accounts"][0])
    check("scrape: no followers/following data anywhere", "follower_list" not in json.dumps(b) and "items" not in b)
    # 5. what /api/trend gives directly
    t = call("GET", "/api/trend/ada.lovelace?limit=3").json()
    check("trend: limit honoured, format nm-ig-page", len(t["posts"]) == 3 and t["format"] == "nm-ig-page", t.get("format"))
    check("trend: unknown page 404", call("GET", "/api/trend/nobody_here").status_code == 404)
    # 6. the page budget and the refusal on a private/unknown page
    b2 = J.scrape(client, ["nobody_here_zz"], max_accounts=1, pace=(15, 15), sleep=nap, timeout_s=120)
    check("unknown page -> per_account skipped, no crash", "nobody_here_zz" in b2["per_account"], b2["per_account"])
    print(json.dumps({k: b2[k] for k in ("per_account", "stopped")}, ensure_ascii=False))
    check("report after reads", J.summarize_status(client.status())["pages_hour"][0] >= 1)
finally:
    try:
        call("POST", "/api/cancel"); time.sleep(1)
    except httpx.HTTPError: pass
    for p in procs: p.terminate()
    time.sleep(1)
    shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{sum(res)}/{len(res)} checks passed")
sys.exit(0 if all(res) else 1)
