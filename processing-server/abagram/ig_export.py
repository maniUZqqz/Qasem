"""The JSON of one page («دریافت JSON»): everything saved about it — its profile, posts, highlights, stories, reels, similar
pages, comments, the list of downloaded files, the «پردازش» results — and its whole followers / following lists, each person
with his own saved profile (and anything else saved about him). One format for the site's download, for handing the data to
someone else, and for taking it back in (ig_import). Built from the files in data/ only: nothing is asked of Instagram.

It is written piece by piece (chunks): a list of tens of thousands of people never sits in memory as one big text.
Pictures are not inside (the avatars alone are hundreds of megabytes): every person keeps Instagram's own picture links."""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import ig_files
import ig_process
import ig_profile
import ig_store
from ig_common import DATA

FORMAT, VERSION = "abagram-page", 1
SECTIONS = ("posts", "highlights", "similar", "details", "stories", "reels")   # one file per person each (ig_store.Section)
LISTS = ("followers", "following")
# a whole-list read's position belongs to the Instagram session that made it (it answered «wait» to an old one): not exported
HARVEST_KEEP = ("started_at", "updated_at", "runs", "pages", "more", "done")
PERSON_PROCESS = ("score", "label", "state", "note", "read_at", "why", "matched")


def _dump(value):
    return json.dumps(value, ensure_ascii=False)


def _process_file(root):
    data = ig_profile.read_json(Path(root) / "process.json", {}, backup=True)
    return data if isinstance(data, dict) else {}


def saved_anything(username, root=DATA):
    """Is anything at all saved about this page (its profile, a section, a list)?"""
    root = Path(root)
    return ig_profile.Store(root)._file(username, "json").is_file() or any(
        ig_store.Section(root, s)._file(username).is_file() for s in SECTIONS + LISTS)


class _Renamed:
    """username by numeric id of every saved profile, made the first time a person read under his list name has no profile
    file: he changed his username since the list was read, and his profile was saved under the new one (2026-11-05: 5 of 2,480)."""

    def __init__(self, store):
        self.store, self.names = store, None

    def find(self, uid):
        if self.names is None:
            self.names = {}
            for f in self.store.dir.glob("p_*.json") if self.store.dir.is_dir() else []:
                try:
                    rec = json.loads(f.read_text("utf-8"))
                except (OSError, ValueError):
                    continue
                if rec.get("user_id") and rec.get("username"):
                    self.names[str(rec["user_id"])] = rec["username"]
        return self.names.get(str(uid))


def _person(item, store, sections, candidates, renamed):
    """One person of a list with what we know about him: his saved profile, other saved data, his «پردازش» result."""
    name = item.get("username") or ""
    prof = store.load(name) if ig_profile.USERNAME_RE.match(name) else None
    cand = candidates.get(name)
    now_name = None
    if prof is None and cand and cand.get("state") == "done" and item.get("id"):
        now_name = renamed.find(item["id"])
        prof = store.load(now_name) if now_name else None
    extra = {s: sec.load(now_name or name) for s, sec in sections.items()} if prof else {}
    out = {**item, "profile": prof, "process": {k: cand[k] for k in PERSON_PROCESS if k in cand} if cand else None}
    if prof and now_name:
        out["renamed_to"] = now_name
    if any(extra.values()):
        out["saved"] = {k: v for k, v in extra.items() if v}
    return out


def chunks(username, root=DATA, by=None, now=None):
    """The page's JSON as pieces of text, in order (join them, or send them one by one)."""
    root, user = Path(root), username.lower()
    store = ig_profile.Store(root)
    sections = {s: ig_store.Section(root, s) for s in SECTIONS}
    procs, renamed = _process_file(root), _Renamed(store)
    head = {"format": FORMAT, "version": VERSION, "username": user, "exported_by": by,
            "exported_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
            "profile": store.load(user), "sections": {s: sec.load(user) for s, sec in sections.items()},
            "files": ig_files.Files(root).listing(user) or None}
    yield _dump(head)[:-1]                       # the object stays open: the two lists follow
    for which in LISTS:
        data = ig_store.Section(root, which).load(user)
        if not data:
            yield f", {_dump(which)}: null"
            continue
        entry = procs.get(ig_process.key(user, which)) or {}
        meta = {k: v for k, v in data.items() if k not in ("items", "harvest")}
        meta["harvest"] = {k: v for k, v in (data.get("harvest") or {}).items() if k in HARVEST_KEEP} or None
        meta["saved"] = len(data.get("items") or [])
        meta["process"] = {**{k: v for k, v in entry.items() if k != "candidates"}, "counts": ig_process.counts(entry)} if entry else None
        yield f", {_dump(which)}: {_dump(meta)[:-1]}, \"items\": ["
        read, cands = 0, entry.get("candidates") or {}
        for n, item in enumerate(data.get("items") or []):
            person = _person(item, store, sections, cands, renamed)
            read += person["profile"] is not None
            yield ("," if n else "") + _dump(person)
        yield f"], \"with_profile\": {read}}}"
    yield "}"


def pages(root=DATA):
    """The pages with more than a bare profile saved (a followers / following list, posts, highlights …), biggest list first:
    what «تبادلِ JSON» offers. Every saved profile can still be downloaded by its name."""
    root, names = Path(root), set()
    for kind in SECTIONS + LISTS:
        folder = root / kind
        names |= {f.stem[2:] for f in folder.glob("p_*.json")} if folder.is_dir() else set()
    store, procs, out = ig_profile.Store(root), _process_file(root), []
    for name in sorted(n for n in names if ig_profile.USERNAME_RE.match(n)):
        prof = store.load(name) or {}
        row = {"username": name, "full_name": prof.get("full_name") or "", "followers": prof.get("followers"),
               "has_avatar": bool(prof.get("has_avatar")), "profile": bool(prof),
               "sections": [s for s in SECTIONS if ig_store.Section(root, s)._file(name).is_file()], "lists": {}}
        for which in LISTS:
            data = ig_store.Section(root, which).load(name)
            if data:
                entry = procs.get(ig_process.key(name, which))
                row["lists"][which] = {"saved": len(data.get("items") or []), "total": data.get("total"),
                                       "complete": bool((data.get("harvest") or {}).get("done")),
                                       "read": ig_process.counts(entry)["done"] if entry else None}
        out.append(row)
    return sorted(out, key=lambda r: (-max([x["saved"] for x in r["lists"].values()] or [0]), r["username"]))


def build(username, root=DATA, by=None, now=None):
    """The whole JSON as one object (tests; a small page)."""
    return json.loads("".join(chunks(username, root, by, now)))


def filename(username, at=None):
    return f"abagram-{username.lower()}-{time.strftime('%Y%m%d-%H%M', time.localtime(at))}.json"


def write(username, path, root=DATA, by=None):
    """Write the page's JSON to a file (atomically); returns its size in bytes."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for piece in chunks(username, root, by):
            f.write(piece)
        f.flush()
        os.fsync(f.fileno())   # on the disk before it takes the old file's place (a power cut leaves no file of zeros)
    tmp.replace(path)
    return path.stat().st_size


if __name__ == "__main__":   # python ig_export.py <page> [file]: the same JSON as the site's download, written here
    page = sys.argv[1]
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(filename(page))
    if not saved_anything(page):
        sys.exit(f"nothing saved about {page}")
    print(target, write(page, target))
