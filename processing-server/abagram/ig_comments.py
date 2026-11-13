"""Comments and likers of a post: from the JSON a post page carries inside its HTML, and from Instagram's own replies
when more are asked for. Pure functions, no browser."""
import json
import re

from ig_more import walk
from ig_profile import parse_body

SCRIPT_JSON = re.compile(r'<script type="application/json"[^>]*>(.*?)</script>', re.S)


def docs_from_html(html):
    """The JSON blobs of a post page that talk about comments (the page sends them inside itself, not as a separate request)."""
    docs = []
    for blob in SCRIPT_JSON.findall(html or ""):
        if "XDTCommentDict" in blob or "comments__connection" in blob:
            try:
                docs.append(json.loads(blob))
            except ValueError:
                continue
    return docs


def comment_of(node):
    who = node.get("user") if isinstance(node.get("user"), dict) else {}
    return {"id": str(node.get("pk") or ""), "user": who.get("username") or "", "user_id": str(who.get("pk") or who.get("id") or ""),
            "verified": bool(who.get("is_verified")), "avatar": who.get("profile_pic_url"), "text": node.get("text") or "",
            "at": node.get("created_at") if isinstance(node.get("created_at"), int) else None,
            "likes": node.get("comment_like_count") if isinstance(node.get("comment_like_count"), int) else None,
            "replies": node.get("child_comment_count") if isinstance(node.get("child_comment_count"), int) else 0,
            "reply_to": str(node["parent_comment_id"]) if node.get("parent_comment_id") else None,
            "liked_by_viewer": bool(node.get("has_liked_comment")), "edited": bool(node.get("is_edited")),
            "pinned": bool(node.get("is_pinned")), "gif": bool(node.get("giphy_media_info"))}


def comments_from_docs(docs):
    """Comments in the order Instagram ranks them, each once. A document may be a parsed object or text."""
    found, seen = [], set()
    for doc in docs:
        for part in ([doc] if not isinstance(doc, str) else parse_body(doc)):
            for node in walk(part):
                if node.get("__typename") == "XDTCommentDict" and node.get("pk") and node["pk"] not in seen:
                    seen.add(node["pk"])
                    found.append(comment_of(node))
    return found


def comment_paging(docs):
    """{'more': bool, 'cursor': str|None} of the last comments connection found."""
    last = None
    for doc in docs:
        for part in ([doc] if not isinstance(doc, str) else parse_body(doc)):
            for node in walk(part):
                for key, value in node.items():
                    if key.endswith("comments__connection") and isinstance(value, dict) and isinstance(value.get("page_info"), dict):
                        last = value["page_info"]
    return {"more": bool(last and last.get("has_next_page")), "cursor": (last or {}).get("end_cursor") if last else None}


def liker_of(user):
    return {"username": user.get("username") or "", "full_name": user.get("full_name") or "", "id": str(user.get("pk") or user.get("id") or ""),
            "private": bool(user.get("is_private")), "verified": bool(user.get("is_verified")),
            "avatar": user.get("profile_pic_url"), "story_at": user.get("latest_reel_media") if isinstance(user.get("latest_reel_media"), int) and user.get("latest_reel_media") else None}


def likers_from_api(texts):
    """{'total': n, 'users': [...]} from the replies of /api/v1/media/<id>/likers/. total is Instagram's own count of all likes."""
    users, total, seen = [], None, set()
    for text in texts:
        for doc in parse_body(text):
            for node in walk(doc):
                if isinstance(node.get("users"), list) and "user_count" in node:
                    total = node["user_count"] if isinstance(node["user_count"], int) else total
                    for u in node["users"]:
                        if isinstance(u, dict) and u.get("username") and u["username"] not in seen:
                            seen.add(u["username"])
                            users.append(liker_of(u))
    return {"total": total, "users": users}
