"""Colour LUTs (.cube): validate, store per shop, blend with the original, hand to ffmpeg's `lut3d`. §23.4

A LUT is a colour recipe a colourist hands over as one `.cube` file. The panel imports it; a clip's picture then gets
`lut3d=file=…` after the Lumetri block (the browser mirrors it with a trilinear lookup, `lut.ts`). «Amount» less than
1 is done by writing a *blended* cube — `identity × (1 - amount) + lut × amount` — once, so the filter chain stays one
plain filter (and a render on another computer needs only that file).

Only 3D LUTs (`LUT_3D_SIZE`, up to 65) are accepted; a 1D LUT, a truncated table or a file that is not a cube are refused
with a sentence, never stored.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from django.conf import settings

from .errors import TimelineError

MAX_BYTES = 12 * 1024 * 1024
MAX_SIZE = 65
MAX_LUTS = 40
KEY_RE = re.compile(r"^[0-9a-f]{12}$")


def lut_dir(store_id) -> Path:
    return Path(settings.MEDIA_ROOT) / "generated" / "editing" / "luts" / f"store_{int(store_id)}"


def derived_dir() -> Path:
    return Path(settings.MEDIA_ROOT) / "generated" / "editing" / "luts" / "derived"


def parse(text: str) -> dict:
    """`.cube` text → {"size", "title", "dmin", "dmax", "table": float32 ndarray (size³, 3), red index fastest}."""
    import numpy as np

    size = 0
    title = ""
    dmin, dmax = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]
    rows: list[list[float]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head = line.split(None, 1)[0].upper()
        if head == "TITLE":
            title = line.split(None, 1)[1].strip().strip('"')[:80] if " " in line else ""
        elif head == "LUT_3D_SIZE":
            try:
                size = int(line.split()[1])
            except (IndexError, ValueError):
                raise TimelineError("LUT_3D_SIZE درست نیست.") from None
        elif head == "LUT_1D_SIZE":
            raise TimelineError("فقط LUT سه‌بعدی (LUT_3D_SIZE) پشتیبانی می‌شود؛ این فایل یک‌بعدی است.")
        elif head in ("DOMAIN_MIN", "DOMAIN_MAX"):
            try:
                vals = [float(x) for x in line.split()[1:4]]
            except ValueError:
                raise TimelineError(f"{head} درست نیست.") from None
            if len(vals) != 3:
                raise TimelineError(f"{head} باید سه عدد داشته باشد.")
            (dmin if head == "DOMAIN_MIN" else dmax)[:] = vals
        elif head[0].isalpha():
            continue                          # LUT_IN_VIDEO_RANGE and friends: ignored
        else:
            parts = line.split()
            if len(parts) < 3:
                raise TimelineError("ردیفِ نادرست در جدولِ LUT.")
            try:
                rows.append([float(parts[0]), float(parts[1]), float(parts[2])])
            except ValueError:
                raise TimelineError("ردیفِ نادرست در جدولِ LUT.") from None
    if size < 2 or size > MAX_SIZE:
        raise TimelineError(f"اندازهٔ LUT باید بین ۲ و {MAX_SIZE} باشد (LUT_3D_SIZE).")
    if len(rows) != size ** 3:
        raise TimelineError(f"جدولِ LUT {len(rows)} ردیف دارد ولی {size}³ = {size ** 3} ردیف لازم است.")
    table = np.asarray(rows, dtype=np.float32)
    if not np.isfinite(table).all():
        raise TimelineError("جدولِ LUT عددِ نامعتبر دارد.")
    if any(b <= a for a, b in zip(dmin, dmax)):
        raise TimelineError("DOMAIN_MIN/MAX نادرست است.")
    return {"size": size, "title": title, "dmin": dmin, "dmax": dmax, "table": table}


def _identity(size: int):
    import numpy as np

    g = np.linspace(0.0, 1.0, size, dtype=np.float32)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")          # red varies fastest in a .cube
    return np.stack([r.ravel(), gg.ravel(), b.ravel()], axis=1)


def write_cube(path, size: int, table, *, title: str = "", dmin=None, dmax=None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'TITLE "{title or "nm"}"', f"LUT_3D_SIZE {size}"]
    if dmin and any(abs(v) > 1e-9 for v in dmin):
        lines.append("DOMAIN_MIN " + " ".join(f"{v:.6f}" for v in dmin))
    if dmax and any(abs(v - 1) > 1e-9 for v in dmax):
        lines.append("DOMAIN_MAX " + " ".join(f"{v:.6f}" for v in dmax))
    body = "\n".join(f"{r:.6f} {g:.6f} {b:.6f}" for r, g, b in table.tolist())
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n" + body + "\n", encoding="ascii")
    tmp.replace(path)
    return path


def store(store_id, data: bytes, title: str = "") -> dict:
    """Validate and keep an uploaded .cube for a shop → its row (key, title, size, bytes)."""
    if len(data) > MAX_BYTES:
        raise TimelineError("فایلِ LUT بزرگ‌تر از ۱۲ مگابایت است.")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        try:
            text = data.decode("latin-1")
        except UnicodeDecodeError:
            raise TimelineError("فایلِ LUT متنِ .cube نیست.") from None
    meta = parse(text)
    folder = lut_dir(store_id)
    if len(list(folder.glob("*.json"))) >= MAX_LUTS and not (folder / f"{hashlib.sha1(data).hexdigest()[:12]}.json").is_file():
        raise TimelineError(f"حداکثر {MAX_LUTS} LUT؛ چندتا را پاک کنید.")
    key = hashlib.sha1(data).hexdigest()[:12]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{key}.cube").write_bytes(data)
    row = {"key": key, "title": (title or meta["title"] or f"LUT {key[:4]}")[:60], "size": meta["size"], "bytes": len(data),
           "created": int(time.time())}
    (folder / f"{key}.json").write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
    return row


def listing(store_id) -> list[dict]:
    rows = []
    for meta in sorted(lut_dir(store_id).glob("*.json")):
        try:
            row = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (meta.with_suffix(".cube")).is_file():
            rows.append(row)
    return sorted(rows, key=lambda r: -r.get("created", 0))


def path_of(store_id, key: str) -> Path | None:
    if not KEY_RE.match(str(key or "")):
        return None
    p = lut_dir(store_id) / f"{key}.cube"
    return p if p.is_file() else None


def remove(store_id, key: str) -> bool:
    if not KEY_RE.match(str(key or "")):
        return False
    gone = False
    for ext in (".cube", ".json"):
        p = lut_dir(store_id) / f"{key}{ext}"
        if p.is_file():
            p.unlink()
            gone = True
    return gone


def blended(path, amount: float) -> Path:
    """The cube to hand to ffmpeg for this amount: the file itself at 1, else a blended copy (made once)."""
    amount = max(0.0, min(1.0, float(amount)))
    path = Path(path)
    if amount >= 0.995:
        return path
    key = hashlib.sha1(f"{path.name}|{path.stat().st_size}|{round(amount, 3)}".encode()).hexdigest()[:16]
    out = derived_dir() / f"{key}.cube"
    if out.is_file():
        out.touch()
        return out
    meta = parse(path.read_text(encoding="utf-8", errors="replace"))
    table = _identity(meta["size"]) * (1 - amount) + meta["table"] * amount
    write_cube(out, meta["size"], table, title=meta["title"], dmin=meta["dmin"], dmax=meta["dmax"])
    olds = sorted(derived_dir().glob("*.cube"), key=lambda p: p.stat().st_mtime)[:-80]
    for old in olds:
        try:
            old.unlink()
        except OSError:
            pass
    return out
