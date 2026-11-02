"""بستهٔ کدِ «سرورِ پردازش» که گره‌ها خودشان را با آن به‌روز می‌کنند (update.py / Update.bat روی کامپیوترِ گرافیکی).

    GET  /api/v1/compute/update/              فهرست: نسخه، شناسه، اندازه و sha256 ِ زیپ، هر فایل با اندازه و sha256
    GET  /api/v1/compute/update/package/      خودِ زیپ (پوشهٔ بالایی processing-server/)؛ ?zip=<sha256> همان ساختِ مشخص
    POST /api/v1/compute/nodes/<pk>/update/   (کارکنان) کارِ node.update: گره خودش را به‌روز و وقتِ بی‌کاری دوباره راه‌اندازی می‌کند

دسترسی: توکنِ گره (Authorization: Node <token>) یا کاربرِ کارمند. بسته از settings.NM_PROCESSING_DIR (پیش‌فرض
<repo>/processing) ساخته می‌شود، فقط وقتی فایل‌هایش عوض شده باشد؛ ساخته‌ها در <NM_DATA_DIR>/processing-update/
(سه تای آخر می‌مانند). مدل‌ها، venv ها، node.json و هر چیزِ ساخته‌شده روی گره هرگز در بسته نیست.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import threading
import time
import zipfile
from pathlib import Path

from django.conf import settings

PREFIX = "processing-server/"
#: پوشه‌هایی که هر جا باشند در بسته نیستند
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", "bin", "obj"}
#: پوشه‌های بالایی که روی گره ساخته می‌شوند (پوشهٔ داده)
SKIP_TOP = {"logs", "work", "venvs", "models", "vendor", "pip-cache", "downloads-cache", "data", "updates"}
SKIP_TOP_GLOB = ("python3*",)
#: ساخته‌های ویرایشگرها
SKIP_PATHS = ("tools/PersianAiKit/*/app", "tools/PersianAiKit/*/models", "tools/PersianAiKit/*/data",
              "tools/PersianAiKit/Video/tools/ffmpeg")
SKIP_FILES = ("*.pyc", "*.pyo", "*.bak", "*.bak-*", "*.part", "*.nm-new", "*.nm-tmp", "*.nm-old", "*.log", "*.tmp",
              "node.json", "services.json", "downloads-local.json", ".nm-version.json", "nm-data.txt",
              ".nm-moved-to-data.json", ".nm-kit-sync.json", "START-local.bat", "*.swp", ".DS_Store", "Thumbs.db")
KEEP_BUILDS = 3
_LOCK = threading.Lock()
_CACHE: dict = {"at": 0.0, "fp": None, "manifest": None}


def source_dir() -> Path:
    return Path(getattr(settings, "NM_PROCESSING_DIR", "") or Path(settings.BASE_DIR).parent / "processing")


def build_dir() -> Path:
    from .services import data_root
    d = data_root() / "processing-update"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _skipped(rel: str, is_dir: bool) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    if is_dir:
        if name in SKIP_DIRS:
            return True
        if len(parts) == 1 and (name in SKIP_TOP or any(fnmatch.fnmatch(name, g) for g in SKIP_TOP_GLOB)):
            return True
        return any(fnmatch.fnmatch(rel, p) for p in SKIP_PATHS)
    return any(fnmatch.fnmatch(name, p) for p in SKIP_FILES)


def source_files(root: Path | None = None) -> list[tuple[str, Path]]:
    """(مسیرِ نسبی با /، مسیرِ کامل) ِ هر فایلِ بسته، مرتب."""
    root = Path(root or source_dir())
    out = []
    for d, dirs, files in os.walk(root):
        rel_d = os.path.relpath(d, root).replace(os.sep, "/")
        rel_d = "" if rel_d == "." else rel_d
        dirs[:] = sorted(x for x in dirs if not _skipped((rel_d + "/" + x).lstrip("/"), True))
        for f in sorted(files):
            rel = (rel_d + "/" + f).lstrip("/")
            if not _skipped(rel, False) and not os.path.islink(os.path.join(d, f)):
                out.append((rel, Path(d) / f))
    return out


def fingerprint(files) -> str:
    h = hashlib.sha1()
    for rel, p in files:
        st = p.stat()
        h.update(("%s\0%d\0%d\n" % (rel, st.st_size, st.st_mtime_ns)).encode("utf-8"))
    return h.hexdigest()


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _version_of(path: Path, default=None):
    try:
        m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', path.read_text(encoding="utf-8", errors="replace"), re.M)
        return m.group(1) if m else default
    except OSError:
        return default


def _build(src: Path, files, fp: str) -> dict:
    rows = []
    for rel, p in files:
        rows.append({"path": rel, "size": p.stat().st_size, "sha256": _sha(p)})
    content_id = hashlib.sha256("".join("%s\0%d\0%s\n" % (r["path"], r["size"], r["sha256"]) for r in rows)
                                .encode("utf-8")).hexdigest()
    out = build_dir()
    tmp = out / ("build-%d-%d.zip" % (os.getpid(), threading.get_ident()))
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for (rel, p), r in zip(files, rows):
            info = zipfile.ZipInfo(PREFIX + rel, date_time=time.localtime(p.stat().st_mtime)[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, p.read_bytes())
    zsha = _sha(tmp)
    final = out / ("package-%s.zip" % zsha[:16])
    os.replace(tmp, final)
    agent = _version_of(src / "agent.py", "?")
    manifest = {"version": agent, "agent": agent, "downloader": _version_of(src / "download_models.py"),
                "updater": _version_of(src / "update.py"), "id": content_id, "zip_sha256": zsha,
                "zip_size": final.stat().st_size, "zip_name": final.name, "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "fingerprint": fp, "count": len(rows), "url": "/api/v1/compute/update/package/", "files": rows}
    tmpm = out / ("manifest-%d.json.tmp" % os.getpid())
    tmpm.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    os.replace(tmpm, out / "manifest.json")
    zips = sorted(out.glob("package-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in zips[KEEP_BUILDS:]:
        try:
            old.unlink()
        except OSError:
            pass
    return manifest


def current_manifest(max_age: float = 10.0) -> dict:
    """فهرستِ بستهٔ فعلی؛ اگر فایل‌های پوشهٔ پردازش عوض شده باشند بسته دوباره ساخته می‌شود."""
    now = time.time()
    if _CACHE["manifest"] is not None and now - _CACHE["at"] < max_age:
        return _CACHE["manifest"]
    src = source_dir()
    if not (src / "agent.py").is_file():
        raise FileNotFoundError("processing folder not found: %s" % src)
    files = source_files(src)
    fp = fingerprint(files)
    with _LOCK:
        m = _CACHE["manifest"]
        if m is None or m.get("fingerprint") != fp:
            try:
                disk = json.loads((build_dir() / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                disk = None
            if disk and disk.get("fingerprint") == fp and (build_dir() / disk.get("zip_name", "-")).is_file():
                m = disk
            else:
                m = _build(src, files, fp)
        _CACHE.update(at=now, fp=fp, manifest=m)
    return m


def package_path(zip_sha: str | None = None) -> Path | None:
    """زیپِ فعلی، یا ساختِ قبلی‌ای که فهرستش را گره پیش‌تر گرفته (تا ساختِ تازه وسطِ دانلود مزاحم نشود)."""
    m = current_manifest()
    if not zip_sha or zip_sha == m["zip_sha256"]:
        return build_dir() / m["zip_name"]
    if not re.fullmatch(r"[0-9a-f]{64}", zip_sha):
        return None
    p = build_dir() / ("package-%s.zip" % zip_sha[:16])
    return p if p.is_file() else None


def latest() -> dict:
    """{"version", "id"} ِ بستهٔ فعلی برای پنل؛ اگر پوشهٔ پردازش نباشد {}."""
    try:
        m = current_manifest(max_age=60.0)
        return {"version": m.get("version"), "id": m.get("id"), "size": m.get("zip_size"), "built": m.get("built")}
    except Exception:  # noqa: BLE001 — نبودِ بسته نباید فهرستِ سرورها را بخواباند
        return {}


# ───────────────────────────────────────────── ابزارِ به‌روزرسانیِ کوچک (Update.bat) و فایل‌های بزرگِ سایت

#: چیزی که Update.bat هر بار تازه از سایت می‌گیرد تا حتی پوشهٔ خیلی قدیمی (نسخهٔ ۱) با منطقِ تازه به‌روز شود
BOOT_FILES = ("update.py", "nm_data.py", "nm_fetch.py")
_BOOT: dict = {"fp": None, "info": None}


def bootstrap() -> dict:
    """زیپِ کوچکِ ابزارِ به‌روزرسانی: {"path", "sha256", "size", "version", "files"}؛ فقط وقتی فایل‌ها عوض شوند دوباره ساخته
    می‌شود (زمانِ فایل‌های داخلش ثابت است تا sha256 فقط با محتوا عوض شود)."""
    src = source_dir()
    files = [(n, src / n) for n in BOOT_FILES]
    missing = [n for n, p in files if not p.is_file()]
    if missing:
        raise FileNotFoundError("update tool files missing in %s: %s" % (src, ", ".join(missing)))
    fp = tuple((n, p.stat().st_size, p.stat().st_mtime_ns) for n, p in files)
    with _LOCK:
        if _BOOT["info"] is not None and _BOOT["fp"] == fp and Path(_BOOT["info"]["path"]).is_file():
            return _BOOT["info"]
        out = build_dir()
        tmp = out / ("bootstrap-%d-%d.zip.tmp" % (os.getpid(), threading.get_ident()))
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for n, p in files:
                info = zipfile.ZipInfo(n, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                z.writestr(info, p.read_bytes())
        sha = _sha(tmp)
        final = out / ("bootstrap-%s.zip" % sha[:16])
        os.replace(tmp, final)
        for old in sorted(out.glob("bootstrap-*.zip"), key=lambda q: q.stat().st_mtime, reverse=True)[KEEP_BUILDS:]:
            try:
                old.unlink()
            except OSError:
                pass
        info = {"path": str(final), "sha256": sha, "size": final.stat().st_size, "files": list(BOOT_FILES),
                "version": _version_of(src / "update.py"), "fetcher": _version_of(src / "nm_fetch.py")}
        _BOOT.update(fp=fp, info=info)
        return info


def update_bat_bytes() -> bytes:
    """متنِ Update.bat بسته (همان فایلِ processing/Update.bat) همیشه با CRLF؛ cmd.exe با LF تنها گاهی خط‌ها را خراب می‌خواند."""
    p = source_dir() / "Update.bat"
    if not p.is_file():
        raise FileNotFoundError("Update.bat missing in %s" % source_dir())
    data = p.read_bytes()
    return data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def downloads_dir() -> Path:
    """پوشهٔ فایل‌های بزرگی که nginx مستقیم می‌دهد: {site}/3d/files/downloads/ (Blender، ویرایشگرها، مدل‌ها)."""
    from .services import data_root
    return data_root() / "up3d" / "downloads"


_SHA_LOCK = threading.Lock()


def download_info(name: str) -> dict | None:
    """{"name", "size", "sha256"} ِ یک فایلِ پوشهٔ downloads (پیوندِ نمادین هم دنبال می‌شود)؛ sha256 یک بار حساب و با
    (اندازه، زمان) کش می‌شود تا گره‌ها بتوانند دانلودِ ۴۰۰ مگابایتی را بعد از پایان بسنجند."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", name or ""):
        return None
    path = downloads_dir() / name
    try:
        real = path.resolve(strict=True)
        st = real.stat()
    except OSError:
        return None
    if not real.is_file():
        return None
    cache_file = build_dir() / "downloads-sha.json"
    with _SHA_LOCK:
        try:
            cache = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
        row = cache.get(name) or {}
        if row.get("size") != st.st_size or row.get("mtime_ns") != st.st_mtime_ns or not row.get("sha256"):
            row = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": _sha(real)}
            cache[name] = row
            tmp = cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(cache), encoding="utf-8")
            os.replace(tmp, cache_file)
    return {"name": name, "size": st.st_size, "sha256": row["sha256"]}


def list_downloads() -> list[dict]:
    """نامِ فایل‌های بزرگ + اندازه (sha256 فقط اگر پیش‌تر حساب شده)؛ کار را سبک نگه می‌دارد."""
    out = []
    d = downloads_dir()
    try:
        names = sorted(p.name for p in d.iterdir())
    except OSError:
        return out
    for n in names:
        try:
            st = (d / n).resolve(strict=True).stat()
        except OSError:
            continue
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", n) and (d / n).resolve().is_file():
            out.append({"name": n, "size": st.st_size})
    return out


def _vtuple(v) -> tuple:
    try:
        return tuple(int(x) for x in str(v or "0").split(".")[:3])
    except ValueError:
        return (0,)


def update_state(caps: dict, last: dict | None = None) -> dict:
    """چه نسخه‌ای روی گره است و آیا بستهٔ تازه‌تری منتظر است."""
    last = latest() if last is None else last
    caps = caps or {}
    code = caps.get("code") if isinstance(caps.get("code"), dict) else {}
    agent = caps.get("agent")
    waiting = False
    if last.get("id") and agent:
        if code.get("id"):
            waiting = not str(last["id"]).startswith(str(code["id"]))
        else:
            waiting = _vtuple(agent) < _vtuple(last.get("version"))
    return {"agent_latest": last.get("version"), "update_waiting": waiting,
            "can_remote_update": _vtuple(agent) >= (2, 0)}
