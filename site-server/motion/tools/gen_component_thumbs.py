#!/usr/bin/env python3
"""Thumbnails of the component library: one real still of every component (its Persian sample, flat-vector style, 9:16) -> backend/apps/motion/thumbs/components/<id>.jpg.

    python motion/tools/gen_component_thumbs.py --bundle data/motion/bundle --browser <chrome-headless-shell> [--node node] [--scale 0.25]

Uses the same bundle and the same one-browser still renderer (tools/stills.mjs) as the style thumbnails, so a thumbnail IS what the component renders.
"""
import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_components():
    spec = importlib.util.spec_from_file_location("nm_components", ROOT / "backend" / "apps" / "motion" / "components.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.COMPONENTS


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--browser", default=None)
    ap.add_argument("--node", default="node")
    ap.add_argument("--scale", type=float, default=0.25)
    ap.add_argument("--style", default="flat-vector")
    ap.add_argument("--only", default="", help="comma separated ids")
    args = ap.parse_args()
    comps = load_components()
    ids = [i for i in (args.only.split(",") if args.only else comps) if i in comps]
    jobs = []
    for cid in ids:
        sc = dict(comps[cid]["sample"])
        dur = float(sc.get("duration", 4))
        jobs.append({"name": cid, "frame": int(min(dur * 0.62, dur - 0.6) * 30), "scale": args.scale,
                     "spec": {"version": 2, "style": args.style, "aspect": "9:16", "fps": 30, "lang": "fa", "digits": "auto", "platform": "",
                              "brand": {"use_brand_colors": True, "show_logo": False, "colors": ["#126F85", "#163F75"]}, "scenes": [sc]}})
    out = ROOT / "backend" / "apps" / "motion" / "thumbs" / "components"
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nm-comp-thumbs-") as tmp:
        jf = Path(tmp) / "jobs.json"
        jf.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
        cmd = [args.node, str(ROOT / "motion" / "tools" / "stills.mjs"), args.bundle, str(jf), str(out)]
        if args.browser:
            cmd += ["--browser", args.browser]
        proc = subprocess.run(cmd, cwd=str(ROOT / "motion"), text=True)
    missing = [i for i in ids if not (out / f"{i}.jpg").is_file()]
    print(json.dumps({"made": len(ids) - len(missing), "missing": missing}))
    return proc.returncode or (1 if missing else 0)


if __name__ == "__main__":
    sys.exit(main())
