"""Story reels: a person's active story and the items of a highlight, from the JSON a story page carries inside its HTML.
Reading them never presses Instagram's "View story" button. Pure functions, no browser."""
import json

from ig_comments import SCRIPT_JSON
from ig_more import walk
from ig_posts import count_of, pictures, thumb_url, unique
from ig_profile import parse_body, pick

MAX_ITEMS = 100


def docs_from_html(html):
    """The JSON blobs of a story page that carry reels."""
    docs = []
    for blob in SCRIPT_JSON.findall(html or ""):
        if "XDTReelDict" in blob or "reels_media" in blob:
            try:
                docs.append(json.loads(blob))
            except ValueError:
                continue
    return docs


def usernames(stickers, inner):
    """Usernames from a list of stickers like [{'user': {'username': 'a'}}] (inner='user')."""
    out = []
    for s in stickers or []:
        who = s.get(inner) if isinstance(s, dict) and isinstance(s.get(inner), dict) else s
        if isinstance(who, dict) and isinstance(who.get("username"), str):
            out.append(who["username"])
    return unique(out)


def web_addresses(stickers):
    """Every web address found inside link stickers, once each."""
    found = []
    for sticker in stickers or []:
        for node in walk(sticker):
            for key, value in node.items():
                if key in ("url", "display_url", "link_url") and isinstance(value, str) and value.startswith(("http://", "https://")):
                    found.append(value)
    return unique(found)


def music_of(item):
    for sticker in item.get("story_music_stickers") or []:
        info = sticker.get("music_asset_info") if isinstance(sticker, dict) else None
        if isinstance(info, dict) and (info.get("title") or info.get("display_artist")):
            return {"title": info.get("title") or "", "artist": info.get("display_artist") or ""}
    return None


def item_of(m):
    """One story item (a picture or a video) in our shape."""
    videos = [v for v in m.get("video_versions") or [] if isinstance(v, dict) and v.get("url")]
    found = pictures(m)
    feed = next((s for s in m.get("story_feed_media") or [] if isinstance(s, dict) and s.get("media_code")), None)
    shared = feed.get("media_code") if feed else None
    # where the shared post card sits on the story (fractions of the frame, centre point), for the «View post» bubble
    box = {k: feed.get(k) for k in ("x", "y", "width", "height", "rotation")} if feed and all(isinstance(feed.get(k), (int, float)) for k in ("x", "y", "width", "height")) else None
    flags = [name for name, key in (("poll", "story_polls"), ("question", "story_questions"), ("countdown", "story_countdowns"), ("slider", "story_sliders"),
                                     ("quiz", "story_quizs")) if m.get(key)]
    places = [pick(s, ("location", "name")) for s in m.get("story_locations") or [] if isinstance(s, dict)]
    return {
        "id": str(m.get("pk") or m.get("id") or ""), "type": "video" if videos or m.get("media_type") == 2 else "image",
        "taken_at": count_of(m.get("taken_at")), "expires_at": count_of(m.get("expiring_at")),
        "image": found[0]["url"] if found else None, "thumb": thumb_url(m), "video": videos[0]["url"] if videos else None,
        "duration": m.get("video_duration") if isinstance(m.get("video_duration"), (int, float)) else None,
        "width": m.get("original_width"), "height": m.get("original_height"), "audio": m.get("has_audio") is True,
        "music": music_of(m), "links": web_addresses(m.get("story_link_stickers")), "mentions": usernames(m.get("reel_mentions"), "user"),
        "hashtags": unique(pick(s, ("hashtag", "name")) for s in m.get("story_hashtags") or [] if isinstance(s, dict)),
        "places": unique(p for p in places if p), "shared_post": shared, "shared_box": box, "stickers": flags,
        "caption": pick(m, ("caption", "text")) or "", "alt": m.get("accessibility_caption") or None,
    }


def reels_from_docs(docs):
    """Reels found in the parsed documents (or JSON text): the person's own story ('story') and highlights ('highlight')."""
    out, seen = [], set()
    for doc in docs:
        for part in ([doc] if not isinstance(doc, str) else parse_body(doc)):
            for node in walk(part):
                if isinstance(node.get("items"), list) and "reel_type" in node:
                    ident = str(node.get("id") or "")
                    if ident in seen:
                        continue
                    seen.add(ident)
                    kind = "highlight" if node.get("reel_type") == "highlight_reel" or ident.startswith("highlight:") else "story"
                    who = node.get("user") if isinstance(node.get("user"), dict) else {}
                    out.append({"kind": kind, "id": ident.split(":", 1)[1] if ident.startswith("highlight:") else ident, "title": node.get("title") or "",
                                "user": who.get("username") or "", "user_id": str(who.get("pk") or who.get("id") or ""),
                                "latest": count_of(node.get("latest_reel_media")), "items_total": len(node["items"]),
                                "items": [item_of(i) for i in node["items"][:MAX_ITEMS] if isinstance(i, dict)]})
    return out
