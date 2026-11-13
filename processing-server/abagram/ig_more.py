"""The profile page's other replies: the highlights tray and the list of similar accounts. Pure functions, no browser."""
from ig_profile import parse_body, pick

MAX_SIMILAR = 30


def walk(obj):
    """Every dict inside obj, outer before inner, in the order they appear."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def highlights_from_api(texts):
    """Story highlights of the profile, in the order Instagram gave them: id, title, cover address."""
    found, seen = [], set()
    for text in texts:
        for doc in parse_body(text):
            for node in walk(doc):
                ident = node.get("id")
                if isinstance(ident, str) and ident.startswith("highlight:") and "title" in node:
                    key = ident.split(":", 1)[1]
                    if key not in seen:
                        seen.add(key)
                        found.append({"id": key, "title": node.get("title") or "",
                                      "cover": pick(node, ("cover_media", "cropped_image_version", "url")), "url": f"/stories/highlights/{key}/"})
    return found


def similar_from_api(texts, username=None):
    """Accounts Instagram suggests as similar to this one (a long list: the first MAX_SIMILAR are kept)."""
    out, seen = [], {(username or "").lower()}
    for text in texts:
        for doc in parse_body(text):
            users = pick(doc, ("data", "xdt_api__v1__discover__chaining", "users"))
            for u in users if isinstance(users, list) else []:
                name = u.get("username") if isinstance(u, dict) else None
                if isinstance(name, str) and name.lower() not in seen:
                    seen.add(name.lower())
                    out.append({"username": name, "full_name": u.get("full_name") or "", "verified": bool(u.get("is_verified")),
                                "private": bool(u.get("is_private")), "id": str(u.get("pk") or u.get("id") or ""),
                                "avatar": pick(u, ("hd_profile_pic_url_info", "url")) or u.get("profile_pic_url")})
    return out[:MAX_SIMILAR]
