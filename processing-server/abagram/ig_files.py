"""Pictures and videos of posts, highlights and stories kept on disk, one folder per person: files/p_<username>/<key>.<ext>.
What to fetch is decided here from the saved data (a plan: key, address, kind); the fetching is ig_media.py. No browser, no network."""
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ig_store import KEY_RE, sniff_image

TYPES = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif", ".mp4": "video/mp4"}
EXT_OF = {v: k for k, v in TYPES.items()}
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def expiry_of(url):
    """When an Instagram picture/video address stops working (its `oe` part is a hex time), or None when it has none."""
    try:
        value = parse_qs(urlparse(url or "").query).get("oe", [None])[0]
        return int(value, 16) if value else None
    except ValueError:
        return None


def sniff(head):
    """The content type of a downloaded file from its first bytes: a picture, an MP4 video, or None."""
    if head[4:8] == b"ftyp":
        return "video/mp4"
    return sniff_image(head)


def plan_posts(posts, codes=None, videos=True):
    """Every picture (and video) of the saved posts: pp_<code>_<n> for the picture of slide n, pv_<code>_<n> for its video."""
    out = []
    for post in posts or []:
        if codes and post["code"] not in codes:
            continue
        for n, item in enumerate(post.get("items") or []):
            if item.get("image"):
                out.append({"key": f"pp_{post['code']}_{n}", "url": item["image"], "type": "image", "of": post["code"]})
            if videos and item.get("video"):
                out.append({"key": f"pv_{post['code']}_{n}", "url": item["video"], "type": "video", "of": post["code"]})
    return out


def plan_reel(reel, prefix, items=None, videos=True):
    """Pictures (and videos) of a story or a highlight: <prefix>p_<item id> and <prefix>v_<item id>, all items or the chosen ones.
    prefix is 'h<highlight id>_' for a highlight and 's' for the active story."""
    out = []
    for item in (reel or {}).get("items") or []:
        if items and item["id"] not in items:
            continue
        if item.get("image"):
            out.append({"key": f"{prefix}p_{item['id']}", "url": item["image"], "type": "image", "of": reel.get("id")})
        if videos and item.get("video"):
            out.append({"key": f"{prefix}v_{item['id']}", "url": item["video"], "type": "video", "of": reel.get("id")})
    return out


class Files:
    """The downloaded files of every person."""

    def __init__(self, root):
        self.dir = Path(root) / "files"

    def folder(self, username):
        return self.dir / f"p_{username.lower()}"

    def path(self, username, key):
        """The saved file for this key (whatever its extension), or None."""
        if not KEY_RE.match(key):
            return None
        for ext in TYPES:
            path = self.folder(username) / f"{key}{ext}"
            if path.is_file():
                return path
        return None

    def partial(self, username, key):
        """Where a download is written until it is whole."""
        self.folder(username).mkdir(parents=True, exist_ok=True)
        return self.folder(username) / f"{key}.part"

    def commit(self, username, key, partial, content_type):
        """Move a finished download into place; returns the final path (an older file under the same key is replaced)."""
        final = self.folder(username) / f"{key}{EXT_OF[content_type]}"
        for ext in TYPES:
            old = self.folder(username) / f"{key}{ext}"
            if old != final and old.is_file():
                old.unlink()
        partial.replace(final)
        return final

    def listing(self, username):
        """{key: {'size', 'type', 'at'}} of what is saved for one person."""
        out = {}
        for path in sorted(self.folder(username).glob("*")) if self.folder(username).is_dir() else []:
            if path.suffix in TYPES and KEY_RE.match(path.stem):
                st = path.stat()
                out[path.stem] = {"size": st.st_size, "type": TYPES[path.suffix], "at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds")}
        return out

    def total_bytes(self):
        return sum(p.stat().st_size for p in self.dir.glob("*/*") if p.suffix in TYPES) if self.dir.is_dir() else 0
