"""Timeline operations on the project JSON — the Python twin of `frontend/.../manual/model.ts`.

The manual editor edits a project in the browser; the director edits the SAME JSON on the server, so what the AI builds is an
ordinary, fully editable project (never a flattened render). These are the pure helpers; `tools.py` composes them into the
catalogue's tools. A project is a plain `dict`; helpers mutate it in place and return what they made.

Layer order follows the panel: `tracks` is bottom → top; the first video track is the «main» one.
"""
from __future__ import annotations

import copy
import itertools
from typing import Iterable

from .. import timeline as tl

PRESETS = {
    "reel": {"width": 1080, "height": 1920, "fps": 30},
    "feed": {"width": 1080, "height": 1350, "fps": 30},
    "square": {"width": 1080, "height": 1080, "fps": 30},
    "wide": {"width": 1920, "height": 1080, "fps": 30},
}
EPS = 0.001
MIN_LEN = 0.1

_COUNTER = itertools.count(1)


def uid(project: dict | None = None, prefix: str = "c") -> str:
    """A short id unique inside the project (the browser's ids look like `c1k2x3a`; any unique string is valid)."""
    used = ids_of(project) if project is not None else set()
    while True:
        cand = f"{prefix}d{next(_COUNTER):x}"
        if cand not in used:
            return cand


def ids_of(project: dict) -> set[str]:
    out = {t.get("id") for t in project.get("tracks", [])}
    for t in project.get("tracks", []):
        out |= {c.get("id") for c in t.get("clips", [])}
    return out


def new_project(preset: str = "reel", fps: int | None = None) -> dict:
    f = PRESETS.get(preset, PRESETS["reel"])
    p = {"format": {"width": f["width"], "height": f["height"], "fps": fps or f["fps"], "preset": preset if preset in PRESETS else "reel"},
         "tracks": [], "global_ops": [], "markers": [], "inout": None}
    add_track(p, "video", name="تصویر ۱")
    add_track(p, "video", name="تصویر ۲")
    add_track(p, "text", name="متن")
    add_track(p, "audio", name="گفتار", role="speech")
    add_track(p, "audio", name="موسیقی", role="music")
    return p


def set_format(project: dict, preset: str, fps: int | None = None) -> None:
    f = PRESETS[preset]
    project["format"] = {"width": f["width"], "height": f["height"], "fps": fps or project.get("format", {}).get("fps", 30) or 30,
                         "preset": preset}


def add_track(project: dict, kind: str, *, name: str | None = None, role: str = "", at_end: bool | None = None) -> dict:
    n = sum(1 for t in project["tracks"] if t["kind"] == kind) + 1
    default = {"video": f"تصویر {n}", "audio": f"صدا {n}", "text": f"متن {n}"}[kind]
    track = {"id": uid(project, "t"), "kind": kind, "name": name or default, "muted": False, "locked": False, "clips": []}
    if role:
        track["role"] = role
    tracks = project["tracks"]
    kinds = [t["kind"] for t in tracks]
    if kind == "audio" or at_end:
        tracks.append(track)
    elif kind == "video":
        tracks.insert(max(i for i, k in enumerate(kinds) if k == "video") + 1 if "video" in kinds else 0, track)
    else:  # text above the picture
        last = max([i for i, k in enumerate(kinds) if k in ("video", "text")] or [-1])
        tracks.insert(last + 1, track)
    return track


def video_tracks(project: dict) -> list[dict]:
    return [t for t in project["tracks"] if t["kind"] == "video"]


def main_track(project: dict) -> dict:
    vt = video_tracks(project)
    return vt[0] if vt else add_track(project, "video")


def overlay_track(project: dict) -> dict:
    vt = video_tracks(project)
    return vt[1] if len(vt) > 1 else add_track(project, "video")


def text_track(project: dict, *, caption: bool = False) -> dict:
    for t in project["tracks"]:
        if t["kind"] == "text" and bool(t.get("caption")) == caption:
            return t
    t = add_track(project, "text", name="زیرنویس" if caption else None)
    if caption:
        t["caption"] = True
    return t


def audio_track(project: dict, role: str) -> dict:
    for t in project["tracks"]:
        if t["kind"] == "audio" and t.get("role") == role:
            return t
    names = {"speech": "گفتار", "music": "موسیقی", "sfx": "جلوه"}
    return add_track(project, "audio", name=names.get(role), role=role)


# ----------------------------------------------------------------------------- timing


def ramp_len(c: dict) -> float:
    ramp = c.get("ramp") or []
    speeds = tl.ramp_speeds(ramp) if len(ramp) >= 2 else []
    span = float(c["end"]) - float(c["start"])
    if len(speeds) >= 2:
        step = span / len(speeds)
        return max(0.04, sum(step / v for v in speeds))
    return span / (float(c.get("speed") or 1) or 1)


def clip_length(c: dict) -> float:
    if c.get("type") == "text":
        return float(c.get("duration") or 0)
    if c.get("freeze") or c.get("kind") == "image":
        return max(0.04, float(c["end"]) - float(c["start"]))
    return max(0.04, ramp_len(c))


def clip_end(c: dict) -> float:
    return float(c["at"]) + clip_length(c)


def project_length(project: dict) -> float:
    return max([clip_end(c) for t in project["tracks"] for c in t["clips"]] or [0.0])


def find(project: dict, cid: str):
    for t in project["tracks"]:
        for c in t["clips"]:
            if c.get("id") == cid:
                return t, c
    return None


def sort_track(track: dict) -> None:
    track["clips"].sort(key=lambda c: float(c["at"]))


def overlaps(track: dict, at: float, length: float, ignore: Iterable[str] = ()) -> bool:
    skip = set(ignore)
    return any(c["id"] not in skip and at < clip_end(c) - EPS and at + length > float(c["at"]) + EPS for c in track["clips"])


def free_spot(track: dict, at: float, length: float, ignore: Iterable[str] = ()) -> float:
    """`at` when free, else the nearest gap that fits (before or after the clashing clips)."""
    at = max(0.0, at)
    if not overlaps(track, at, length, ignore):
        return at
    skip = set(ignore)
    cands = [0.0]
    for c in track["clips"]:
        if c["id"] in skip:
            continue
        cands += [clip_end(c), float(c["at"]) - length]
    for x in sorted((x for x in cands if x >= 0), key=lambda x: abs(x - at)):
        if not overlaps(track, x, length, ignore):
            return x
    return max([clip_end(c) for c in track["clips"]] or [0.0])


def end_of(track: dict) -> float:
    return max([clip_end(c) for c in track["clips"]] or [0.0])


# ----------------------------------------------------------------------------- clips


def media_clip(project: dict, item: dict, at: float, *, start: float = 0.0, end: float | None = None, label: str | None = None,
               kind: str | None = None, cid: str | None = None) -> dict:
    """A fresh clip for a media item (`describe` output): defaults identical to the browser's `newMediaClip`."""
    k = kind or item.get("kind") or "video"
    dur = float(item.get("duration") or 0)
    if k == "image":
        end = float(end) if end is not None else 5.0
        src = 0
    else:
        if end is None:
            end = dur or 5.0
        end = min(float(end), dur) if dur else float(end)
        src = dur
    return {
        "id": cid or uid(project), "type": "media", "ref": item["ref"], "label": (label or item.get("title") or "")[:60],
        "kind": k, "at": round(float(at), 3), "start": round(float(start), 3), "end": round(float(end), 3), "src": src,
        "opacity": 1, "x": 0, "y": 0, "width": 1, "height": 1, "volume": 1, "speed": 1, "fit": "cover", "fade_in": 0, "fade_out": 0,
        "audio_on": True, "has_audio": bool(item.get("has_audio")), "effects": [], "transition": None,
    }


def text_clip(project: dict, text: str, at: float, duration: float, **extra) -> dict:
    c = {"id": uid(project, "x"), "type": "text", "text": text, "at": round(float(at), 3), "duration": round(float(duration), 3),
         "position": "bottom", "size": 6, "color": "#ffffff", "box": True, "opacity": 1, "label": text[:20]}
    c.update({k: v for k, v in extra.items() if v is not None})
    return c


def place(track: dict, clip: dict, *, exact: bool = False) -> dict:
    """Put the clip on the track; on a clash move it to the nearest free spot (unless `exact`: caller guarantees)."""
    if not exact:
        clip["at"] = round(free_spot(track, float(clip["at"]), clip_length(clip), (clip["id"],)), 3)
    track["clips"].append(clip)
    sort_track(track)
    return clip


def place_free(project: dict, kind: str, clip: dict, *, role: str = "", caption: bool = False) -> dict:
    """Put `clip` on the first track of its kind that is free at that time, adding a new track when every one is busy
    (two titles at once, two stickers at once and two sound effects at once need their own tracks — the renderer refuses
    overlaps on one track). For video the main track is never used. Returns the track."""
    length = clip_length(clip)
    cands = [t for t in project["tracks"] if t["kind"] == kind and not t.get("locked")]
    if kind == "audio":
        cands = [t for t in cands if t.get("role", "") == role]
    elif kind == "text":
        cands = [t for t in cands if bool(t.get("caption")) == caption]
    elif kind == "video":
        cands = [t for t in cands if t is not main_track(project)]
    for t in cands:
        if not overlaps(t, float(clip["at"]), length, (clip["id"],)):
            t["clips"].append(clip)
            sort_track(t)
            return t
    t = add_track(project, kind, role=role if kind == "audio" else "")
    if kind == "text" and caption:
        t["caption"] = True
        t["name"] = "زیرنویس"
    t["clips"].append(clip)
    return t


# ----------------------------------------------------------------------------- trimming and cutting


def trim(project: dict, cid: str, *, start: float | None = None, end: float | None = None) -> bool:
    """Set the SOURCE in/out of a clip (a clip's timeline start stays). Clamped to the source and to MIN_LEN."""
    f = find(project, cid)
    if not f:
        return False
    _, c = f
    if c.get("type") == "text":
        if end is not None:
            c["duration"] = round(max(MIN_LEN, float(end) - float(c["at"])), 3)
        return True
    s = float(c["start"]) if start is None else max(0.0, float(start))
    e = float(c["end"]) if end is None else float(end)
    if c.get("src") and c.get("kind") != "image":
        e = min(e, float(c["src"]))
    if e < s + MIN_LEN:
        e = s + MIN_LEN
    c["start"], c["end"] = round(s, 3), round(e, 3)
    return True


def _src_time_at(c: dict, t: float) -> float:
    """Source second shown at timeline time `t` (speed and reverse followed; ramp approximated by its mean speed)."""
    if c.get("freeze"):
        return float(c["start"])
    L = clip_length(c)
    local = max(0.0, min(L, t - float(c["at"])))
    if c.get("reverse"):
        local = L - local
    span = float(c["end"]) - float(c["start"])
    return float(c["start"]) + (local / L) * span if L > 0 else float(c["start"])


def split(project: dict, cid: str, t: float, links: dict | None = None) -> str | None:
    """Cut one clip at timeline time `t`; returns the id of the RIGHT half (the left keeps `cid`)."""
    f = find(project, cid)
    if not f:
        return None
    track, c = f
    if t <= float(c["at"]) + 0.05 or t >= clip_end(c) - 0.05:
        return None
    right = copy.deepcopy(c)
    right["id"] = uid(project, "c" if c.get("type") == "media" else "x")
    right["at"] = round(t, 3)
    if c.get("type") == "text":
        lt = t - float(c["at"])
        right["duration"] = round(float(c["duration"]) - lt, 3)
        c["duration"] = round(lt, 3)
    else:
        s = _src_time_at(c, t)
        if c.get("reverse"):
            right["end"], c["start"] = round(s, 3), round(s, 3)
        else:
            right["start"], c["end"] = round(s, 3), round(s, 3)
        c["fade_out"], right["fade_in"], right["transition"] = 0, 0, None
        old = c.get("link")
        if old and links is not None:
            links.setdefault(old, uid(project, "L"))
            right["link"] = links[old]
        else:
            right.pop("link", None)
    track["clips"].append(right)
    sort_track(track)
    return right["id"]


def split_all(project: dict, ids: list[str], t: float) -> list[str]:
    links: dict = {}
    made = []
    for cid in ids:
        r = split(project, cid, t, links)
        if r:
            made.append(r)
    return made


def linked_ids(project: dict, ids: Iterable[str]) -> list[str]:
    ids = list(ids)
    links = set()
    allc = [c for t in project["tracks"] for c in t["clips"]]
    for c in allc:
        if c.get("id") in ids and c.get("link"):
            links.add(c["link"])
    out = list(ids)
    for c in allc:
        if c.get("link") in links and c["id"] not in out:
            out.append(c["id"])
    return out


def linked_ids_clips(project: dict, ids: Iterable[str]) -> list[dict]:
    keep = set(linked_ids(project, ids))
    return [c for t in project["tracks"] for c in t["clips"] if c["id"] in keep]


def delete_clips(project: dict, ids: Iterable[str], ripple: bool = False) -> int:
    gone = set(linked_ids(project, ids))
    removed = []
    for t in project["tracks"]:
        keep = []
        for c in t["clips"]:
            if c["id"] in gone:
                removed.append((t["id"], float(c["at"]), clip_length(c)))
            else:
                keep.append(c)
        t["clips"] = keep
    if ripple:
        for tid, at, length in sorted(removed, key=lambda r: -r[1]):
            for t in project["tracks"]:
                if t["id"] == tid:
                    for c in t["clips"]:
                        if float(c["at"]) >= at - EPS:
                            c["at"] = round(max(0.0, float(c["at"]) - length), 3)
    return len(removed)


def remove_range(project: dict, a: float, b: float, ripple: bool = True, only_tracks: Iterable[str] | None = None) -> int:
    """Lift [a, b) out of every unlocked track (or only `only_tracks`); with `ripple` close the gap on those tracks."""
    if b <= a + 0.02:
        return 0
    only = set(only_tracks) if only_tracks is not None else None
    tracks = [t for t in project["tracks"] if not t.get("locked") and (only is None or t["id"] in only)]
    links: dict = {}
    for at in (a, b):
        for t in tracks:
            for c in list(t["clips"]):
                if float(c["at"]) < at - 0.05 and clip_end(c) > at + 0.05:
                    split(project, c["id"], at, links)
    gone = {c["id"] for t in tracks for c in t["clips"] if float(c["at"]) >= a - 0.02 and clip_end(c) <= b + 0.02}
    n = 0
    for t in tracks:
        before = len(t["clips"])
        t["clips"] = [c for c in t["clips"] if c["id"] not in gone]
        n += before - len(t["clips"])
    if ripple:
        d = b - a
        for t in tracks:
            for c in t["clips"]:
                if float(c["at"]) >= b - 0.02:
                    c["at"] = round(max(0.0, float(c["at"]) - d), 3)
    return n


def close_gaps(track: dict, start_at: float = 0.0) -> None:
    """Butt every clip of the track against the previous one (keeping order)."""
    sort_track(track)
    cur = start_at
    for c in track["clips"]:
        c["at"] = round(cur, 3)
        cur = clip_end(c)


def set_speed(c: dict, speed: float) -> None:
    c["speed"] = round(max(0.25, min(4.0, speed)), 3)
    c["ramp"] = []


def timeline_to_source(c: dict, t: float) -> float:
    return _src_time_at(c, t)


def source_to_timeline(c: dict, s: float) -> float:
    span = float(c["end"]) - float(c["start"])
    if span <= 0:
        return float(c["at"])
    frac = (s - float(c["start"])) / span
    if c.get("reverse"):
        frac = 1 - frac
    return float(c["at"]) + frac * clip_length(c)


# ----------------------------------------------------------------------------- keyframes


def key(t: float, v: float, e: str = "linear") -> dict:
    return {"t": round(float(t), 3), "v": round(float(v), 4), "e": e}


def set_keys(c: dict, channel: str, keys: list[dict]) -> None:
    kf = c.setdefault("kf", {})
    if keys:
        kf[channel] = sorted(keys, key=lambda k: k["t"])
    else:
        kf.pop(channel, None)


def summary(project: dict) -> dict:
    """A tiny, model-friendly picture of the project (used in prompts and critiques)."""
    out = {"format": project.get("format"), "length": round(project_length(project), 2), "tracks": []}
    for t in project["tracks"]:
        out["tracks"].append({
            "id": t["id"], "kind": t["kind"], "role": t.get("role", ""), "name": t.get("name", ""), "clips": [
                {"id": c["id"], "at": round(float(c["at"]), 2), "len": round(clip_length(c), 2),
                 **({"ref": c["ref"], "start": round(float(c["start"]), 2), "end": round(float(c["end"]), 2)} if c.get("type") == "media" else {"text": c.get("text", "")[:40]})}
                for c in t["clips"][:40]],
        })
    return out
