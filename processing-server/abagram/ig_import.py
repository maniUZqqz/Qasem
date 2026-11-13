"""Taking a page's JSON in («آپلود JSON»): the format ig_export writes (abagram-page). What is new is added, what is newer
replaces ours, what we have newer stays; a followers / following list is merged person by person (nobody twice), never
replaced, and nothing is deleted. A list whose whole-list read is open right now is left alone (that window writes the file;
the people's profiles still come in). The file comes from someone else: every name is checked before it names a file.
Nothing is asked of Instagram."""
import json
from datetime import datetime, timezone
from pathlib import Path

import ig_profile
import ig_store
from ig_common import DATA
from ig_export import FORMAT, HARVEST_KEEP, LISTS, SECTIONS, VERSION
from ig_profile import write_atomic

MAX_RECORD = 2_000_000      # bytes of one saved record (a profile, a section): bigger is not ours
PERSON_DROP = ("profile", "process", "saved", "renamed_to")   # what the export adds to a person of a list
LIST_KEEP = ("total", "more", "limited", "hidden", "reason", "read_at", "order", "fetched_at")


class Refused(Exception):
    """The file is not a page's JSON from آباگرام (the message says why, in Persian)."""


def _when(rec):
    try:
        t = datetime.fromisoformat(str((rec or {}).get("fetched_at")))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _newer(theirs, ours):
    """Take theirs? Yes when we have nothing, or theirs was read later (one without a date never replaces ours)."""
    if not ours:
        return True
    a, b = _when(theirs), _when(ours)
    return bool(a and (b is None or a > b))


def _name(value):
    return value.lower() if isinstance(value, str) and ig_profile.USERNAME_RE.match(value) else None


def _small(rec):
    return isinstance(rec, dict) and len(json.dumps(rec, ensure_ascii=False)) <= MAX_RECORD


def _save_as_is(path, rec):
    """A record exactly as it came (its own fetched_at kept: the date says when it was read, not when it arrived)."""
    write_atomic(path, json.dumps(rec, ensure_ascii=False, indent=1).encode("utf-8"))


def check(doc):
    """The page this file is about; Refused when it is not a page's JSON we can read."""
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise Refused("این فایل JSONِ یک پیج از آباگرام نیست (همان فایلی که «دریافت JSON» می‌دهد).")
    if not isinstance(doc.get("version"), int) or doc["version"] > VERSION:
        raise Refused("این فایل را نسخهٔ تازه‌تری از آباگرام ساخته؛ اول این آباگرام را به‌روز کن.")
    page = _name(doc.get("username"))
    if not page:
        raise Refused("نامِ پیج در این فایل درست نیست.")
    return page


def _profile(store, rec, counts):
    """One saved profile from the file: new, newer (replaces ours) or older (ours stays). Its picture stays ours."""
    name = _name((rec or {}).get("username")) if isinstance(rec, dict) else None
    if not name or not _small(rec):
        counts["bad"] += 1
        return None
    if not _newer(rec, store.load(name)):
        counts["kept"] += 1
        return name
    counts["updated" if store.load(name) else "new"] += 1
    store.save({k: v for k, v in rec.items() if k not in ("has_avatar", "avatar_type")})
    return name


def _section(sec, name, rec, counts):
    if not isinstance(rec, dict) or not _small(rec):
        return
    if _newer(rec, sec.load(name)):
        counts["sections"] += 1
        _save_as_is(sec._file(name), rec)


def _keys(p):
    return {k for k in (str(p.get("id") or ""), (p.get("username") or "").lower()) if k}


def _merge_list(sec, page, theirs):
    """Their people after ours, nobody twice; our own list facts (and its whole-list read state) stay as they are."""
    ours = sec.load(page)
    known = set()
    for p in (ours or {}).get("items") or []:
        known |= _keys(p)
    new = []
    for p in theirs.get("items") or []:
        if not isinstance(p, dict) or not _name(p.get("username")) or _keys(p) & known:
            continue
        known |= _keys(p)
        new.append({k: v for k, v in p.items() if k not in PERSON_DROP})
    if ours:
        ours["items"] = (ours.get("items") or []) + new
        if isinstance(theirs.get("total"), int) and theirs["total"] > (ours.get("total") or 0):
            ours["total"] = theirs["total"]
    else:   # a list we never had: theirs, with how far its read went (complete or not); the position never travels anyway
        ours = {**{k: theirs[k] for k in LIST_KEEP if k in theirs}, "items": new}
        state = theirs.get("harvest") if isinstance(theirs.get("harvest"), dict) else {}
        if any(k in state for k in HARVEST_KEEP):
            ours["harvest"] = {k: state[k] for k in HARVEST_KEEP if k in state and isinstance(state[k], (str, int, bool, type(None)))}
        ours.setdefault("fetched_at", ig_store.now_iso())
    if new or not sec._file(page).is_file():
        _save_as_is(sec._file(page), ours)
    return {"added": len(new), "saved": len(ours["items"])}


def merge(doc, root=DATA, busy=lambda page: ()):
    """Take one page's JSON in. busy(page) names the lists of that page whose whole-list read is open now (left alone).
    Returns what changed: {'page', 'profile', 'sections', 'lists': {which: {'added', 'saved'} | {'skipped'}}, 'people': {...}}."""
    page = check(doc)
    root = Path(root)
    store = ig_profile.Store(root)
    sections = {s: ig_store.Section(root, s) for s in SECTIONS}
    report = {"page": page, "profile": "none", "sections": 0, "lists": {},
              "people": {"new": 0, "updated": 0, "kept": 0, "bad": 0, "sections": 0}}
    prof = doc.get("profile")
    if isinstance(prof, dict):
        own = {"new": 0, "updated": 0, "kept": 0, "bad": 0}
        if _name(prof.get("username")) == page:
            _profile(store, prof, own)
        report["profile"] = next((k for k, v in own.items() if v), "bad")
    counts = {"sections": 0}
    for s, rec in (doc.get("sections") or {}).items() if isinstance(doc.get("sections"), dict) else ():
        if s in sections:
            _section(sections[s], page, rec, counts)
    report["sections"] = counts["sections"]
    open_now = set(busy(page) or ())
    people = report["people"]
    for which in LISTS:
        theirs = doc.get(which)
        if not isinstance(theirs, dict) or not isinstance(theirs.get("items"), list):
            continue
        report["lists"][which] = {"skipped": "harvest"} if which in open_now else _merge_list(ig_store.Section(root, which), page, theirs)
        for p in theirs["items"]:
            if isinstance(p, dict) and isinstance(p.get("profile"), dict):
                name = _profile(store, p["profile"], people)
                for s, rec in (p.get("saved") or {}).items() if name and isinstance(p.get("saved"), dict) else ():
                    if s in sections:
                        _section(sections[s], name, rec, people)
    return report


def read(data):
    """The bytes of an uploaded file → the parsed page JSON (Refused when it is not JSON at all)."""
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise Refused("این فایل JSON نیست یا ناقص رسیده.") from None
