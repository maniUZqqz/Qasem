"""«پردازش»: who among a page's saved followers (or following) may matter. Step 1, the filter, asks nothing of Instagram:
words he chooses are looked for in each person's username and name. Step 2 reads the profile of each candidate, one at a
time, through the queue (task 'process', the same limits as everything else). Results come from the saved profiles.
State lives in data/process.json, one entry per list ("<page>/<followers|following>")."""
import json
import re
import threading
import time
from functools import wraps

import ig_profile as pr
import ig_score as sc
import ig_share
import ig_store
from ig_common import DATA
from ig_score import fold  # noqa: F401  (kept here too: ig_process.fold)

FILE = DATA / "process.json"
WHICH = ("followers", "following")
DEFAULT_WORDS = ["آبیاری", "کشاورزی", "قطره", "گلخانه", "irrigation", "irrig", "drip", "sprinkler", "agro", "agri",
                 "tarim", "tarım", "sulama", "damla", "sera", "greenhouse"]
MAX_WORDS, MAX_WORD = 60, 40
def clean_words(words):
    out = []
    for w in words or []:
        w = str(w).strip()[:MAX_WORD]
        if fold(w) and w not in out:
            out.append(w)
    return out[:MAX_WORDS]


_LOCK = threading.RLock()   # read → change → write of process.json, one at a time (the queue marks while he labels or re-ranks)


def _locked(fn):
    @wraps(fn)
    def run(*a, **kw):
        with _LOCK:
            return fn(*a, **kw)
    return run


def _read():
    data = pr.read_json(FILE, {}, backup=True)   # damaged (2026-11-07: zeros after a power cut): its .bak, never "nothing"
    return data if isinstance(data, dict) else {}


def _write(data):
    DATA.mkdir(parents=True, exist_ok=True)
    pr.write_atomic(FILE, json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"), backup=True)


def key(source, which):
    return f"{source.lower()}/{which}"


def lists():
    """Every saved followers / following list: the pages whose people can be processed."""
    out = []
    for which in WHICH:
        for f in sorted((DATA / which).glob("p_*.json")):
            data = ig_store.Section(DATA, which).load(f.stem[2:]) or {}
            if data.get("items"):
                out.append({"source": f.stem[2:], "which": which, "saved": len(data["items"]), "total": data.get("total"),
                            "complete": bool((data.get("harvest") or {}).get("done"))})
    return out


@_locked
def run_filter(source, which, words):
    """Step 1: the candidates of a list for these words. A person already read keeps his state."""
    people = (ig_store.Section(DATA, which).load(source) or {}).get("items") or []
    words = clean_words(words)
    folded = [(w, fold(w)) for w in words]
    data = _read()
    old = (data.get(key(source, which)) or {}).get("candidates") or {}
    found = {}
    for p in people:
        name = p.get("username") or ""
        hay = fold(name) + " " + fold(p.get("full_name"))
        hits = [w for w, f in folded if f in hay]
        if name and hits:
            prev = old.get(name) or {}
            found[name] = {"id": str(p.get("id") or prev.get("id") or ""), "full_name": p.get("full_name") or "", "private": bool(p.get("private")), "matched": hits,
                           "state": prev.get("state", "new"), "note": prev.get("note", ""), "read_at": prev.get("read_at")}
    data[key(source, which)] = {"source": source.lower(), "which": which, "words": words, "people": len(people),
                                "filtered_at": int(time.time()), "candidates": found}
    _write(data)
    return data[key(source, which)]


@_locked
def run_rank(source, which, words=(), min_score=0):
    """Step 1, asking nothing of Instagram: every person of the list gets a score from the list alone (ig_score.pre_score; his
    words count as the trade's), and those at min_score or above become candidates, read best first. Someone read before keeps
    his state, a label he set by hand stays; someone new to the ranking whose profile is already saved counts as read at once
    (the counts of step 2 are right straight away, not only once the queue has walked past him). buckets: how many people are
    high (70+), middle (40+) and low."""
    people = (ig_store.Section(DATA, which).load(source) or {}).get("items") or []
    words, min_score = clean_words(words), max(0, min(100, int(min_score or 0)))
    trade = sc._folded(list(sc.TRADE) + words)
    data = _read()
    old = (data.get(key(source, which)) or {}).get("candidates") or {}
    found, buckets, saved = {}, {"high": 0, "mid": 0, "low": 0}, _saved_profiles()
    for p in people:
        name = p.get("username") or ""
        if not name:
            continue
        score, why = sc.pre_score(p, words)
        buckets["high" if score >= 70 else "mid" if score >= 40 else "low"] += 1
        if score < min_score:
            continue
        prev = old.get(name) or {}
        state, read_at = prev.get("state", "new"), prev.get("read_at")
        if state == "new" and name.lower() in saved:
            state, read_at = "done", read_at or int(time.time())
        found[name] = {"id": str(p.get("id") or prev.get("id") or ""), "full_name": p.get("full_name") or "", "private": bool(p.get("private")),
                       "score": score, "why": why, "matched": sc.hits(f"{name} {p.get('full_name') or ''}", trade)[:3],
                       "state": state, "note": prev.get("note", ""), "read_at": read_at,
                       **({"lost": prev["lost"]} if prev.get("lost") else {}),
                       **({"label": prev["label"]} if prev.get("label") else {})}
    data[key(source, which)] = {"source": source.lower(), "which": which, "words": words, "min_score": min_score, "people": len(people),
                                "buckets": buckets, "filtered_at": int(time.time()), "mode": "rank", "candidates": found}
    _write(data)
    return data[key(source, which)]


def _saved_profiles():
    """Usernames (lower case) whose profile is saved: one listing of the folder instead of one file check per person."""
    folder = DATA / "profiles"
    return {f.stem[2:].lower() for f in folder.glob("p_*.json")} if folder.is_dir() else set()


def _by_score(entry):
    """Candidates in his reading order (2026-11-02): public pages tied to farming or irrigation (a trade word in the name), then
    private ones with such a word, then the other public pages, then the other private ones — best score first within each (a
    list ranked before scores existed keeps its order)."""
    def group(p):
        return (0 if p.get("matched") else 2) + (1 if p.get("private") else 0)
    return sorted(entry["candidates"].items(), key=lambda kv: (group(kv[1]), -(kv[1].get("score") or 0)))


def get(source, which):
    return _read().get(key(source, which))


def _mine(name, p, share):
    """Is this candidate this system's to read («تقسیم کار», ig_share)? By his numeric id when the list has it."""
    return ig_share.person_mine(name, p.get("id"), share)


def counts(entry, mine=False):
    """How many candidates there are, new, done and failed; mine=True: only this system's share of them («تقسیم کار»)."""
    c = {"total": 0, "new": 0, "done": 0, "failed": 0}
    share = ig_share.get() if mine else None
    for name, p in ((entry or {}).get("candidates") or {}).items():
        if mine and not _mine(name, p, share):
            continue
        c["total"] += 1
        c[p["state"] if p["state"] in c else "new"] += 1
    return c


LINE = ("network", "timeout")   # not read because of the line, not because of him
LINE_TRIES = 2                  # such a person comes again in his place this many times (2026-11-03: 170 lost to a VPN outage)


def _due(p):
    return p["state"] == "new" or (p["state"] == "failed" and p.get("note") in LINE and p.get("lost", 0) < LINE_TRIES)


@_locked
def next_candidate(source, which):
    """Step 2: the next person to read, or None. Someone whose profile was already saved (read by hand, or earlier) counts as read."""
    data = _read()
    entry = data.get(key(source, which))
    if not entry:
        return None
    store, changed, who, share = pr.Store(DATA), False, None, ig_share.get()
    for name, p in _by_score(entry):
        if not _due(p):
            continue
        if p["state"] == "new" and store.load(name):   # read here, by hand, or by another system and taken in with its JSON
            p["state"], p["read_at"], changed = "done", int(time.time()), True
            continue
        if not _mine(name, p, share):                   # another system's share: never read here
            continue
        who = name
        break
    if changed:
        _write(data)
    return who


@_locked
def next_candidates(source, which, n):
    """The next n people to read fast, as {username, id} (the numeric id is what the fast reader asks by)."""
    data = _read()
    entry = data.get(key(source, which))
    if not entry:
        return []
    store, changed, out, share = pr.Store(DATA), False, [], ig_share.get()
    for name, p in _by_score(entry):
        if not _due(p):
            continue
        if p["state"] == "new" and store.load(name):
            p["state"], p["read_at"], changed = "done", int(time.time()), True
            continue
        if not _mine(name, p, share):
            continue
        out.append({"username": name, "id": p.get("id") or ""})
        if len(out) >= n:
            break
    if changed:
        _write(data)
    return out


@_locked
def mark(source, which, username, state, note=""):
    data = _read()
    p = ((data.get(key(source, which)) or {}).get("candidates") or {}).get(username)
    if p is None:
        return
    p["state"], p["note"], p["read_at"] = state, note, int(time.time())
    if state == "failed" and note in LINE:
        p["lost"] = p.get("lost", 0) + 1
    _write(data)


_PROFILES = {}   # username -> (file time, saved profile): a page of results never reads the same profile file twice


def _profile(store, name):
    path = DATA / "profiles" / f"p_{name.lower()}.json"
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return None
    hit = _PROFILES.get(name)
    if hit and hit[0] == stamp:
        return hit[1]
    prof = store.load(name)
    _PROFILES[name] = (stamp, prof)
    return prof


def row(username, p, prof=None, words=()):
    """One candidate as the page shows it: its score and label (final once the profile was read, from the list before), the
    reasons, and what the saved profile says. A label he set by hand wins over the automatic one."""
    prof = prof or {}
    more = prof.get("more") or {}
    contact, address = more.get("contact") or {}, more.get("address") or {}
    links = [l.get("url") for l in prof.get("links") or [] if isinstance(l, dict) and l.get("url")]
    if prof:
        score, label, why = sc.final(prof, p, words)
    else:
        score, label, why = p.get("score", 0), "unknown", list(p.get("why") or [])
    kind = more.get("account_type")
    account = ("business" if prof.get("is_business") or kind == 2 else "creator" if kind == 3 else "personal") if prof else "unknown"
    return {"username": username, "full_name": prof.get("full_name") or p.get("full_name") or "", "matched": p.get("matched") or [],
            "state": p.get("state"), "note": p.get("note") or "", "private": prof.get("is_private", p.get("private")),
            "read": bool(prof), "business": account == "business", "account": account,
            "score": score, "pre": p.get("score"), "label": p.get("label") or label, "label_auto": label, "manual": bool(p.get("label")),
            "why": why, "category": prof.get("category") or "", "bio": (prof.get("biography") or "")[:300], "links": links[:3],
            "phone": contact.get("phone") or "", "email": contact.get("email") or "", "city": address.get("city") or "",
            "followers": prof.get("followers"), "posts": prof.get("posts"), "has_avatar": bool(prof.get("has_avatar"))}


def rows(source, which):
    entry = get(source, which)
    if not entry:
        return None, []
    store, words = pr.Store(DATA), entry.get("words") or []
    return entry, [row(u, p, _profile(store, u), words) for u, p in entry["candidates"].items()]


FILTERS = ("label", "account", "contact", "min_followers", "q", "read", "city")
SORTS = {"score": lambda r: (-r["score"], -(r["followers"] or 0), r["username"]),   # equal scores: the bigger page first
         # (this key had slipped into the comment above, so «ترتیب: فالوور» quietly sorted by score)
         "followers": lambda r: (-(r["followers"] if r["followers"] is not None else -1), r["username"]),
         "name": lambda r: r["username"]}


def pick(all_rows, label="", account="", contact=False, min_followers=0, q="", read="", city="", sort="score"):
    """The rows that pass his filters, in his order. label / account may be several, comma separated."""
    labels = {x for x in (label or "").split(",") if x}
    accounts = {x for x in (account or "").split(",") if x}
    needle, place = fold(q), fold(city)
    out = []
    for r in all_rows:
        if labels and r["label"] not in labels or accounts and r["account"] not in accounts:
            continue
        if contact and not (r["phone"] or r["email"]) or min_followers and (r["followers"] or 0) < min_followers:
            continue
        if read == "read" and not r["read"] or read == "unread" and r["read"]:
            continue
        if needle and needle not in fold(f"{r['username']} {r['full_name']} {r['bio']} {r['category']}"):
            continue
        if place and place not in fold(r["city"]):
            continue
        out.append(r)
    return sorted(out, key=SORTS.get(sort, SORTS["score"]))


def view(source, which, offset=0, limit=10, **filters):
    """One page of results with the counts the filters show (each count over the whole list, so he sees what is there)."""
    entry, all_rows = rows(source, which)
    if not entry:
        return None
    chosen = pick(all_rows, **filters)
    facets = {"label": {}, "account": {}}
    for r in all_rows:
        facets["label"][r["label"]] = facets["label"].get(r["label"], 0) + 1
        facets["account"][r["account"]] = facets["account"].get(r["account"], 0) + 1
    facets["contact"] = sum(1 for r in all_rows if r["phone"] or r["email"])
    facets["read"] = sum(1 for r in all_rows if r["read"])
    offset, limit = max(0, int(offset)), max(1, min(int(limit), 200))
    index, count = ig_share.get()
    return {**{k: v for k, v in entry.items() if k != "candidates"}, "counts": counts(entry), "facets": facets,
            "share": {"index": index, "count": count, "counts": counts(entry, mine=True)},   # «تقسیم کار»: what this system reads
            "total": len(chosen), "offset": offset, "rows": chosen[offset: offset + limit]}


@_locked
def set_label(source, which, username, label):
    """His own label for one person (None: back to the automatic one)."""
    data = _read()
    p = ((data.get(key(source, which)) or {}).get("candidates") or {}).get(username)
    if p is None:
        return False
    if label:
        p["label"] = label
    else:
        p.pop("label", None)
    _write(data)
    return True


EXPORT = [("یوزرنیم", "username", 24), ("لینک پیج", "url", 34), ("نام", "full_name", 26), ("برچسب", "label_fa", 18), ("امتیاز", "score", 8),
          ("نوع حساب", "account_fa", 12), ("دسته‌بندی اینستاگرام", "category", 22), ("شماره", "phone", 18), ("ایمیل", "email", 26),
          ("شهر", "city", 14), ("فالوور", "followers", 10), ("پست", "posts", 8), ("وب‌سایت و لینک‌ها", "links_text", 34),
          ("بیو", "bio", 50), ("چرا این امتیاز", "why_text", 44), ("پروفایل خوانده شده", "read", 10)]
ACCOUNT_FA = {"business": "کسب‌وکار", "creator": "کریتور", "personal": "شخصی", "unknown": "خوانده نشده"}


def export(source, which, **filters):
    """The rows he filtered, best first, as an .xlsx file (ig_xlsx): (bytes, how many rows) or (None, 0)."""
    import ig_xlsx
    entry, all_rows = rows(source, which)
    if not entry:
        return None, 0
    chosen = pick(all_rows, **{k: v for k, v in filters.items() if k in FILTERS or k == "sort"})
    table = [{**r, "url": f"https://www.instagram.com/{r['username']}/", "label_fa": sc.LABEL_FA.get(r["label"], r["label"]),
              "account_fa": ACCOUNT_FA.get(r["account"], r["account"]), "links_text": " ".join(r["links"]), "why_text": "، ".join(r["why"])}
             for r in chosen]
    return ig_xlsx.workbook(EXPORT, table, "پردازش"), len(table)

