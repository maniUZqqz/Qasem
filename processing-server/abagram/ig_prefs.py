"""Settings the person changes in the site that the engine itself reads (data/settings.json)."""
import json
import re

from ig_common import DATA
from ig_profile import read_json, write_atomic

PROXY_RE = re.compile(r"^(https?|socks5)://[^\s]+$")   # e.g. socks5://127.0.0.1:1080 or http://user:pass@host:port

FILE = DATA / "settings.json"
SHARE_MAX = 50   # «تقسیم کار» (ig_share): at most this many systems
DEFAULTS = {"show_browser": False,   # Chromium works without a window unless he turns it on
            "proxy": "",                 # Instagram is filtered in Iran: a proxy the browser uses even when the system VPN is off
            "share_index": 1,            # «تقسیم کار»: this copy is system share_index of share_count (1 of 1: no split)
            "share_count": 1}


def load():
    saved = read_json(FILE, {}, backup=True)   # a damaged file must not quietly turn «تقسیم کار» back into "1 of 1"
    if not isinstance(saved, dict):
        saved = {}
    return {k: saved.get(k, v) if isinstance(saved.get(k, v), type(v)) else v for k, v in DEFAULTS.items()}


def valid(values):
    """Field names of the given settings that are malformed: the proxy, or a split that cannot be (system 3 of 2)."""
    bad = []
    if isinstance(values.get("proxy"), str) and values["proxy"].strip() and not PROXY_RE.match(values["proxy"].strip()):
        bad.append("proxy")
    share = [k for k in ("share_index", "share_count") if k in values]
    if share:
        if any(type(values[k]) is not int for k in share):   # a bool is an int to Python: not here
            return bad + [k for k in share if type(values[k]) is not int]
        merged = {**load(), **{k: values[k] for k in share}}
        if not 1 <= merged["share_count"] <= SHARE_MAX:
            bad.append("share_count")
        elif not 1 <= merged["share_index"] <= merged["share_count"]:
            bad.append("share_index")
    return bad


def save(values):
    values = {**values, "proxy": values["proxy"].strip()} if isinstance(values.get("proxy"), str) else values
    merged = {**load(), **{k: v for k, v in values.items() if k in DEFAULTS and isinstance(v, type(DEFAULTS[k]))}}
    DATA.mkdir(parents=True, exist_ok=True)
    write_atomic(FILE, json.dumps(merged).encode("utf-8"), backup=True)
    return merged
