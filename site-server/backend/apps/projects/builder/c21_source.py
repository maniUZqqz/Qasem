# -*- coding: utf-8 -*-
"""منبعِ کدِ قطعه‌های 21st.dev — فقط راه‌های روا:

* **نمونهٔ استفاده (Usage.tsx)** که صفحهٔ عمومیِ قطعه (بدونِ ورود) نشان می‌دهد («How X is used: the demo's code»). خودِ کدِ قطعه آن‌جا نیست
  («The component's own source comes with a free account»)؛ پس ``/r/`` و ``/api/`` (که robots.txt بسته) را نمی‌زنیم.
* **مخزنِ عمومیِ خودِ کتابخانه** در GitHub (نشانی‌اش در صفحهٔ ``.md`` ِ کتابخانهٔ 21st.dev آمده)، فقط اگر مجوزِ مخزن (LICENSE) آزاد باشد و مجوزِ خودِ قطعه در
  21st.dev هم آزاد باشد (هر دو شرط). فایل را از روی نامِ قطعه پیدا می‌کنیم؛ رکوردِ مبدأ (مخزن، مسیر، commit، مجوز، حقِ نشر) ذخیره می‌شود.
* **کدِ گرفته‌شده با کلیدِ API ِ مالک** (``c21st.fetch_code``؛ ۲ قطعه در روز).

هیچ‌چیزِ دیگری گرفته نمی‌شود. توابعِ این ماژول خالص‌اند (بی‌شبکه، بی‌زیرفرایند) تا آزمون‌پذیر باشند؛ شبکه و git در c21_pipeline است.
"""
from __future__ import annotations

import html as html_mod
import json
import os
import re
from pathlib import Path

PERMISSIVE_LICENSE_TEXT = (
    ("MIT", re.compile(r"permission is hereby granted, free of charge|\bMIT License\b", re.I)),
    ("Apache-2.0", re.compile(r"Apache License[\s,]+Version 2\.0", re.I)),
    ("BSD-3-Clause", re.compile(r"redistribution and use in source and binary forms.*neither the name", re.I | re.S)),
    ("BSD-2-Clause", re.compile(r"redistribution and use in source and binary forms", re.I)),
    ("ISC", re.compile(r"permission to use, copy, modify, and/or distribute this software for any purpose", re.I)),
    ("Unlicense", re.compile(r"This is free and unencumbered software released into the public domain", re.I)),
    ("0BSD", re.compile(r"\b0BSD\b")),
)
LICENSE_FILES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "COPYING", "license", "license.md", "License.md")
SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next", "coverage", "__tests__", "tests", "test", "e2e", "storybook", ".storybook", "docs", "doc", "public", ".github"}
CODE_EXT = (".tsx", ".jsx")
BAD_PATH = re.compile(r"(^|/)(demo|demos|example|examples|story|stories|test|tests|__tests__|e2e|content|docs?|templates?|playground|app/\(|pages/)(/|$)|\.(test|spec|stories|demo)\.", re.I)
GOOD_PATH = re.compile(r"(^|/)(registry|ui|components|blocks|sections|lib|src|elements)(/|$)", re.I)
MAX_FILE = 80_000
MAX_REPO_FILES = 6000


def detect_license(repo: Path) -> dict:
    """⇒ {'spdx': 'MIT'|…|'', 'file': 'LICENSE', 'copyright': 'Copyright (c) …', 'text_len': n}؛ ناشناخته ⇒ spdx ''."""
    for name in LICENSE_FILES:
        p = repo / name
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")[:20000]
            except OSError:
                continue
            spdx = next((k for k, rx in PERMISSIVE_LICENSE_TEXT if rx.search(text)), "")
            cp = re.search(r"^.*copyright\s*(?:\(c\)|©)?.*$", text, re.I | re.M)
            return {"spdx": spdx, "file": name, "copyright": (cp.group(0).strip()[:160] if cp else ""), "text_len": len(text)}
    pj = repo / "package.json"
    if pj.is_file():
        try:
            lic = json.loads(pj.read_text(encoding="utf-8")).get("license", "")
            if isinstance(lic, str) and lic in ("MIT", "Apache-2.0", "ISC", "BSD-3-Clause", "BSD-2-Clause", "0BSD", "Unlicense"):
                return {"spdx": lic, "file": "package.json", "copyright": "", "text_len": 0}
        except (OSError, ValueError):
            pass
    return {"spdx": "", "file": "", "copyright": "", "text_len": 0}


def is_permissive_spdx(spdx: str) -> bool:
    return (spdx or "") in ("MIT", "Apache-2.0", "ISC", "BSD-3-Clause", "BSD-2-Clause", "0BSD", "Unlicense")


# ───────────────────────────── صفحهٔ عمومیِ قطعه: نمونهٔ استفاده

_PRE = re.compile(r"<pre[^>]*>(.*?)</pre>", re.S)
_FILE_NAME = re.compile(r">\s*([\w./-]+\.(?:tsx|jsx|ts|js))\s*</p>")
IMPORT_RE = re.compile(r"""import\s+(?:[\w*\s{},$]+?\s+from\s+)?["']([^"']+)["']""")


def parse_demo(page_html: str) -> dict:
    """صفحهٔ HTMLِ قطعه ⇒ {'file': 'Usage.tsx', 'code': …, 'imports': […]} یا {}.
    فقط اولین بلوکِ کدی که import/export دارد (همان «نمونهٔ استفاده»)."""
    for m in _PRE.finditer(page_html or ""):
        code = html_mod.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip("\n")
        if not re.search(r"\b(import|export)\b", code):
            continue
        before = page_html[max(0, m.start() - 400):m.start()]
        names = _FILE_NAME.findall(before)
        return {"file": names[-1] if names else "Usage.tsx", "code": code[:MAX_FILE], "imports": imports_of(code)}
    return {}


def imports_of(code: str) -> list[str]:
    out = []
    for m in IMPORT_RE.finditer(code or ""):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


# ───────────────────────────── مخزن: یافتنِ فایلِ قطعه

def index_repo(repo: Path) -> dict[str, list[str]]:
    """نامِ فایل (بی‌پسوند، حروف کوچک) ⇒ مسیرهای نسبی؛ فقط tsx/jsx، بی‌پوشه‌های بی‌ربط."""
    out: dict[str, list[str]] = {}
    n = 0
    for dirpath, dirnames, files in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            if f.endswith(CODE_EXT):
                n += 1
                if n > MAX_REPO_FILES:
                    return out
                rel = os.path.relpath(os.path.join(dirpath, f), repo).replace("\\", "/")
                out.setdefault(os.path.splitext(f)[0].lower(), []).append(rel)
    return out


def pick_path(paths: list[str], slug: str = "") -> str:
    """از چند مسیرِ هم‌نام بهترین: مسیرِ «registry/ui/components/blocks» بهتر، «demo/example/test» بد؛ کوتاه‌تر بهتر."""
    if not paths:
        return ""
    scored = []
    for p in paths:
        s = 0
        if BAD_PATH.search(p):
            s -= 10
        if GOOD_PATH.search(p):
            s += 3
        if "/registry/" in "/" + p:
            s += 2
        scored.append((s, -len(p), p))
    scored.sort(reverse=True)
    return scored[0][2] if scored[0][0] > -10 else ""


def find_component(idx: dict, slug: str, demo_imports: list[str] | None = None) -> str:
    """نامِ قطعه (و importهای نمونه) ⇒ مسیرِ نسبیِ فایل در مخزن یا ''. نخست مسیرِ importِ نمونه (آخرین بخشش)، بعد خودِ نام."""
    names = []
    for spec in demo_imports or []:
        if spec.startswith("@/") or spec.startswith("~/") or spec.startswith("."):
            base = spec.rstrip("/").split("/")[-1].lower()
            if base and base not in ("utils", "index") and base not in names:
                names.append(base)
    s = slug.lower()
    for cand in names + [s]:
        got = pick_path(idx.get(cand, []), cand)
        if got:
            return got
    return ""


def local_specs_for(demo_imports: list[str], component_basename: str) -> list[str]:
    """importهای نمونه که به همین قطعه اشاره دارند (باید به فایلِ پیداشده نگاشته شوند)."""
    return [s for s in demo_imports or [] if (s.startswith("@/") or s.startswith("~/") or s.startswith(".")) and s.rstrip("/").split("/")[-1].lower() == component_basename.lower()]


def repo_roots(repo: Path) -> list[str]:
    """ریشه‌هایی که «@/» به آن‌ها نگاشت می‌شود (به ترتیب)."""
    roots = [repo / "src", repo]
    for top in ("apps", "packages"):
        d = repo / top
        if d.is_dir():
            for sub in sorted(p for p in d.iterdir() if p.is_dir())[:6]:
                roots += [sub / "src", sub]
    return [str(r) for r in roots if r.is_dir()]


EXPORT_RE = re.compile(r"export\s+(?:default\s+)?(?:async\s+)?(?:function|const|class)\s+([A-Z]\w*)")


def fallback_demo(spec: str, code: str) -> str:
    """نمونهٔ استفاده نبود: خودِ قطعه را بی‌props رندر می‌کند (برای بخش‌های خودکفا مثل hero)."""
    names = EXPORT_RE.findall(code or "")
    pick = "M.default || M.%s" % names[0] if names else "M.default"
    return ("import * as M from '%s';\nconst C: any = %s;\nexport default function Demo() { return <C />; }\n" % (spec, pick))


def bundle_from_repo(repo: Path, rel: str, slug: str, demo: dict, *, license_info: dict, repo_url: str, commit: str, idx: dict | None = None) -> dict:
    """⇒ bundle برای c21_convert.convert_bundle. idx = فهرستِ فایل‌های مخزن (index_repo): importهای دیگرِ نمونه هم (مثلاً قطعه‌ای که نمونه کنارِ خودش می‌آورد) به فایلِ مخزن نگاشت می‌شوند."""
    path = repo / rel
    code = path.read_text(encoding="utf-8", errors="replace")[:MAX_FILE]
    base = os.path.splitext(os.path.basename(rel))[0]
    imports = demo.get("imports") or []
    specs = local_specs_for(imports, base)
    spec = specs[0] if specs else "@/components/ui/%s" % base
    aliases = {s: str(path) for s in (specs or [spec])}
    for other in imports:                                              # importِ محلیِ دیگر در نمونه: فایلِ هم‌نامش در مخزن
        if other in aliases or not (other.startswith("@/") or other.startswith("~/")):
            continue
        got = pick_path((idx or {}).get(other.rstrip("/").split("/")[-1].lower(), []))
        if got:
            aliases[other] = str(repo / got)
    entry_code = demo.get("code") or fallback_demo(spec, code)
    return {"entry": {"path": demo.get("file") or "Demo.tsx", "code": entry_code}, "files": {}, "aliases": aliases, "roots": repo_roots(repo), "export": "auto",
            "source": {"kind": "upstream", "repo": repo_url, "path": rel, "commit": commit, "license": license_info.get("spdx", ""), "copyright": license_info.get("copyright", ""),
                       "license_file": license_info.get("file", ""), "demo": bool(demo.get("code"))}}


def bundle_from_api(files: list[dict], demo: dict, *, row: dict) -> dict:
    """کدِ گرفته‌شده با کلیدِ مالک (c21st.fetch_code) ⇒ bundle."""
    main = files[0]
    imports = demo.get("imports") or []
    base = os.path.splitext(os.path.basename(main.get("path") or "component.tsx"))[0]
    specs = local_specs_for(imports, base) or ["@/components/ui/%s" % base]
    vfiles = {s: main["content"] for s in specs}
    for f in files[1:]:
        b = os.path.splitext(os.path.basename(f.get("path") or ""))[0]
        if b:
            vfiles.setdefault("@/components/ui/%s" % b, f["content"])
    entry_code = demo.get("code") or fallback_demo(specs[0], main["content"])
    return {"entry": {"path": demo.get("file") or "Demo.tsx", "code": entry_code}, "files": vfiles, "aliases": {}, "roots": [], "export": "auto",
            "source": {"kind": "api", "repo": "", "path": main.get("path", ""), "commit": "", "license": row.get("license", ""), "copyright": "", "license_file": "", "demo": bool(demo.get("code"))}}
