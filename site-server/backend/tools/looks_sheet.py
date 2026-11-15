#!/usr/bin/env python3
"""Sample sheets of the styles that came over from InstAI: every style in three aspects, through the REAL motion toolchain (tools/stills.mjs + the render bundle).

    venv/bin/python backend/tools/looks_sheet.py --bundle <data>/motion/bundle --out /root/stage/looks-sheet [--ids manga-ink,mosaic-tiles] [--browser <chrome-headless-shell>]

Per style: the title card in 9:16, 1:1 and 16:9, a list card (9:16) and a call-to-action card (1:1), all with the style's own palette (no brand colours) and
text taken from the public facts of the owner's product «چغر» (docs/chagher/brand-facts-fa.md: nothing invented, no price, no statistic).
Output: <out>/stills/*.jpg and <out>/sheet-NN.jpg (six styles per sheet, one row per style) + <out>/sheet.json. Plain Python + Pillow; needs node and the
bundle (manage.py motion_build --only catalog,shell). Heavy: run it under `flock -w 3600 /root/nm-heavy.lock`.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CATALOG_LOOKS = ROOT / "backend" / "apps" / "motion" / "catalog_looks.py"
FONT = ROOT / "backend" / "services" / "imaging" / "fonts"

#: the same text in every style: the real facts of Chagher (brand-facts-fa.md §1, §2, §4)
TITLE = {"type": "title", "duration": 3, "kicker": "معرفی", "title": "چغر", "subtitle": "دستیارِ هوش مصنوعیِ مربی‌ها؛ پیش‌نویسِ برنامهٔ ورزشی و غذایی در کمتر از یک دقیقه"}
LIST = {"type": "list", "duration": 4, "title": "چهار قدم", "items": ["ثبت‌نام در کمتر از یک دقیقه", "خریدِ توکن", "واردکردنِ اطلاعاتِ مجموعه", "تولیدِ برنامه"], "numbered": True}
CTA = {"type": "cta", "duration": 3, "title": "با چغر چغر تر شو", "button": "شروع رایگان", "note": "بدونِ کارتِ اعتباری"}
SHOTS = [("title", "9:16", TITLE, 84), ("title", "1:1", TITLE, 84), ("title", "16:9", TITLE, 84), ("list", "9:16", LIST, 108), ("cta", "1:1", CTA, 84)]      # late in the scene: every word has entered


def style_ids() -> list[str]:
    return re.findall(r'^\s+S\("([a-z0-9-]+)"', CATALOG_LOOKS.read_text(encoding="utf-8"), re.M)


def jobs_for(ids: list[str], scale: float) -> list[dict]:
    out = []
    for sid in ids:
        for kind, aspect, scene, frame in SHOTS:
            spec = {"style": sid, "aspect": aspect, "fps": 30, "lang": "fa", "brand": {"use_brand_colors": False}, "scenes": [dict(scene)]}
            out.append({"name": f"{sid}.{kind}.{aspect.replace(':', 'x')}", "spec": spec, "frame": frame, "scale": scale})
    return out


def montage(ids: list[str], stills: Path, out: Path, per_sheet: int = 6, row_h: int = 330) -> list[Path]:
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype(str(next(FONT.glob("*.ttf"))), 20)
    except (StopIteration, OSError):
        font = ImageFont.load_default()
    sheets = []
    for n, i in enumerate(range(0, len(ids), per_sheet), 1):
        rows = []
        for sid in ids[i:i + per_sheet]:
            tiles = []
            for kind, aspect, _scene, _f in SHOTS:
                p = stills / f"{sid}.{kind}.{aspect.replace(':', 'x')}.jpg"
                if p.is_file():
                    im = Image.open(p).convert("RGB")
                    tiles.append(im.resize((max(1, round(im.width * row_h / im.height)), row_h)))
            if not tiles:
                continue
            w = sum(t.width for t in tiles) + 8 * (len(tiles) - 1)
            row = Image.new("RGB", (w, row_h + 26), (24, 24, 28))
            x = 0
            for t in tiles:
                row.paste(t, (x, 26))
                x += t.width + 8
            ImageDraw.Draw(row).text((6, 2), sid, fill=(235, 235, 235), font=font)
            rows.append(row)
        if not rows:
            continue
        W = max(r.width for r in rows)
        sheet = Image.new("RGB", (W, sum(r.height + 6 for r in rows)), (12, 12, 14))
        y = 0
        for r in rows:
            sheet.paste(r, (0, y))
            y += r.height + 6
        p = out / f"sheet-{n:02d}.jpg"
        sheet.save(p, quality=84)
        sheets.append(p)
    return sheets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ids", default="")
    ap.add_argument("--browser", default="")
    ap.add_argument("--node", default="node")
    ap.add_argument("--scale", type=float, default=0.3)
    ap.add_argument("--montage-only", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    stills = out / "stills"
    stills.mkdir(parents=True, exist_ok=True)
    ids = [x for x in a.ids.split(",") if x] or style_ids()
    unknown = [x for x in ids if x not in style_ids()]
    if unknown:
        print("unknown style ids:", unknown, file=sys.stderr)
        return 2
    report = {"ok": 0, "fail": []}
    if not a.montage_only:
        jobs = out / "jobs.json"
        jobs.write_text(json.dumps(jobs_for(ids, a.scale), ensure_ascii=False), encoding="utf-8")
        cmd = [a.node, str(ROOT / "motion" / "tools" / "stills.mjs"), a.bundle, str(jobs), str(stills)] + (["--browser", a.browser] if a.browser else [])
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT / "motion"))
        for line in p.stdout.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("ev") == "still":
                report["ok"] += 1
            elif ev.get("ev") == "fail":
                report["fail"].append({"name": ev.get("name"), "message": ev.get("message")})
        if p.returncode not in (0, 1):
            print(p.stderr[-800:], file=sys.stderr)
    sheets = montage(ids, stills, out)
    report["sheets"] = [str(s) for s in sheets]
    (out / "sheet.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "fail": len(report["fail"]), "sheets": len(sheets)}))
    return 1 if report["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
