"""Builds backend/apps/photoedit/kit_catalog.json from the PersianAiKit.Photo C# sources (ToolCatalog.cs + Presets.cs).

Run again whenever the kit gains a slider or a preset:  python3 gen_kit_catalog.py <upmarket root>
"""
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "/var/www/NM/upmarket")
src = root / "processing/tools/PersianAiKit/Photo/src/PersianAiKit.Photo"
cat = (src / "ToolCatalog.cs").read_text(encoding="utf-8")
pre = (src / "Presets.cs").read_text(encoding="utf-8")

groups = [{"key": k, "title": t, "help": h}
          for k, t, h in re.findall(r'new ToolGroup\("([^"]+)", "([^"]+)", "([^"]*)"\)', cat)]

num = r"(-?[0-9.]+)"
pat = re.compile(r'new\("([A-Za-z]+)", "([a-z]+)", "([^"]+)", "([^"]*)", ' + num + ", " + num + ", " + num + ", " + num
                 + r'(?:, "([^"]*)")?(?:, "([^"]*)")?\)')
params = []
for m in pat.finditer(cat):
    key, group, title, help_, lo, hi, de, st, unit, ps = m.groups()
    params.append({"key": key, "group": group, "title": title, "help": help_, "min": float(lo), "max": float(hi),
                   "default": float(de), "step": float(st), "unit": unit or "", "photoshop": ps or ""})

bands = re.findall(r'\("([a-z]+)", "([^"]+)", ([0-9]+)\)', cat.split("Bands =", 1)[1].split("};", 1)[0])
for key, title, _hue in bands:
    params.append({"key": key + "Hue", "group": "hsl", "title": "فامِ " + title,
                   "help": f"چرخاندنِ رنگِ {title} به سمتِ رنگ‌های همسایه.", "min": -100.0, "max": 100.0,
                   "default": 0.0, "step": 1.0, "unit": "", "photoshop": "HSL (Hue)"})
    params.append({"key": key + "Sat", "group": "hsl", "title": "اشباعِ " + title, "help": f"شدتِ رنگِ {title}.",
                   "min": -100.0, "max": 100.0, "default": 0.0, "step": 1.0, "unit": "", "photoshop": "HSL (Saturation)"})
    params.append({"key": key + "Lum", "group": "hsl", "title": "روشنیِ " + title,
                   "help": f"روشن یا تیره کردنِ {title}.", "min": -100.0, "max": 100.0, "default": 0.0, "step": 1.0,
                   "unit": "", "photoshop": "HSL (Luminance)"})

presets = []
for m in re.finditer(r'P\("([A-Za-z]+)", "([^"]+)", "([^"]*)", "([a-z]+)",\s*"""(.*?)"""\)', pre, re.S):
    key, title, help_, kind, recipe = m.groups()
    presets.append({"key": key, "title": title, "help": help_, "kind": kind, "recipe": json.loads(recipe)})

assert len(params) >= 40, len(params)
assert len(presets) >= 10, len(presets)
out = {"source": "processing/tools/PersianAiKit/Photo (ToolCatalog.cs, Presets.cs)", "groups": groups,
       "params": params, "presets": presets}
dst = root / "backend/apps/photoedit/kit_catalog.json"
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("groups", len(groups), "params", len(params), "presets", len(presets), "->", dst)
