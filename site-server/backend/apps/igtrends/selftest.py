"""The acceptance check of the Instagram reader on a processing node (for the automatic node self-test run).

Two small jobs, in this order. Nothing here posts, follows or messages anyone; the page read is ONE public page, only when the node
reports itself signed in and ready.

    1. kind `ig.health`   payload {"test_connection": true}
       PASS  meta.ok is true  (Abagram's service is installed, started and answering on 127.0.0.1)
       FAIL  anything else - with the node's own `problem` code in the message (installing / install_error / service_down ...)
    2. kind `ig.scrape`   payload {"accounts": ["instagram"], "max_accounts": 1, "pace_s": [15, 15], "fresh": false, "posts_per_account": 6}
       SKIP  when step 1's report is not `ready` (not signed in, line closed ...): a person has to sign in once; that is not a defect
       PASS  meta.accounts_read == 1 and meta.posts > 0
       SKIP  meta.stopped is set with code in {limit, budget, challenge, not_signed_in, unreachable}: Instagram or the line said no - the stop itself worked
       FAIL  otherwise

`evaluate(step, meta)` returns {"status": "pass"|"skip"|"fail", "message": <Persian>} and is what a registered self-test module calls.
"""
from __future__ import annotations

HEALTH = {"kind": "ig.health", "payload": {"test_connection": True}, "timeout_s": 180}
SCRAPE = {"kind": "ig.scrape", "payload": {"accounts": ["instagram"], "max_accounts": 1, "pace_s": [15, 15], "fresh": False, "posts_per_account": 6},
          "timeout_s": 900}
BENIGN_STOPS = {"limit", "budget", "challenge", "not_signed_in", "unreachable", "busy", "cooldown"}
PROBLEM_FA = {
    "installing": "آباگرام هنوز در حالِ نصبِ خودکار است", "install_error": "نصبِ خودکارِ آباگرام خطا دارد", "service_down": "آباگرام روشن نیست",
    "starting": "آباگرام در حالِ روشن‌شدن است", "not_signed_in": "آباگرام هنوز وارد اینستاگرام نشده (یک بار Open-Abagram.bat)",
    "unreachable": "اینستاگرام از این سرور دیده نمی‌شود (VPN/پراکسی)", "cooldown": "آباگرام مکثِ بعد از «صبر کن» دارد",
}


def evaluate(step: str, meta: dict) -> dict:
    meta = meta or {}
    rep = meta.get("report") or {}
    if step == "health":
        if meta.get("ok"):
            extra = "؛ آماده‌ی خواندن" if rep.get("ready") else ("؛ " + PROBLEM_FA.get(rep.get("problem") or "", "") if rep.get("problem") else "")
            return {"status": "pass", "message": "آباگرام روی سرور نصب است و جواب می‌دهد%s" % extra, "ready": bool(rep.get("ready"))}
        return {"status": "fail", "message": PROBLEM_FA.get(rep.get("problem") or "", "آباگرام روی سرور جواب نمی‌دهد") + (": " + rep["error"][:120] if rep.get("error") else ""),
                "ready": False}
    if step == "scrape":
        stop = meta.get("stopped") or {}
        if meta.get("accounts_read") == 1 and (meta.get("posts") or 0) > 0:
            return {"status": "pass", "message": "یک صفحه با %d پست خوانده شد" % meta["posts"]}
        if stop.get("code") in BENIGN_STOPS:
            return {"status": "skip", "message": "خواندن زود متوقف شد (%s) — خودِ توقف درست کار کرد" % stop.get("code")}
        return {"status": "fail", "message": "صفحه خوانده نشد: %s" % (stop.get("message") or "بدونِ توضیح")}
    return {"status": "fail", "message": "مرحلهٔ ناشناخته"}
