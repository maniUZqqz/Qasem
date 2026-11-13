"""Splitting the work between several copies of آباگرام (his rule, 2026-11-06: the project is copied to several computers, there
is no shared database, and no person or page may be read twice). Each copy is «سیستم k از n» (Settings → «تقسیم کار», kept in
data/settings.json, so a copy never brings the setting of the one it was copied from). Every person and every page belongs to
exactly one system, by a rule every copy computes the same way and alone: crc32 of the key, modulo n. A person's key is
Instagram's numeric id when the list has it (a rename does not move him), else the username; a page's key is its username.
Nothing is asked of the other systems; they only have to agree on n. 1 of 1 (the default): no split, everything is ours."""
import zlib

import ig_prefs

MAX = ig_prefs.SHARE_MAX


def get():
    """(index, count) of this system; (1, 1) when the work is not split."""
    p = ig_prefs.load()
    k, n = p.get("share_index", 1), p.get("share_count", 1)
    if type(k) is not int or type(n) is not int or not 1 <= k <= n <= MAX:
        return 1, 1
    return k, n


def owner(key, count):
    """The system (1..count) a key belongs to; the same answer on every computer."""
    if count <= 1:
        return 1
    return zlib.crc32(str(key).strip().lower().encode("utf-8")) % count + 1


def person_key(username, pk=None):
    pk = str(pk).strip() if pk is not None else ""
    return pk or (username or "").strip().lower()


def mine(key, share=None):
    """Is this key this system's? share: (index, count) already read, to read the settings once for a whole list."""
    k, n = share or get()
    return n == 1 or owner(key, n) == k


def person_mine(username, pk=None, share=None):
    return mine(person_key(username, pk), share)


def page_owner(username):
    """(owner, index, count) for a page: who should run a full extraction, a whole list or a watch of it."""
    k, n = get()
    return owner((username or "").strip().lower(), n), k, n
