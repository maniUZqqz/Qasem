"""Everything saved about a person, one folder per kind (posts/, highlights/, followers/ ...) next to profiles/.
Files are named p_<username> so a username like 'con' is never a reserved device name on Windows."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from ig_profile import age_seconds, write_atomic

KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sniff_image(head):
    """The content type of an image from its first bytes; None when it does not look like one."""
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:4] == b"GIF8":
        return "image/gif"
    return None


class Section:
    """One JSON file per person for one kind of data."""

    def __init__(self, root, name):
        self.dir = Path(root) / name

    def _file(self, username):
        return self.dir / f"p_{username.lower()}.json"

    def load(self, username):
        try:
            return json.loads(self._file(username).read_text("utf-8"))
        except (OSError, ValueError):
            return None

    def save(self, username, data):
        data = dict(data, fetched_at=now_iso())
        write_atomic(self._file(username), json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"))
        return data

    def age(self, username):
        return age_seconds(self.load(username) or {})


class Media:
    """Small pictures kept next to the data (thumbnails, covers): media/p_<username>/<key>.img"""

    def __init__(self, root):
        self.dir = Path(root) / "media"

    def _file(self, username, key):
        return self.dir / f"p_{username.lower()}" / f"{key}.img"

    def put(self, username, key, data):
        if KEY_RE.match(key):
            write_atomic(self._file(username, key), data)
            return True
        return False

    def path(self, username, key):
        path = self._file(username, key) if KEY_RE.match(key) else None
        return path if path and path.exists() else None
