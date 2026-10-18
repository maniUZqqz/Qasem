# -*- coding: utf-8 -*-
"""Pull the part of a log that says WHY a step failed.

`verify_all.py` calls `explain()` for every failed step and appends the result
to logs/verify/ERRORS.txt, so the person reading the report never has to open a
100 KB log to find the six lines that matter.

What it keeps, in this order of preference:
  * for a Django test run: every `ERROR:` / `FAIL:` block with its traceback;
  * any Python traceback found anywhere in the log;
  * TypeScript / build errors (`error TS1234`, `Failed to compile`, ...);
  * and always the last lines, because the final word is usually the verdict.

Also usable by hand:   python tools/verify_tail.py <log file> "<step name>"
"""
import re
import sys
from pathlib import Path

MAX_BLOCKS = 12
TAIL_LINES = 25


def read(path):
    raw = Path(path).read_bytes()
    for enc in ("utf-8", "cp1256", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def test_blocks(lines):
    """Django/unittest failure blocks: from `ERROR: test_x (...)` to the next rule."""
    blocks, current = [], None
    for line in lines:
        if re.match(r"^(ERROR|FAIL): ", line):
            if current:
                blocks.append(current)
            current = [line]
        elif current is not None:
            if line.startswith("======") or line.startswith("Ran "):
                blocks.append(current)
                current = None
            else:
                current.append(line)
    if current:
        blocks.append(current)
    return blocks


def tracebacks(lines):
    blocks, i = [], 0
    while i < len(lines):
        if lines[i].startswith("Traceback (most recent call last)"):
            j = i + 1
            while j < len(lines) and (lines[j].startswith((" ", "\t")) or not lines[j].strip()):
                j += 1
            blocks.append(lines[i:min(j + 1, len(lines))])   # +1: the exception line itself
            i = j + 1
        else:
            i += 1
    return blocks


def build_errors(lines):
    pat = re.compile(r"error TS\d+|^\s*Error:|Failed to compile|Type error:|Module not found|ERR!|✗", re.I)
    return [ln for ln in lines if pat.search(ln)]


def explain(path, title):
    out = ["#" * 70, "مرحله : %s" % title, "لاگ   : %s" % Path(path).name]
    if not Path(path).exists():
        out += ["(این مرحله هیچ لاگی ننوشت — یعنی خودِ دستور اصلاً اجرا نشد؛ python یا npm در PATH هست؟)", ""]
        return "\n".join(out)
    lines = read(path).splitlines()
    if not lines:
        out += ["(لاگ خالی است — دستور قبل از نوشتنِ حتی یک خط متوقف شد.)", ""]
        return "\n".join(out)
    shown = False

    blocks = test_blocks(lines)
    if blocks:
        shown = True
        out.append("--- %d تستِ ردشده (تا %d تا نشان داده می‌شود) ---" % (len(blocks), MAX_BLOCKS))
        for b in blocks[:MAX_BLOCKS]:
            out += ["\n".join(b[:40]).rstrip(), ""]
    else:
        tbs = tracebacks(lines)
        if tbs:
            shown = True
            out.append("--- traceback ---")
            for b in tbs[-3:]:
                out += ["\n".join(b[-30:]).rstrip(), ""]
        errs = build_errors(lines)
        if errs:
            shown = True
            out.append("--- خط‌های خطا ---")
            out += [ln.rstrip()[:300] for ln in errs[:30]]
            out.append("")

    out.append("--- آخرین %d خط%s ---" % (TAIL_LINES, "" if shown else " (چیز مشخص‌تری در لاگ پیدا نشد)"))
    out += [ln.rstrip()[:300] for ln in lines[-TAIL_LINES:]]
    out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        sys.exit(2)
    print(explain(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]))
