#!/usr/bin/env python3
"""Generator of the 30 motion styles that came over from InstAI's art-style library (docs/motion/looks-from-instai-fa.md).

SOURCE: ported from InstAI:instai/styles/builtin_styles.py + remotion/src/kit/{Look.tsx,motion.ts,theme.ts} @ 2f8aa90 (v0.14.0), adapted for NMarketing
store ads. NMarketing never imports InstAI: the 116 InstAI styles are a frozen snapshot (backend/tools/instai_looks/snapshot.json).

    python backend/tools/gen_instai_looks.py                       writes backend/apps/motion/catalog_looks.py  (the 30 S(...) rows; reproducible)
    python backend/tools/gen_instai_looks.py --check               exit 1 when the committed file differs from what the generator makes
    python backend/tools/gen_instai_looks.py --doc                 the diff table against NM's 66 base ids (Markdown) on stdout
    python backend/tools/gen_instai_looks.py --update-doc <file>   rewrites the tables between <!-- looks:begin --> / <!-- motion:begin --> / <!-- springs:begin --> markers
    python backend/tools/gen_instai_looks.py --update-qa <file> <dir>...   writes the measured QA table (<!-- qa:begin -->) from the looks-qa.json files of the e2e runs

What is automatic: the 8-colour palette (mapping.derive_palette: ink >= 7:1, accent >= 4.5:1 on the background and >= 3.9:1 on bg2, decoration >= 1.9:1) and the motion
personality of the InstAI animation approach (mapping.motion_for). What is hand-made: the NM recipe (instai_looks/recipes.py). The diff against
NM's own ids is computed from catalog.py (the S("id", ...) rows written there), not typed.

Plain Python, no Django needed. After a change run: manage.py motion_build --only catalog (regenerates styles.generated.json), then the style table
(python motion/tools/gen_style_table.py --update docs/motion/README-fa.md) and this script's --update-doc.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LOOKS = HERE / "instai_looks"
CATALOG_PY = ROOT / "backend" / "apps" / "motion" / "catalog.py"
OUT_PY = ROOT / "backend" / "apps" / "motion" / "catalog_looks.py"
SNAPSHOT = LOOKS / "snapshot.json"
SOURCE_COMMIT = "2f8aa90 (v0.14.0)"


def _load(name: str):
    spec = importlib.util.spec_from_file_location("nm_instai_looks_" + name, LOOKS / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mapping = _load("mapping")
recipes = _load("recipes")


def snapshot() -> dict:
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    return {s["key"]: s for s in data["styles"]}


def base_ids() -> list[str]:
    """NM's own styles: the S("id", ...) rows written in catalog.py (the generated rows are added to STYLES afterwards and never appear there)"""
    src = CATALOG_PY.read_text(encoding="utf-8")
    return re.findall(r'^\s+S\("([a-z0-9-]+)"', src, re.M)


def group_labels() -> dict[str, str]:
    """GROUPS of catalog.py (key -> Persian label), read from the source like the base ids"""
    src = CATALOG_PY.read_text(encoding="utf-8")
    m = re.search(r"^GROUPS = \{(.*?)^\}", src, re.M | re.S)
    return dict(re.findall(r'"([a-z]+)":\s*"([^"]+)"', m.group(1))) if m else {}


def known_groups() -> set[str]:
    return set(group_labels())


# ───────────────────────────────────────────────────────────────────────── the conversion
def build(snap: dict | None = None) -> list[dict]:
    snap = snap or snapshot()
    out = []
    for r in recipes.RECIPES:
        src = snap[r["src"]]
        pal = mapping.derive_palette(src["palette"], r.get("pal"))
        motion = mapping.motion_for(src["animation"], src["fps_feel"])
        motion.update(r.get("motion") or {})
        out.append({**r, "palette": pal, "motion": motion, "instai": src})
    return out


def classify(snap: dict | None = None) -> dict[str, tuple[str, str, str]]:
    """every InstAI key -> (status, NM id or "", note); raises when a key is missing, doubled or points at an id that does not exist"""
    snap = snap or snapshot()
    base = set(base_ids())
    ported = {r["src"]: r["id"] for r in recipes.RECIPES}
    ported_ids = set(ported.values())
    res: dict[str, tuple[str, str, str]] = {}

    def put(key, status, to, note):
        if key in res:
            raise ValueError(f"{key}: classified twice ({res[key][0]} and {status})")
        if key not in snap:
            raise ValueError(f"{key}: not an InstAI style of the snapshot")
        res[key] = (status, to, note)

    for k, i in ported.items():
        put(k, "ported", i, "")
    for k, i in mapping.HAVE.items():
        if i not in base:
            raise ValueError(f"HAVE {k} -> {i}: not one of NM's {len(base)} base styles")
        put(k, "have", i, "")
    for k, (i, note) in mapping.NEAR.items():
        if i not in base | ported_ids:
            raise ValueError(f"NEAR {k} -> {i}: neither a base nor a ported style")
        put(k, "near", i, note)
    for k, note in mapping.SKIP.items():
        put(k, "skip", "", note)
    missing = sorted(set(snap) - set(res))
    if missing:
        raise ValueError(f"InstAI styles nobody classified: {missing}")
    return res


# ───────────────────────────────────────────────────────────────────────── the Python source of the generated module
def lit(v, indent: int = 0) -> str:
    """a Python literal (json.dumps would print true/null)"""
    if isinstance(v, dict):
        return "{" + ", ".join(f"{lit(k)}: {lit(x)}" for k, x in v.items()) + "}"
    if isinstance(v, tuple):
        return "(" + ", ".join(lit(x) for x in v) + ("," if len(v) == 1 else "") + ")"
    if isinstance(v, list):
        return "[" + ", ".join(lit(x) for x in v) + "]"
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    return repr(v)


def _motion_literal(m: dict) -> str:
    d = {"enter": m["enter"], "spring": tuple(m["spring"]), "stagger": m["stagger"]}
    if m.get("stepFps"):
        d["stepFps"] = m["stepFps"]
    if m.get("wobble"):
        d["wobble"] = m["wobble"]
    if m.get("cam"):
        d["cam"] = m["cam"]
    return lit(d)


def row_source(r: dict) -> str:
    p = r["palette"]
    pal = " ".join(p[k] for k in ("bg", "bg2", "ink", "paper", "accent", "accent2", "accent3", "muted"))
    src = r["instai"]
    lines = [f'        # {r["src"]} ({src["animation"]}, {src["fps_feel"]} poses/s, motif "{src["motif"]}")',
             f'        S({lit(r["id"])}, {lit(r["fa"])}, {lit(r["en"])}, {lit(r["group"])},',
             f'          {lit(pal)},',
             f'          {lit(r["font"])},',
             f'          {lit(r["bg"])},',
             f'          {lit(r["text"])},',
             f'          shape={lit(r["shape"])},']
    if r.get("decor"):
        lines.append(f'          decor={lit(r["decor"])},')
    if r.get("tex"):
        lines.append(f'          tex={lit(r["tex"])},')
    lines.append(f'          motion={_motion_literal(r["motion"])}, trans={lit(tuple(r["trans"]))},')
    if r.get("bg2"):
        lines.append(f'          bg2={lit(r["bg2"])},')
    if r.get("fx"):
        lines.append(f'          fx={lit(r["fx"])},')
    lines.append(f'          about={lit(r["about"])},')
    lines.append(f'          fits={lit(r["fits"])},')
    lines.append(f'          tags={lit(tuple(r["tags"]))}),')
    return "\n".join(lines)


def module_source(rows: list[dict] | None = None) -> str:
    rows = rows or build()
    origin = {r["id"]: r["src"] for r in rows}
    head = f'''"""سی سبکِ تازه از کتابخانهٔ هنریِ InstAI — فایلِ تولیدشده؛ دستی ویرایش نکنید.

SOURCE: ported from InstAI:instai/styles/builtin_styles.py + remotion/src/kit/{{Look.tsx,motion.ts,theme.ts}} @ {SOURCE_COMMIT}, adapted for NMarketing store ads
(the diff against NM's own 66 ids, the rules and the licence notes: docs/motion/looks-from-instai-fa.md).

تولید: `python backend/tools/gen_instai_looks.py` (پالتِ ۸رنگ و شخصیتِ حرکت از خودِ سبکِ InstAI می‌آید؛ دستورِ ساختِ هر ردیف در
backend/tools/instai_looks/recipes.py). برای تغییر، دستورِ ساخت را عوض کنید و دوباره بسازید؛ آزمونِ `tests_looks` می‌سنجد که این فایل همان خروجی است.
هیچ نامِ استودیو، برند یا هنرمندی در شناسه، نام، توضیح یا برچسب نیست.
"""
from __future__ import annotations

#: شناسهٔ سبکِ NM -> کلیدِ سبکِ InstAI که از آن آمده
ORIGIN = {{
'''
    head += "".join(f"    {lit(k)}: {lit(v)},\n" for k, v in origin.items())
    head += "}\nIDS = tuple(ORIGIN)\n\n\ndef rows(S) -> list[dict]:\n    \"\"\"ردیف‌هایِ سبک‌ها؛ `S` همان سازندهٔ catalog.py است.\"\"\"\n    return [\n"
    body = "\n\n".join(row_source(r) for r in rows)
    return head + body + "\n    ]\n"


# ───────────────────────────────────────────────────────────────────────── the diff table (docs)
STATUS_FA = {"have": "NM دارد", "near": "نزدیک دارد", "ported": "تازه افزوده شد", "skip": "نمی‌شود"}


def doc_table(snap: dict | None = None) -> str:
    snap = snap or snapshot()
    cls = classify(snap)
    rows = build(snap)
    by_src = {r["src"]: r for r in rows}
    labels = group_labels()
    out = ["| # | سبکِ InstAI | نام | وضعیت | سبکِ NM | یادداشت |", "|---|---|---|---|---|---|"]
    for i, (k, s) in enumerate(snap.items(), 1):
        status, to, note = cls[k]
        nm = f"`{to}`" if to else ""
        if status == "ported":
            note = f'گروهِ «{labels.get(by_src[k]["group"], by_src[k]["group"])}»؛ ورودِ {by_src[k]["motion"]["enter"]}' + (f'، {by_src[k]["motion"]["stepFps"]} فریم‌بر‌ثانیه' if by_src[k]["motion"].get("stepFps") else "")
        out.append(f"| {i} | `{k}` | {s['name_fa']} | {STATUS_FA[status]} | {nm} | {note} |")
    n = {st: sum(1 for v in cls.values() if v[0] == st) for st in STATUS_FA}
    out.append("")
    out.append(f"جمع: {len(snap)} سبکِ InstAI؛ {n['have']} را NM همان‌طور دارد، {n['near']} را سبکی نزدیک پوشش می‌دهد، {n['ported']} سبکِ تازه افزوده شد و {n['skip']} مورد با کد کشیدنی نیست.")
    return "\n".join(out)


def motion_table(snap: dict | None = None) -> str:
    """the real motion values of the 30 rows (what the engine reads), next to the InstAI approach they came from"""
    out = ["| # | سبک | شناسه | گروه | حرکتِ InstAI | ورود | فنر | تأخیر | پله (فریم‌بر‌ثانیه) | گذار | پس‌زمینه | متن |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    labels = group_labels()
    for i, r in enumerate(build(snap), 1):
        m = r["motion"]
        sp = "، ".join(str(x) for x in m["spring"])
        out.append("| %d | %s | `%s` | %s | `%s` | `%s` | `%s` | %d | %s | `%s` | `%s` | `%s` |" % (
            i, r["fa"], r["id"], labels.get(r["group"], r["group"]), r["instai"]["animation"], m["enter"], sp, m["stagger"], m.get("stepFps") or "", r["trans"][0], r["bg"]["kind"], r["text"]["fx"]))
    return "\n".join(out)


def spring_table() -> str:
    """the spring of every InstAI animation approach with its damping ratio and the overshoot it really gives (computed, not typed)"""
    out = ["| حرکتِ InstAI | ورودِ پیش‌فرض | فنر (damping، stiffness، mass) | ζ | بالازدگیِ واقعی | خواستهٔ InstAI | تأخیرِ پله‌ای | پله‌ای؟ | دوربین |", "|---|---|---|---|---|---|---|---|---|"]
    for name, m in mapping.MOTION.items():
        sp = "، ".join(str(x) for x in m["spring"])
        cam = ("zoom %s" % m["cam"]["zoom"] + (" + pan" if m["cam"].get("pan") else "") + (" + rot" if m["cam"].get("rot") else "")) if m["cam"] else "—"
        out.append("| `%s` | `%s` | `%s` | %.2f | %d٪ | %d٪ | %d | %s | %s |" % (
            name, m["enter"], sp, mapping.zeta(m["spring"]), round(mapping.overshoot_of(m["spring"]) * 100), round(m["overshoot"] * 100), m["stagger"], "بله" if m["stepped"] else "خیر", cam))
    return "\n".join(out)


def qa_table(dirs: list[str]) -> str:
    """the measured result of apps.motion.tests_looks_e2e (looks-qa.json of one or several runs, in the order they were made: a later run of the same style replaces the
    earlier one): per style the errors and warnings qa.py found in 3 aspects x 3 scenes. Styles that are not one of the 30 (NM's own, run as a control) get their own lines."""
    from collections import Counter

    per, fbs = {}, {}
    for d in dirs:
        p = Path(d) / "looks-qa.json" if Path(d).is_dir() else Path(d)
        data = json.loads(p.read_text(encoding="utf-8"))
        for sid in data.get("ids") or list(data.get("per_style", {})):
            per[sid] = data.get("per_style", {}).get(sid, {"errors": 0, "warnings": 0})
            fbs[sid] = [f for f in data.get("findings", []) if f["style"] == sid]
    order = [r["id"] for r in recipes.RECIPES]
    names = {r["id"]: r["fa"] for r in recipes.RECIPES}
    codes = {"low_contrast": "کنتراستِ متن", "safe_zone": "ناحیهٔ امنِ پلتفرم", "accent_contrast": "رنگِ تأکید", "overflow": "سرریز", "overlap": "هم‌پوشانی", "small_text": "متنِ ریز"}
    fa = lambda v: str(v).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))

    def detail(sid):
        c = Counter(f["code"] for f in fbs[sid] if f["severity"] != "error")
        return "، ".join(f"{codes.get(k, k)} ×{v}" for k, v in sorted(c.items())) or "—"

    ids = [x for x in order if x in per]
    out = ["| # | سبک | شناسه | خطا | هشدار | هشدارها به تفکیک |", "|---|---|---|---|---|---|"]
    err = warn = 0
    tot = Counter()
    for i, sid in enumerate(ids, 1):
        out.append(f"| {i} | {names[sid]} | `{sid}` | {per[sid]['errors']} | {per[sid]['warnings']} | {detail(sid)} |")
        err += per[sid]["errors"]
        warn += per[sid]["warnings"]
        tot.update(f["code"] for f in fbs[sid] if f["severity"] != "error")
    extra = " (" + "، ".join(f"{codes.get(k, k)} {fa(v)}" for k, v in sorted(tot.items())) + ")" if tot else ""
    out.append("")
    out.append(f"جمع: {fa(len(ids))} سبک × ۳ نسبت (۹:۱۶، ۱:۱، ۱۶:۹) × ۳ صحنه (عنوان، فهرست، دعوت به اقدام) با متنِ واقعیِ «چغر»؛ {fa(len(ids) * 18)} نمای واقعی (هر صحنه دو فریم: ورود و پایان) "
               f"از رندرِ واقعیِ Remotion و `qa.py`ِ موتورِ موشن؛ **خطا: {fa(err)}**، هشدار: {fa(warn)}{extra}.")
    ctl = [x for x in per if x not in order]
    if ctl:
        cw = sum(per[x]["warnings"] for x in ctl)
        ce = sum(per[x]["errors"] for x in ctl)
        out.append("")
        out.append("**شاهد (سه سبکِ قدیمیِ NM با همین سنجش):** " + "؛ ".join(f"`{x}` خطا {fa(per[x]['errors'])}، هشدار {fa(per[x]['warnings'])} ({detail(x)})" for x in ctl)
                   + f". جمعِ شاهد: خطا {fa(ce)}، هشدار {fa(cw)}.")
    return "\n".join(out)


def update_qa(path: Path, dirs: list[str]) -> int:
    text = path.read_text(encoding="utf-8")
    table = qa_table(dirs)
    text, n = re.subn(r"(<!-- qa:begin -->\n).*?(\n<!-- qa:end -->)", lambda m: m.group(1) + table + m.group(2), text, flags=re.S)
    if n != 1:
        print("markers <!-- qa:begin --> / <!-- qa:end --> not found", file=sys.stderr)
        return 1
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"updated {path} (qa table)")
    return 0


def update_doc(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    for name, table in (("looks", doc_table()), ("motion", motion_table()), ("springs", spring_table())):
        text, n = re.subn(rf"(<!-- {name}:begin -->\n).*?(\n<!-- {name}:end -->)", lambda m: m.group(1) + table + m.group(2), text, flags=re.S)
        if n != 1:
            print(f"markers <!-- {name}:begin --> / <!-- {name}:end --> not found", file=sys.stderr)
            return 1
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"updated {path}")
    return 0


def main(argv: list[str]) -> int:
    if "--doc" in argv:
        print(doc_table())
        return 0
    if "--update-doc" in argv:
        return update_doc(Path(argv[argv.index("--update-doc") + 1]))
    if "--update-qa" in argv:
        i = argv.index("--update-qa")
        return update_qa(Path(argv[i + 1]), argv[i + 2:])
    classify()                                   # the partition of the 116 styles must be complete and consistent before anything is written
    rows = build()
    groups = known_groups()
    bad = [r["id"] for r in rows if r["group"] not in groups]
    if bad:
        print(f"unknown group in {bad}: add it to GROUPS in catalog.py", file=sys.stderr)
        return 1
    text = module_source(rows)
    if "--check" in argv:
        have = OUT_PY.read_text(encoding="utf-8") if OUT_PY.is_file() else ""
        if have != text:
            print(f"{OUT_PY.name} differs from what the generator makes: run python backend/tools/gen_instai_looks.py", file=sys.stderr)
            return 1
        print(f"ok: {OUT_PY.name} is what the generator makes ({len(rows)} styles)")
        return 0
    OUT_PY.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT_PY} ({len(rows)} styles)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
