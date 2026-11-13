"""Posts: what Instagram's own replies say about a person's posts. Pure functions, no browser."""
import re
from datetime import datetime, timezone

from ig_profile import parse_body, pick

THUMB_WIDTH = 320    # the list thumbnail is the smallest picture at least this wide
MAX_ITEMS = 20       # slides kept per album
HASHTAG = re.compile(r"#(\w+)", re.UNICODE)
MENTION = re.compile(r"@([A-Za-z0-9._]{1,30})")
COUNT_KEYS = ("view_count", "play_count", "ig_play_count", "fb_play_count")


def owned_by(node, want, user_id):
    for key in ("user", "owner"):
        who = node.get(key)
        if isinstance(who, dict):
            name = who.get("username")
            if isinstance(name, str):
                return name.lower() == want
            if user_id and str(who.get("pk") or who.get("id")) == str(user_id):
                return True
    return False


def media_nodes(obj, username, user_id=None):
    """Top-level post dicts of this user, wherever they sit in obj. A post is never searched inside:
    an album's slides carry a code too, but they are not posts of their own."""
    want, stack = username.lower(), [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if "code" in cur and "taken_at" in cur and "media_type" in cur and not cur.get("carousel_parent_id"):
                if owned_by(cur, want, user_id):
                    yield cur
                continue
            stack.extend(v for v in cur.values() if isinstance(v, (dict, list)))
        elif isinstance(cur, list):
            stack.extend(v for v in cur if isinstance(v, (dict, list)))


def pictures(node):
    """Image candidates, biggest first."""
    found = [c for c in (pick(node, ("image_versions2", "candidates")) or []) if isinstance(c, dict) and c.get("url")]
    return sorted(found, key=lambda c: c.get("width") or 0, reverse=True)


def thumb_url(node):
    """The smallest picture that is at least THUMB_WIDTH wide (else the biggest there is)."""
    found = pictures(node)
    if not found:
        return None
    big_enough = [c for c in found if (c.get("width") or 0) >= THUMB_WIDTH]
    return (big_enough[-1] if big_enough else found[0])["url"]


def item_of(node):
    """One picture or one video (an album has several)."""
    found = pictures(node)
    videos = sorted([v for v in node.get("video_versions") or [] if isinstance(v, dict) and v.get("url")],
                    key=lambda v: v.get("width") or 0, reverse=True)
    top = found[0] if found else (videos[0] if videos else {})
    return {"type": "video" if videos or node.get("media_type") == 2 else "image",
            "width": top.get("width"), "height": top.get("height"),
            "image": found[0]["url"] if found else None, "video": videos[0]["url"] if videos else None,
            "alt": node.get("accessibility_caption") or None}


def tagged_of(node):
    """People tagged in the post or in any slide of it, once each."""
    seen, out = set(), []
    for src in [node] + [c for c in node.get("carousel_media") or [] if isinstance(c, dict)]:
        for tag in pick(src, ("usertags", "in")) or []:
            who = (tag or {}).get("user") or {}
            name = who.get("username")
            if name and name not in seen:
                seen.add(name)
                where = tag.get("position") if isinstance(tag.get("position"), list) else []
                out.append({"username": name, "full_name": who.get("full_name") or "", "verified": bool(who.get("is_verified")),
                            "id": str(who.get("pk") or who.get("id") or ""),
                            "x": where[0] if len(where) > 0 else None, "y": where[1] if len(where) > 1 else None})
    return out


def music_of(node):
    clip = node.get("clips_metadata")
    if not isinstance(clip, dict):
        return None
    info = pick(clip, ("music_info", "music_asset_info"))
    if isinstance(info, dict) and (info.get("title") or info.get("display_artist")):
        return {"kind": "music", "title": info.get("title") or "", "artist": info.get("display_artist") or ""}
    original = clip.get("original_sound_info")
    if isinstance(original, dict):
        return {"kind": "original", "title": original.get("original_audio_title") or "", "artist": pick(original, ("ig_artist", "username")) or ""}
    return None


def location_of(node):
    loc = node.get("location")
    if not isinstance(loc, dict):
        return None
    ident = loc.get("pk") or loc.get("id") or loc.get("facebook_places_id")
    return {"name": loc.get("name") or loc.get("short_name") or "", "id": str(ident or ""), "city": loc.get("city") or "",
            "address": loc.get("address") or "", "lat": loc.get("lat"), "lng": loc.get("lng")}


def names_of(users):
    """Usernames from a list of user dicts (or of wrappers such as {'sponsor': {...}})."""
    out = []
    for u in users or []:
        who = u.get("sponsor") if isinstance(u, dict) and isinstance(u.get("sponsor"), dict) else u
        if isinstance(who, dict) and who.get("username"):
            out.append(who["username"])
    return out


def unique(items):
    """The items without repeats, in the order they came."""
    return list(dict.fromkeys(i for i in items if i))


def count_of(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def post_from_node(node):
    """One post in our own shape. Raises KeyError/TypeError on something that is not a post."""
    media, product, code = node.get("media_type"), node.get("product_type"), node["code"]
    kind = "album" if media == 8 else "reel" if product == "clips" else "video" if media == 2 else "photo"
    caption = pick(node, ("caption", "text")) or ""
    slides = [c for c in node.get("carousel_media") or [] if isinstance(c, dict)]
    items = [item_of(c) for c in (slides or [node])][:MAX_ITEMS]
    hidden = bool(node.get("like_and_view_counts_disabled"))
    taken = int(node["taken_at"])
    views = next((count_of(node.get(k)) for k in COUNT_KEYS if count_of(node.get(k)) is not None), None)
    return {
        "code": code, "id": str(node.get("pk") or ""), "kind": kind,
        "url": f"/{'reel' if kind == 'reel' else 'p'}/{code}/",
        "taken_at": taken, "taken_iso": datetime.fromtimestamp(taken, timezone.utc).isoformat(timespec="seconds"),
        "caption": caption, "hashtags": unique(HASHTAG.findall(caption))[:30],
        "mentions": unique(m.rstrip(".") for m in MENTION.findall(caption))[:30],  # a full stop ends the sentence, not the name
        "likes": None if hidden else count_of(node.get("like_count")), "comments": count_of(node.get("comment_count")),
        "views": views, "likes_hidden": hidden, "comments_disabled": bool(node.get("comments_disabled")),
        "pinned": bool(node.get("timeline_pinned_user_ids")),
        "location": location_of(node), "tagged": tagged_of(node), "music": music_of(node),
        "coauthors": names_of(node.get("coauthor_producers")), "sponsors": names_of(node.get("sponsor_tags")),
        "paid_partnership": bool(node.get("is_paid_partnership")), "alt": node.get("accessibility_caption") or None,
        "items": items, "items_count": len(slides) or 1, "thumb": thumb_url(slides[0] if slides else node),
        "width": node.get("original_width"), "height": node.get("original_height"),
        "fb_likes": count_of(node.get("fb_like_count")), "fb_comments": count_of(node.get("fb_comment_count")),
    }


def posts_from_api(texts, username, user_id=None, limit=12):
    """This user's posts found in Instagram's replies, newest first (pinned ones sit by date, flagged)."""
    found = {}
    for text in texts:
        for doc in parse_body(text):
            for node in media_nodes(doc, username, user_id):
                try:
                    post = post_from_node(node)
                except (KeyError, TypeError, ValueError):
                    continue
                found.setdefault(post["code"], post)
    return sorted(found.values(), key=lambda p: p["taken_at"], reverse=True)[:limit]
