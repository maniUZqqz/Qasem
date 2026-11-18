# -*- coding: utf-8 -*-
"""از کاتالوگِ خزیده‌شده تا قطعهٔ قابلِ درج: برای هر کتابخانه‌ای که مخزنِ عمومیِ GitHub دارد (و مجوزش آزاد است)، قطعه‌های با مجوزِ آزادِ 21st.dev را
پیدا می‌کند، «نمونهٔ استفاده» را از صفحهٔ عمومی می‌گیرد، تبدیل می‌کند (c21_convert)، پیش‌نمایش/RTL را می‌سنجد و نتیجه را در رکورد می‌نویسد.

قابلِ ازسرگیری: وضعیتِ هر قطعه در ردیفِ کاتالوگ (``conv``: ok / failed / no-source / license) می‌ماند و فقط ناتمام‌ها دوباره کار می‌شوند؛ هر نوبت زمان‌دار است.
هر مخزن پس از کار پاک می‌شود (فقط فایل‌های کد با sparse-checkout؛ ``_repos`` موقتی است). هیچ‌چیزِ بیرون از GitHub/21st.dev گرفته نمی‌شود.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from pathlib import Path

from services import safenet

from . import c21_convert as CV, c21_crawl, c21_source as SRC, c21st

logger = logging.getLogger(__name__)

RETRY_FAILED_AFTER_S = 7 * 24 * 3600
RUNNING_STALE_S = 1800
CLONE_TIMEOUT = 420
SPARSE = ["*.tsx", "*.jsx", "*.ts", "*.css", "LICENSE*", "COPYING*", "License*", "package.json"]
GITHUB_RE = r"^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$"


def repos_dir() -> Path:
    d = c21st.root() / "_repos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_path() -> Path:
    return c21st.root() / "pipeline.json"


def pipeline_state() -> dict:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _git(args, *, cwd=None, timeout=CLONE_TIMEOUT, runner=subprocess.run):
    r = runner(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": "/tmp"})
    return r


def clone_repo(url: str, dest: Path, *, runner=subprocess.run) -> str:
    """شبه-کلونِ کم‌حجم (بی‌تاریخچه، فقط فایل‌های کد). ⇒ commit. خطا ⇒ ConvertError."""
    import re
    if not re.match(GITHUB_RE, url):
        raise CV.ConvertError("نشانیِ مخزن معتبر نیست")
    shutil.rmtree(dest, ignore_errors=True)
    r = _git(["clone", "--depth", "1", "--filter=blob:none", "--sparse", url, str(dest)], runner=runner)
    if r.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise CV.ConvertError(("کلونِ مخزن نشد: " + (r.stderr or "")[-160:]).strip())
    r = _git(["sparse-checkout", "set", "--no-cone", *SPARSE], cwd=str(dest), runner=runner)
    if r.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise CV.ConvertError(("sparse-checkout نشد: " + (r.stderr or "")[-160:]).strip())
    head = _git(["rev-parse", "HEAD"], cwd=str(dest), runner=runner)
    return (head.stdout or "").strip()[:40]


def _candidates(rows: dict, lib: dict, now: float):
    out = []
    for cid in lib.get("component_ids") or []:
        r = rows.get(cid)
        if not r or not r.get("usable") or not r.get("detail") or len(cid.split("/")) != 2:
            continue
        conv = r.get("conv") or {}
        st = conv.get("state")
        if st in ("ok", "license", "no-source"):
            continue
        if st == "failed" and now - float(conv.get("ts") or 0) < RETRY_FAILED_AFTER_S:
            continue
        out.append(r)
    return out


def run(*, max_seconds: float = 900.0, session: c21_crawl.Session | None = None, libs_limit: int = 5, only_libs=None, runner=subprocess.run, clock=time.monotonic,
        rtl: bool = True) -> dict:
    """یک نوبتِ تبدیل (چند کتابخانه). ⇒ وضعیت {converted, failed, no_source, libs_done, remaining_libs}."""
    started = clock()
    if c21st.is_running():                                   # خزش در حالِ نوشتنِ همان کاتالوگ است؛ دو نویسنده یکدیگر را بازنویسی می‌کردند
        return {"deferred": "crawl-running", "converted": 0, "failed": 0, "no_source": 0, "libs_done": 0, "remaining_libs": 1, "errors": []}
    ps = pipeline_state()
    if ps.get("running") and time.time() - float(ps.get("running_at") or 0) < RUNNING_STALE_S:
        return {"deferred": "pipeline-running", "converted": 0, "failed": 0, "no_source": 0, "libs_done": 0, "remaining_libs": 1, "errors": []}
    _save({**ps, "running": True, "running_at": time.time()})
    try:
        return _run(started, max_seconds, session, libs_limit, only_libs, runner, clock, rtl)
    finally:
        _save({**pipeline_state(), "running": False})


def _run(started, max_seconds, session, libs_limit, only_libs, runner, clock, rtl):
    s = session or c21_crawl.Session()
    rows = {r["id"]: r for r in c21st.load()}
    libs = c21_crawl.load_libs()
    now = time.time()
    todo = [(lid, l) for lid, l in libs.items() if l.get("github") and (not only_libs or lid in only_libs) and _candidates(rows, l, now)]
    todo.sort(key=lambda x: -len(_candidates(rows, x[1], now)))
    st = {"started_at": c21st._now(), "converted": 0, "failed": 0, "no_source": 0, "libs_done": 0, "errors": [], "toolchain": CV.toolchain_ready()}
    if not CV.toolchain_ready() and runner is subprocess.run:
        st["errors"].append("جعبه‌ابزار نصب نیست (/opt/nm-c21)")
        _save(st)
        return st
    new_keys = []
    for lid, lib in todo[:libs_limit]:
        if clock() - started > max_seconds:
            break
        dest = repos_dir() / lid.replace("/", "__")
        try:
            commit = clone_repo(lib["github"], dest, runner=runner)
        except (CV.ConvertError, subprocess.TimeoutExpired) as exc:
            lib["clone_error"] = str(exc)[:160]
            st["errors"].append("%s: %s" % (lid, str(exc)[:120]))
            for r in _candidates(rows, lib, now):
                r["conv"] = {"state": "failed", "error": "clone: " + str(exc)[:120], "ts": now}
            continue
        try:
            lic = SRC.detect_license(dest)
            lib["repo_license"] = lic["spdx"]
            cands = _candidates(rows, lib, now)
            if not SRC.is_permissive_spdx(lic["spdx"]):
                for r in cands:
                    r["conv"] = {"state": "license", "error": "مجوزِ مخزنِ کتابخانه آزاد/معلوم نیست (%s)" % (lic["spdx"] or "بدونِ LICENSE"), "ts": now}
                continue
            idx = SRC.index_repo(dest)
            for r in cands:
                if clock() - started > max_seconds:
                    break
                _one(r, dest, idx, lic, lib, commit, s, st, runner, new_keys)
            st["libs_done"] += 1
        finally:
            shutil.rmtree(dest, ignore_errors=True)
            c21st.save(sorted(rows.values(), key=lambda x: x["id"]))
            c21_crawl.save_libs(libs)
    if rtl and new_keys:
        try:
            from . import c21_rtl
            res = c21_rtl.apply(new_keys)
            for r in rows.values():                       # apply() فهرست را خودش هم نوشت؛ ولی ما کپیِ خودمان را در پایان می‌نویسیم، پس نتیجه را این‌جا هم بنشان
                conv = r.get("conv") or {}
                if conv.get("key") in res:
                    conv["rtl"] = (res[conv["key"]] or {}).get("status", "skipped")
        except Exception as exc:                          # noqa: BLE001 - سنجشِ RTL اختیاری است؛ نبودنِ مرورگر کارِ تبدیل را خراب نمی‌کند
            st["errors"].append("rtl: %s" % str(exc)[:100])
    c21st.save(sorted(rows.values(), key=lambda x: x["id"]))
    st["remaining_libs"] = sum(1 for lid, l in libs.items() if l.get("github") and _candidates(rows, l, time.time()))
    st["converted_total"] = sum(1 for r in rows.values() if (r.get("conv") or {}).get("state") == "ok")
    st["finished_at"] = c21st._now()
    _save({**pipeline_state(), **st})
    return st


def _one(r: dict, dest: Path, idx: dict, lic: dict, lib: dict, commit: str, s, st: dict, runner, new_keys: list) -> None:
    cid = r["id"]
    parts = cid.split("/")
    rel0 = SRC.find_component(idx, parts[1])
    if not rel0:
        r["conv"] = {"state": "no-source", "ts": time.time()}
        st["no_source"] += 1
        return
    from . import c21_node
    demo = c21_node.load_demo(cid)                          # نمونه‌ای که گرهٔ GPU با مرورگر گرفته بود؛ وگرنه صفحهٔ عمومی را (مؤدبانه) می‌گیریم
    if not demo:
        try:
            res = s.get(c21st.BASE + "/@%s/components/%s" % (parts[0], parts[1]), max_bytes=900_000, accept="text/html,*/*;q=0.5")
            demo = SRC.parse_demo(res.text)
            if demo:
                c21_node.save_demo(cid, {**demo, "via": "server"})
        except safenet.FetchError as exc:
            if exc.code == "robots":
                r["conv"] = {"state": "failed", "error": "robots.txt", "ts": time.time()}
                st["failed"] += 1
                return
        except c21_crawl.CrawlBlocked:
            raise
    rel = SRC.find_component(idx, parts[1], demo.get("imports")) or rel0
    bundle = SRC.bundle_from_repo(dest, rel, parts[1], demo, license_info=lic, repo_url=lib["github"], commit=commit, idx=idx)
    meta = {"title": r.get("title", ""), "description": r.get("description", ""), "cats": r.get("cats", []), "license": r.get("license", ""), "author": r.get("author_name", ""),
            "library": r.get("library", ""), "url": r.get("url", "")}
    try:
        rec = CV.convert_bundle(cid, bundle, meta=meta, runner=runner)
    except CV.ConvertError as exc:
        r["conv"] = {"state": "failed", "error": str(exc)[:200], "ts": time.time()}
        st["failed"] += 1
        return
    except subprocess.TimeoutExpired:
        r["conv"] = {"state": "failed", "error": "timeout", "ts": time.time()}
        st["failed"] += 1
        return
    CV.save_record(rec)
    r["conv"] = {"state": "ok", "key": rec["key"], "ts": time.time(), "demo": bool(demo.get("code"))}
    r["src"] = "upstream"
    new_keys.append(rec["key"])
    st["converted"] += 1


def convert_from_api_code(cid: str, *, session=None, runner=subprocess.run) -> dict:
    """قطعه‌ای که کدش با کلیدِ مالک گرفته شده (c21st.fetch_code) ⇒ تبدیل. ⇒ رکورد؛ خطا ⇒ ConvertError."""
    row = c21st.by_id(cid)
    if row is None or not row.get("usable"):
        raise CV.ConvertError("قطعه در کاتالوگ نیست یا مجوزِ آزاد ندارد")
    meta_path = c21st.root() / "code" / (c21st.safe_name(cid) + ".json")
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CV.ConvertError("کدِ این قطعه هنوز گرفته نشده (کلیدِ API لازم است)") from exc
    s = session or c21_crawl.Session()
    parts = cid.split("/")
    demo = {}
    try:
        demo = SRC.parse_demo(s.get(c21st.BASE + "/@%s/components/%s" % (parts[0], parts[1]), max_bytes=900_000, accept="text/html,*/*;q=0.5").text)
    except safenet.FetchError:
        pass
    bundle = SRC.bundle_from_api(data.get("files") or [], demo, row=row)
    rec = CV.convert_bundle(cid, bundle, meta={"title": row.get("title", ""), "description": row.get("description", ""), "cats": row.get("cats", []), "license": row.get("license", ""),
                                                "author": row.get("author_name", ""), "library": row.get("library", ""), "url": row.get("url", "")}, runner=runner)
    CV.save_record(rec)
    rows = c21st.load()
    for r in rows:
        if r["id"] == cid:
            r["conv"] = {"state": "ok", "key": rec["key"], "ts": time.time()}
            r["src"] = "api"
    c21st.save(rows)
    return rec


def _checkout_commit(dest: Path, commit: str, *, runner=subprocess.run) -> bool:
    """مخزن را روی همان commit ِ ذخیره‌شده می‌برد (همان کدِ گذشته؛ فقط مبدّل عوض شده). نشد ⇒ False و روی HEAD می‌ماند."""
    import re
    if not re.fullmatch(r"[0-9a-f]{40}", commit or ""):
        return False
    r = _git(["fetch", "--depth", "1", "origin", commit], cwd=str(dest), runner=runner)
    if r.returncode != 0:
        return False
    return _git(["checkout", "--quiet", "FETCH_HEAD"], cwd=str(dest), runner=runner).returncode == 0


def reconvert(ids=None, *, runner=subprocess.run, clock=time.monotonic, max_seconds: float = 3300.0, rtl: bool = True, dry: bool = False, only_libs=None, rtl_batch: int = 30,
              log=None) -> dict:
    """قطعه‌های «از قبل تبدیل‌شده» را با مبدّلِ تازه دوباره می‌سازد (دورِ ۵: همهٔ پنل‌های بسته‌شو/تب‌ها در HTML می‌آیند، رولرِ رقم باز می‌شود، سیگنالِ «تعاملی؟» ثبت می‌شود).

    هر قطعه از **همان commit** ِ ذخیره‌شده ساخته می‌شود (نه HEAD)؛ اگر تبدیلِ تازه شکست خورد رکوردِ قدیمی دست‌نخورده می‌ماند. نتیجهٔ سنجشِ قبلی (rtl) تا سنجشِ تازه می‌ماند.
    ``dry`` ⇒ چیزی ذخیره نمی‌شود؛ رکوردهای تازه در ``st['records']`` می‌آیند (برای توسعه). ⇒ {converted, failed, kept_old, libs, errors, keys}."""
    say = log or (lambda *_a: None)
    started = clock()
    if c21st.is_running():
        return {"deferred": "crawl-running", "converted": 0, "failed": 0, "keys": []}
    rows = {r["id"]: r for r in c21st.load()}
    libs = c21_crawl.load_libs()
    index = CV.load_index()
    want = [cid for cid in (list(ids) if ids else list(index)) if cid in index]
    st = {"converted": 0, "failed": 0, "kept_old": 0, "libs": 0, "errors": [], "keys": [], "records": []}
    if not CV.toolchain_ready() and runner is subprocess.run:
        st["errors"].append("جعبه‌ابزار نصب نیست (/opt/nm-c21)")
        return st
    from . import c21_node
    new_keys: list[str] = []
    for lid, lib in libs.items():
        mine = [cid for cid in (lib.get("component_ids") or []) if cid in want]
        if not mine or not lib.get("github") or (only_libs and lid not in only_libs):
            continue
        if clock() - started > max_seconds:
            break
        dest = repos_dir() / ("re__" + lid.replace("/", "__"))
        try:
            commit = clone_repo(lib["github"], dest, runner=runner)
        except (CV.ConvertError, subprocess.TimeoutExpired) as exc:
            st["errors"].append("%s: %s" % (lid, str(exc)[:120]))
            st["kept_old"] += len(mine)
            continue
        try:
            first = CV.load_record(index[mine[0]]["key"]) or {}
            want_commit = ((first.get("source") or {}).get("commit") or "")
            if want_commit and want_commit != commit and _checkout_commit(dest, want_commit, runner=runner):
                commit = want_commit
            lic = SRC.detect_license(dest)
            if not SRC.is_permissive_spdx(lic["spdx"]):
                st["kept_old"] += len(mine)
                continue
            idx = SRC.index_repo(dest)
            st["libs"] += 1
            for cid in mine:
                if clock() - started > max_seconds:
                    st["kept_old"] += 1
                    continue
                old = CV.load_record(index[cid]["key"])
                row = rows.get(cid) or {}
                parts = cid.split("/")
                demo = c21_node.load_demo(cid) or {}
                rel = ((old or {}).get("source") or {}).get("path") or ""
                if not rel or not (dest / rel).is_file():
                    rel = SRC.find_component(idx, parts[1], demo.get("imports")) or ""
                if not old or not rel:
                    st["kept_old"] += 1
                    continue
                bundle = SRC.bundle_from_repo(dest, rel, parts[1], demo, license_info=lic, repo_url=lib["github"], commit=commit, idx=idx)
                meta = {"title": row.get("title") or old.get("title", ""), "description": row.get("description") or old.get("description", ""), "cats": row.get("cats") or old.get("cats", []),
                        "license": row.get("license") or old.get("license", ""), "author": row.get("author_name") or old.get("author", ""),
                        "library": row.get("library") or old.get("library", ""), "url": row.get("url") or old.get("url", "")}
                try:
                    rec = CV.convert_bundle(cid, bundle, meta=meta, runner=runner)
                except (CV.ConvertError, subprocess.TimeoutExpired) as exc:
                    st["failed"] += 1
                    st["kept_old"] += 1
                    st["errors"].append("%s: %s" % (cid, str(exc)[:100]))
                    continue
                rec["rtl"] = dict(old.get("rtl") or {"status": "unchecked"}, v=0)        # قدیمی تا سنجشِ تازه؛ v=0 ⇒ outdated ⇒ حتماً دوباره سنجیده می‌شود
                if old.get("contrast"):
                    rec["contrast"] = old["contrast"]
                if dry:
                    st["records"].append(rec)
                else:
                    CV.save_record(rec)
                new_keys.append(rec["key"])
                st["converted"] += 1
                say("converted", cid, rec["key"])
        finally:
            shutil.rmtree(dest, ignore_errors=True)
    st["keys"] = new_keys
    if rtl and new_keys and not dry:
        from . import c21_rtl
        for i in range(0, len(new_keys), rtl_batch):
            try:
                c21_rtl.apply(new_keys[i:i + rtl_batch])
                say("measured", min(len(new_keys), i + rtl_batch), len(new_keys))
            except Exception as exc:                                       # noqa: BLE001 - مرورگر اختیاری است؛ رکوردها با سنجشِ قدیمی می‌مانند
                st["errors"].append("rtl: %s" % str(exc)[:100])
                break
    return st


def sync_catalog_conv() -> int:
    """``catalog.json`` keeps a copy of each record's {rtl, kind} (``conv``); ``converted/index.json`` is the truth. Bring the copy in line (used after records were rebuilt
    elsewhere, e.g. copied in from a staging reconvert run, without a browser pass on this machine). ⇒ number of catalogue rows changed."""
    by_key = {e["key"]: e for e in CV.load_index().values() if e.get("key")}
    rows = c21st.load()
    n = 0
    for r in rows:
        conv = r.get("conv") or {}
        e = by_key.get(conv.get("key"))
        if not e:
            continue
        changed = False
        for field in ("rtl", "kind"):
            if e.get(field) and conv.get(field) != e[field]:
                conv[field] = e[field]
                changed = True
        n += 1 if changed else 0
    if n:
        c21st.save(rows)
    return n


def _save(st: dict) -> None:
    c21st._atomic(state_path(), json.dumps(st, ensure_ascii=False))
