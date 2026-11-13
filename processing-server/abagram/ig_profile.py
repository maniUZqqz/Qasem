"""What a profile is: its numbers and text read from the page, from Instagram's own API replies and from
the page's meta tags; merged into one record; saved on disk. No browser in here."""
import json
import os
import re
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
# First path segments that are Instagram pages, never usernames (a pasted post link must not become a name).
RESERVED = {"p", "reel", "reels", "stories", "explore", "accounts", "direct", "tv", "web", "about", "legal", "api"}
FRESH_FOR = 12 * 3600          # a saved profile is served this long without asking Instagram again
IMAGE_HOSTS = (".cdninstagram.com", ".fbcdn.net")
COUNTS = ("posts", "followers", "following")
USER_MARKS = ("full_name", "biography", "follower_count", "edge_followed_by", "is_private", "is_verified", "pk", "id")
UNITS = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


def clean_username(raw):
    """A username from what the person typed or pasted (@name, a profile link); None if it is neither."""
    s = (raw or "").strip()
    m = re.match(r"^(?:https?://)?(?:www\.)?instagram\.com/([^/?#\s]+)", s, re.I)
    if m:
        s = m.group(1)
    s = s.lstrip("@").strip().strip("/")
    return s if USERNAME_RE.match(s) and s.lower() not in RESERVED else None


def parse_count(text, title=None):
    """(value, exact). '8,621' is exact, '686M' is rounded, and a title like '686,535,095' beats the text."""
    for raw in (title, text):
        m = re.fullmatch(r"\s*(\d[\d,]*(?:\.\d+)?)\s*([KkMmBb]?)\s*", str(raw)) if raw is not None else None
        if m:
            number, unit = float(m.group(1).replace(",", "")), m.group(2).lower()
            return (int(round(number * UNITS[unit])), False) if unit else (int(number), True)
    return None, False


def unwrap_link(url):
    """A web address from what a bio shows; Instagram's own l.instagram.com redirect is opened up."""
    u = urlparse(str(url or "").strip())
    if u.scheme not in ("http", "https") or not u.netloc:
        return None
    if u.netloc.lower() == "l.instagram.com" and parse_qs(u.query).get("u"):
        return unwrap_link(parse_qs(u.query)["u"][0])
    return u.geturl()


def safe_image_url(url, base):
    """Only Instagram's own image hosts (or the test site) may be downloaded as an avatar."""
    u = urlparse(url or "")
    host = (u.hostname or "").lower()
    return u.scheme in ("http", "https") and bool(host) and (host == urlparse(base).hostname or host.endswith(IMAGE_HOSTS))


# ---- Instagram's API replies ---------------------------------------------------------------

def parse_body(text):
    """Replies may start with 'for (;;);' and may hold several JSON documents, one per line."""
    strip = lambda t: t.strip()[9:] if t.strip().startswith("for (;;);") else t.strip()  # noqa: E731
    try:
        return [json.loads(strip(text))]
    except ValueError:
        pass
    docs = []
    for line in text.splitlines():
        line = strip(line)
        if line[:1] in ("{", "["):
            try:
                docs.append(json.loads(line))
            except ValueError:
                continue
    return docs


def user_nodes(obj, username):
    """Every dict in obj that describes this user (matched by username, wherever it is nested)."""
    want, stack = username.lower(), [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            name = cur.get("username")
            if isinstance(name, str) and name.lower() == want and any(k in cur for k in USER_MARKS):
                yield cur
            stack.extend(v for v in cur.values() if isinstance(v, (dict, list)))
        elif isinstance(cur, list):
            stack.extend(v for v in cur if isinstance(v, (dict, list)))


def pick(node, *paths):
    """First value found along any of the key paths (a path is a key or a tuple of nested keys)."""
    for path in paths:
        cur = node
        for key in path if isinstance(path, tuple) else (path,):
            if not (isinstance(cur, dict) and key in cur):
                break
            cur = cur[key]
        else:
            if cur is not None:
                return cur
    return None


def as_int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    return int(v) if isinstance(v, str) and v.isdigit() else None


def as_bool(v):
    return v if isinstance(v, bool) else None


def links_of(node):
    found = []
    for item in pick(node, "bio_links") or []:
        url = unwrap_link((item or {}).get("url") or (item or {}).get("lynx_url")) if isinstance(item, dict) else None
        if url and url not in [x["url"] for x in found]:
            found.append({"title": str((item.get("title") or ""))[:120], "url": url})
    extra = unwrap_link(pick(node, "external_url"))
    if extra and extra not in [x["url"] for x in found]:
        found.append({"title": "", "url": extra})
    return found[:10]


def relation_of(node):
    fs = pick(node, "friendship_status")
    if not isinstance(fs, dict):
        return None
    rel = {"following": as_bool(fs.get("following")), "followed_by": as_bool(fs.get("followed_by")),
           "requested": as_bool(fs.get("outgoing_request")), "blocking": as_bool(fs.get("blocking"))}
    return {k: v for k, v in rel.items() if v is not None} or None


def user_names(items):
    """Usernames from a list of user dicts (or plain strings)."""
    out = []
    for u in items or []:
        name = u.get("username") if isinstance(u, dict) else u
        if isinstance(name, str) and name:
            out.append(name)
    return out


def more_of(node):
    """Small facts the profile reply carries about the account. Empty, false and unknown ones are left out."""
    out = {}
    account_type = as_int(node.get("account_type"))
    if account_type is not None:
        out["account_type"] = account_type  # 1 personal, 2 business, 3 creator
    legacy = node.get("business_address_json")  # the older API sent the address as a JSON string
    if isinstance(legacy, str):
        try:
            legacy = json.loads(legacy)
        except ValueError:
            legacy = None
    legacy = legacy if isinstance(legacy, dict) else {}
    address = {"street": node.get("address_street") or legacy.get("street_address") or "",
               "city": node.get("city_name") or legacy.get("city_name") or "",
               "zip": node.get("zip") or legacy.get("zip_code") or ""}
    if any(address.values()):
        out["address"] = address
    code, number = node.get("public_phone_country_code"), node.get("public_phone_number") or node.get("contact_phone_number")
    contact = {"email": node.get("public_email") or "", "phone": (f"+{code} {number}" if code and number else number) or ""}
    if any(contact.values()):
        out["contact"] = contact
    entities = pick(node, ("biography_with_entities", "entities")) or []
    mentions = [e["user"]["username"] for e in entities if isinstance(e, dict) and isinstance(e.get("user"), dict) and e["user"].get("username")]
    hashtags = [e["hashtag"]["name"] for e in entities if isinstance(e, dict) and isinstance(e.get("hashtag"), dict) and e["hashtag"].get("name")]
    for key, value in (("bio_mentions", mentions), ("bio_hashtags", hashtags), ("facepile", user_names(node.get("profile_context_facepile_users"))),
                       ("badges", [str(b.get("title") or b.get("name") or b) if isinstance(b, dict) else str(b) for b in node.get("account_badges") or []])):
        if value:
            out[key] = value
    for key, field in (("story_at", "latest_reel_media"), ("close_story_at", "latest_besties_reel_media"), ("reels", "total_clips_count")):
        value = as_int(node.get(field))
        if value:
            out[key] = value
    if node.get("fbid_v2"):
        out["facebook_id"] = str(node["fbid_v2"])
    for key, on in (("live", bool(node.get("live_broadcast_id"))), ("threads", node.get("show_text_post_app_badge") is True),
                    ("meta_verified", bool(pick(node, ("meta_verified_benefits_info", "active_meta_verified_benefits")))),
                    ("similar", node.get("has_chaining") is True), ("embeds_off", node.get("is_embeds_disabled") is True),
                    ("memorial", node.get("is_memorialized") is True), ("unpublished", node.get("is_unpublished") is True),
                    ("default_avatar", node.get("has_profile_pic") is False),
                    ("ai_label", pick(node, ("aigm_account_label_info", "is_enabled")) is True),
                    ("story_archive", node.get("has_story_archive") is True)):
        if on:
            out[key] = True
    return out


def from_node(node):
    """One user dict in Instagram's API shape (old or new key names) as our field names; absent stays absent."""
    uid = pick(node, "pk", "id", "pk_id")
    cat = pick(node, "category_name", "category")
    out = {
        "user_id": str(uid) if isinstance(uid, (int, str)) and not isinstance(uid, bool) else None,
        "full_name": pick(node, "full_name"),
        "biography": pick(node, "biography", "bio"),
        "followers": as_int(pick(node, "follower_count", ("edge_followed_by", "count"), "followers_count")),
        "following": as_int(pick(node, "following_count", ("edge_follow", "count"))),
        "posts": as_int(pick(node, "media_count", ("edge_owner_to_timeline_media", "count"))),
        "is_private": as_bool(pick(node, "is_private")),
        "is_verified": as_bool(pick(node, "is_verified")),
        "is_business": as_bool(pick(node, "is_business_account", "is_business")),
        "is_professional": as_bool(pick(node, "is_professional_account")),
        "mutual_count": as_int(pick(node, "mutual_followers_count")),
        "category": cat if isinstance(cat, str) and cat else None,
        "avatar": pick(node, ("hd_profile_pic_url_info", "url"), "profile_pic_url_hd", "profile_pic_url"),
        "links": links_of(node) or None,
        "pronouns": [p for p in (pick(node, "pronouns") or []) if isinstance(p, str)] or None,
        "relation": relation_of(node),
        "more": more_of(node) or None,
    }
    return {k: v for k, v in out.items() if v is not None}


def from_api(texts, username):
    """The richest record Instagram's own replies hold for this user ({} if none mention them)."""
    parts = [from_node(n) for text in texts for doc in parse_body(text) for n in user_nodes(doc, username)]
    merged = {}
    for part in sorted(parts, key=len, reverse=True):
        for key, value in part.items():
            merged.setdefault(key, value)
    return merged


# ---- the page itself ---------------------------------------------------------------------------

def counts_from(stats):
    """{'posts': (value, exact), ...} from [(key, text, title)] pairs."""
    got = {}
    for key, text, title in stats:
        value, exact = parse_count(text, title)
        if value is not None:
            got[key] = (value, exact)
    return got


def pack(fields, counts):
    """Fields plus counts as one partial record; counts that are only rounded are listed in 'approx'."""
    out = dict(fields)
    for key, (value, exact) in counts.items():
        out[key] = value
    approx = [k for k, (_, exact) in counts.items() if not exact]
    if approx:
        out["approx"] = approx
    return {k: v for k, v in out.items() if v is not None}


def from_meta(meta):
    """The page's og:/description tags: rounded counts, the name, a bio and a small avatar."""
    meta = meta or {}
    fields, counts = {"avatar": meta.get("og_image")}, {}
    m = re.match(r"\s*([\d.,]+[KMBkmb]?) Followers?, ([\d.,]+[KMBkmb]?) Following, ([\d.,]+[KMBkmb]?) Posts?\b",
                 meta.get("og_description") or "")
    if m:
        counts = counts_from(zip(("followers", "following", "posts"), m.groups(), (None, None, None)))
    t = re.match(r"^(.*?)\s*\(@([A-Za-z0-9._]+)\)\s*•", meta.get("og_title") or "")
    if t:
        fields["full_name"], fields["username"] = t.group(1), t.group(2)
    b = re.search(r'on Instagram: "(.*)"\s*$', meta.get("description") or "", re.S)
    if b:
        fields["biography"] = b.group(1)
    return pack(fields, counts)


def from_dom(dom):
    """What the profile header shows (see JS_DOM in ig_detect): exact counts come from the title attribute."""
    if not dom:
        return {}
    stats = dom.get("stats") or {}
    counts = counts_from((key, (stats.get(kind) or {}).get("text"), (stats.get(kind) or {}).get("title"))
                         for kind, key in (("post", "posts"), ("follower", "followers"), ("following", "following")))
    links = [{"title": "", "url": u} for u in (unwrap_link(h) for h in dom.get("hrefs") or []) if u]
    private = True if dom.get("private_note") else (False if dom.get("has_posts") else None)
    fields = {
        "username": dom.get("username") or None, "full_name": dom.get("full_name"),
        "biography": dom.get("bio"), "is_verified": bool(dom.get("verified")), "is_private": private,
        "avatar": dom.get("avatar"), "links": links or None, "link_text": dom.get("link_text") or None,
        "mutual_text": dom.get("mutual") or None,
    }
    return pack(fields, counts)


def merge(username, api, dom, meta):
    """One record. Per field the first source that has it wins (api, then page, then meta tags), except
    that an exact count beats a rounded one. 'sources' says where each field came from."""
    parts = (("api", api or {}), ("dom", dom or {}), ("meta", meta or {}))
    out, sources, approx = {}, {}, []
    for name, part in parts:
        for key, value in part.items():
            if key != "approx" and key not in COUNTS and key not in out and value is not None:
                out[key], sources[key] = value, name
    for key in COUNTS:
        cands = [(p[key], key not in p.get("approx", ()), n) for n, p in parts if p.get(key) is not None]
        best = next((c for c in cands if c[1]), cands[0] if cands else None)
        if best:
            out[key], sources[key] = best[0], best[2]
            if not best[1]:
                approx.append(key)
    out["approx"], out["sources"] = approx, sources
    out["username"] = out.get("username") or username
    return out


FIELDS = ("username", "user_id", "full_name", "biography", "followers", "following", "posts", "approx",
          "is_private", "is_verified", "is_business", "is_professional", "category", "links", "link_text",
          "pronouns", "relation", "more", "mutual_count", "mutual_text", "avatar", "sources")


def readable(merged):
    """Has the page given us anything worth saving? Counts or a name are enough."""
    return any(merged.get(k) is not None for k in COUNTS) or bool(merged.get("full_name"))


def build(merged, now=None):
    """The record that gets saved: known fields only, text fields never None, a UTC timestamp."""
    rec = {k: merged.get(k) for k in FIELDS}
    rec["avatar_remote"] = rec.pop("avatar")
    for key in ("full_name", "biography", "link_text", "mutual_text", "category"):
        rec[key] = rec[key] or ""
    rec["links"], rec["pronouns"], rec["more"] = rec["links"] or [], rec["pronouns"] or [], rec["more"] or {}
    rec["fetched_at"] = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return rec


# ---- on disk -------------------------------------------------------------------------------------

BACKUP_EVERY = 600   # seconds: the <name>.bak of a state file is at most this old


def _put(path, data):
    """Bytes into path: on the disk itself (fsync) BEFORE the new file takes the old one's place. Without the fsync a power
    cut can keep the new size but not the bytes (2026-11-07: six hard restarts in one afternoon left data/process.json as
    1.5 MB of zero bytes). The temporary name is per thread, so two writers of one file never meet in it; on Windows the
    swap is retried for a moment while a reader still holds the old file open."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        for wait in (0.02, 0.05, 0.1, 0.2, 0.4, 0.8, 0):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if not wait:
                    raise
                time.sleep(wait)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def write_atomic(path, data, backup=False):
    """Write bytes so a reader never sees half a file and a power cut never leaves a broken one. backup=True (a state file
    that cannot be rebuilt: the queue, «پردازش», the limits' counts, the users ...): <name>.bak gets the same bytes too, at
    most every BACKUP_EVERY seconds — read_json falls back to it when the file itself is damaged."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _put(path, data)
    if backup:
        bak = path.with_name(path.name + ".bak")
        try:
            fresh = time.time() - bak.stat().st_mtime < BACKUP_EVERY
        except OSError:
            fresh = False
        if not fresh:
            _put(bak, data)


_SET_ASIDE = set()   # (path, size, mtime) of damaged files already copied aside: one copy each, not one per read


def read_json(path, default=None, backup=False):
    """A JSON file → its data; `default` when it does not exist. A damaged file (zeros after a power cut, cut short, not JSON)
    is never taken for an empty one — the next write would wipe it for good, the way process.json was lost on 2026-11-07. A
    copy of it is set aside as <name>.bad-<time>, and with backup=True the <name>.bak is read in its place."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError:
        return default
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except ValueError:
        pass
    try:
        st = path.stat()
        mark = (str(path), st.st_size, st.st_mtime)
        if mark not in _SET_ASIDE:
            _SET_ASIDE.add(mark)
            bad = path.with_name(f"{path.name}.bad-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.copyfile(path, bad)
            print(f"[data] damaged file {path.name} ({st.st_size} bytes) set aside as {bad.name}"
                  + ("; reading its .bak" if backup else ""), file=sys.stderr, flush=True)
    except OSError:
        pass
    if backup:
        try:
            return json.loads(path.with_name(path.name + ".bak").read_bytes().decode("utf-8-sig"))
        except (OSError, ValueError):
            pass
    return default


def age_seconds(rec, now=None):
    try:
        then = datetime.fromisoformat(rec["fetched_at"])
    except (KeyError, ValueError, TypeError):
        return None
    return max(0, int(((now or datetime.now(timezone.utc)) - then).total_seconds()))


class Store:
    """One JSON file (and one avatar image) per profile in <root>/profiles. The 'p_' prefix keeps a
    username like 'con' from being a reserved device name on Windows."""

    def __init__(self, root):
        self.dir = Path(root) / "profiles"

    def _file(self, username, ext):
        return self.dir / f"p_{username.lower()}.{ext}"

    def load(self, username):
        try:
            return json.loads(self._file(username, "json").read_text("utf-8"))
        except (OSError, ValueError):
            return None

    def save(self, rec, avatar=None):
        """Save rec; avatar is (bytes, content_type) or None (an older image, if any, is kept)."""
        user = rec["username"]
        old = self.load(user) or {}
        if avatar:
            write_atomic(self._file(user, "img"), avatar[0])
            rec["has_avatar"], rec["avatar_type"] = True, avatar[1]
        else:
            rec["has_avatar"], rec["avatar_type"] = bool(old.get("has_avatar")), old.get("avatar_type")
        write_atomic(self._file(user, "json"), json.dumps(rec, ensure_ascii=False, indent=1).encode("utf-8"))
        return rec

    def avatar(self, username):
        """(path, content_type) of the saved avatar, or None."""
        rec = self.load(username) or {}
        path = self._file(username, "img")
        return (path, rec.get("avatar_type") or "image/jpeg") if rec.get("has_avatar") and path.exists() else None

    def listing(self, offset=0, limit=5):
        """Newest first. {'total': n, 'items': [short records]}"""
        files = sorted(self.dir.glob("p_*.json"), key=lambda f: f.stat().st_mtime, reverse=True) if self.dir.is_dir() else []
        items = []
        for f in files[max(0, offset): max(0, offset) + max(1, limit)]:
            try:
                rec = json.loads(f.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            item = {k: rec.get(k) for k in ("username", "full_name", "followers", "approx", "is_private",
                                            "is_verified", "fetched_at", "has_avatar", "category", "is_business")}
            item["story_at"] = (rec.get("more") or {}).get("story_at")   # the story ring of the home tray
            items.append(item)
        return {"total": len(files), "items": items}
