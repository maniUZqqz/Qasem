"""«جمع‌کردنِ فایل‌های پروژه» (Collect / Consolidate): every original file a project uses, plus the project itself, in ONE zip that can be kept or moved.

The media live on the shop's server and are referenced by `ref`; this makes the archive on demand. Inside: `project.json` (the editor's project, untouched),
`manifest.json` (ref → file name in the zip, title, size) and `media/<n>_<name>`. Refs that are not the shop's own are skipped with a note, never read.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

#: refs that are not files of the bin
NO_FILE = ("shape", "adjust")
MAX_BYTES = 3 * 1024 ** 3


def refs_of(data: dict) -> list[str]:
    """Every distinct media ref of a project (clips of every track and of nested sequences, LUTs and mattes), in first-seen order."""
    found: list[str] = []

    def add(ref) -> None:
        ref = str(ref or "")
        if ref and ref not in NO_FILE and not ref.startswith("seq:") and ref not in found:
            found.append(ref)

    def walk(tracks) -> None:
        for t in tracks or []:
            for c in (t or {}).get("clips") or []:
                if not isinstance(c, dict):
                    continue
                add(c.get("ref"))
                lut = c.get("lut")
                if isinstance(lut, dict) and lut.get("key"):
                    add("lut:" + str(lut["key"]))
                mt = c.get("matte")
                if isinstance(mt, dict) and mt.get("key"):
                    add("matte:" + str(mt["key"]))

    walk(data.get("tracks"))
    for seq in (data.get("sequences") or {}).values():
        if isinstance(seq, dict):
            walk(seq.get("tracks"))
    return found


def _safe(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE).strip("._") or "file"


def build(data: dict, store, out: Path, *, progress=None, cancel=None) -> dict:
    """Write the zip to `out`. → {"files", "bytes", "skipped": [persian notes]}. Raises ValueError (Persian) when it would be too big."""
    from apps.content import editor_project

    resolved: list[tuple[str, Path, str]] = []
    skipped: list[str] = []
    total = 0
    for ref in refs_of(data):
        try:
            found = editor_project.locate(store, ref)
            path = found.get("path") or editor_project._field_path(found.get("field"))
        except Exception as exc:  # noqa: BLE001 — a missing or foreign ref is a note, not a crash
            skipped.append(f"«{ref}»: {exc}")
            continue
        if path is None or not Path(path).is_file():
            skipped.append(f"«{ref}»: فایل روی سرور پیدا نشد.")
            continue
        path = Path(path)
        resolved.append((ref, path, str(found.get("title") or path.stem)))
        total += path.stat().st_size
    if total > MAX_BYTES:
        raise ValueError(f"فایل‌های پروژه {total / 1024 ** 3:.1f} گیگابایت است؛ بیش از سقفِ {MAX_BYTES // 1024 ** 3} گیگابایت برای یک بسته.")
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest = []
    done = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        zf.writestr("project.json", json.dumps(data, ensure_ascii=False, indent=1))
        for i, (ref, path, title) in enumerate(resolved, start=1):
            if cancel is not None and cancel():
                raise RuntimeError("لغو شد.")
            arc = f"media/{i:02d}_{_safe(path.name)}"
            zf.write(path, arc)
            manifest.append({"ref": ref, "file": arc, "title": title, "bytes": path.stat().st_size})
            done += path.stat().st_size
            if progress is not None and total:
                progress(done / total)
        zf.writestr("manifest.json", json.dumps({"files": manifest, "skipped": skipped}, ensure_ascii=False, indent=1))
    return {"files": len(manifest), "bytes": out.stat().st_size, "skipped": skipped}
