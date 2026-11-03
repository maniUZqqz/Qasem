"""Background-removal mattes: the grey videos the processing node makes (white = the subject), kept per shop. §23.4

A matte belongs to one source video and one stretch of it (`s0`..`s1`, source seconds) and is sampled at a low frame rate
(the node runs a matting model per frame). A clip that points at one (`clip.matte = {"key": …}`) gets it merged into its
alpha at the source — `compose.py` — so later moves, scales, masks and blends all see the cut-out subject.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path

from django.conf import settings

KEY_RE = re.compile(r"^[0-9a-f]{12}$")
MAX_MATTES = 24


def matte_dir(store_id) -> Path:
    return Path(settings.MEDIA_ROOT) / "generated" / "editing" / "mattes" / f"store_{int(store_id)}"


def store_file(store_id, src, meta: dict) -> dict:
    """Keep the node's finished matte video → its row {key, ref, s0, s1, fps, node, bytes, created, url_path}."""
    src = Path(src)
    h = hashlib.sha1()
    with open(src, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    key = h.hexdigest()[:12]
    folder = matte_dir(store_id)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{key}.mp4"
    shutil.copyfile(src, dest)
    dest.chmod(0o644)
    row = {"key": key, "ref": str(meta.get("ref") or ""), "s0": float(meta.get("s0") or 0.0), "s1": float(meta.get("s1") or 0.0),
           "fps": float(meta.get("fps") or 0.0), "node": str(meta.get("node") or ""), "engine": str(meta.get("engine") or ""),
           "bytes": dest.stat().st_size, "created": int(time.time())}
    (folder / f"{key}.json").write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
    olds = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime)[:-MAX_MATTES]
    for old in olds:
        old.unlink(missing_ok=True)
        old.with_suffix(".mp4").unlink(missing_ok=True)
    return row


def get(store_id, key: str) -> dict | None:
    if not KEY_RE.match(str(key or "")):
        return None
    meta = matte_dir(store_id) / f"{key}.json"
    video = matte_dir(store_id) / f"{key}.mp4"
    if not (meta.is_file() and video.is_file()):
        return None
    try:
        return json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def path_of(store_id, key: str) -> Path | None:
    return matte_dir(store_id) / f"{key}.mp4" if get(store_id, key) else None


def listing(store_id) -> list[dict]:
    rows = []
    for meta in matte_dir(store_id).glob("*.json"):
        row = get(store_id, meta.stem)
        if row:
            rows.append(row)
    return sorted(rows, key=lambda r: -r.get("created", 0))


def remove(store_id, key: str) -> bool:
    if not get(store_id, key):
        return False
    for ext in (".mp4", ".json"):
        (matte_dir(store_id) / f"{key}{ext}").unlink(missing_ok=True)
    return True
