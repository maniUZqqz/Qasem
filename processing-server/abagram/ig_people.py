"""Followers and following: the people Instagram lists in a profile's dialog, taken from the JSON of its own replies
(GET /api/v1/friendships/<id>/followers/ and .../following/). Pure functions, no browser."""
import re

from ig_profile import as_bool, as_int, parse_body, parse_count

FOLLOW_PATH = re.compile(r"^/api/v1/friendships/(\d+)/(followers|following)/$")
PAGE = 12            # people one request brings (Instagram's own page size for these lists)
LINK_TEXT = re.compile(r"^\s*([\d.,]+ ?[KMBkmb]?)\s+(followers?|following)\s*$")


def person_of(u):
    """One person of a list in our shape; None when the entry is not a person."""
    if not isinstance(u, dict) or not isinstance(u.get("username"), str) or not u["username"]:
        return None
    story = as_int(u.get("latest_reel_media"))
    avatar = u.get("profile_pic_url")
    return {
        "id": str(u.get("pk") or u.get("id") or ""), "username": u["username"], "full_name": u.get("full_name") or "",
        "private": as_bool(u.get("is_private")), "verified": as_bool(u.get("is_verified")),
        "avatar": avatar if isinstance(avatar, str) and avatar.startswith("https://") else None,
        "default_avatar": u.get("has_anonymous_profile_picture") is True,
        "story_at": story if story else None,
        "favorite": as_bool(u.get("is_favorite")),
        "badges": [b for b in u.get("account_badges") or [] if isinstance(b, str)],
    }


def page_of_reply(text):
    """One reply of the list: {'users', 'has_more', 'next', 'limited', 'hidden', 'page_size'}; None if it is not a list reply."""
    doc = next((x for x in parse_body(text or "") if isinstance(x, dict) and isinstance(x.get("users"), list)), None)
    if doc is None or doc.get("status") not in (None, "ok"):
        return None
    users = [p for p in (person_of(u) for u in doc["users"]) if p]
    nxt = doc.get("next_max_id")
    return {"users": users, "has_more": doc.get("has_more") is True, "next": str(nxt) if nxt not in (None, "") else None,
            "limited": doc.get("should_limit_list_of_followers") is True or doc.get("should_limit_list_of_followings") is True,
            "hidden": as_int(doc.get("hidden_following_account_count")) or None, "page_size": as_int(doc.get("page_size"))}


def merge_pages(pages):
    """People of several replies in the order Instagram gave them, nobody twice (by id, else by username)."""
    out, seen = [], set()
    for page in pages:
        for p in page["users"]:
            key = p["id"] or p["username"].lower()
            if key not in seen:
                seen.add(key)
                out.append(p)
    return out


def count_in_link(text):
    """(number, exact) from the text of a profile's stat link like '11 followers' or '686M followers'; (None, False) otherwise."""
    m = LINK_TEXT.match(text or "")
    return parse_count(m.group(1).replace(" ", "")) if m else (None, False)
