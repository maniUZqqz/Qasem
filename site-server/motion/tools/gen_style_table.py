#!/usr/bin/env python3
"""Prints (or, with --update <file.md>, rewrites between <!-- styles:begin --> and <!-- styles:end -->) the Markdown table of every style.

    python motion/tools/gen_style_table.py                       -> table on stdout
    python motion/tools/gen_style_table.py --update docs/motion/README-fa.md

Reads backend/apps/motion/catalog.py directly (plain Python, no Django needed)."""
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_catalog():
    spec = importlib.util.spec_from_file_location("nm_motion_catalog", ROOT / "backend" / "apps" / "motion" / "catalog.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def table(cat) -> str:
    rows = ["| # | سبک | شناسه | گروه | الهام | ورود | فنر | پله | گذار | متن | پس‌زمینه |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, s in enumerate(cat.STYLES, 1):
        m = s["motion"]
        sp = "، ".join(str(x) for x in m["spring"])
        rows.append("| %d | %s | `%s` | %s | %s | `%s` | `%s` | %s | `%s` | `%s` | `%s` |" % (
            i, s["name_fa"], s["id"], cat.GROUPS[s["group"]], s["inspired"] or "", m["enter"], sp, m.get("stepFps") or "",
            s["trans"]["kind"], s["text"]["fx"], s["bg"]["kind"]))
    return "\n".join(rows)


def main(argv) -> int:
    cat = load_catalog()
    out = table(cat)
    if len(argv) >= 3 and argv[1] == "--update":
        p = Path(argv[2])
        src = p.read_text(encoding="utf-8")
        new, n = re.subn(r"(<!-- styles:begin -->\n).*?(\n<!-- styles:end -->)", lambda m: m.group(1) + out + m.group(2), src, flags=re.S)
        if n != 1:
            print("markers not found", file=sys.stderr)
            return 1
        p.write_text(new, encoding="utf-8", newline="\n")
        print("updated %s (%d styles)" % (p, len(cat.STYLES)))
        return 0
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
