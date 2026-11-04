"""Where a quick draft (or a range preview) is rendered: on the site (the default) or on the processing node. §23.4

The owner left this to us («خودتان تصمیم بگیرید») — so there is NO setting. The rule, in one place:

  * a draft stays on the site, which is nearly always as fast and costs no transfer;
  * it goes to the node only when ALL of these hold:
      - a node is online, ready for `edit.render` and not busy with another job;
      - the draft is heavy: the site is expected to need more than `HEAVY_SITE_SECONDS` for it (from duration, frame size and
        effects — `estimate_site_seconds`); a light draft is never worth a round trip;
      - the transfer is not the bottleneck: what the node would still have to download (the originals it does not hold yet —
        it reports a sha256 list of its cache) plus the upload of the result, plus the node's own render time, must come
        out clearly (`NODE_MARGIN`) under the site's time;
  * a node that is offline, fails, never picks the job up or does not finish in time ⇒ the site renders it, and the render
    says so (`fallback`), exactly as for a final render.

Every number below is a rough estimate measured once on the site server (a 2-vCPU VPS under normal load: 720p30 plain ≈ 0.5 s of
render per second of video; a stack of denoise + blur + sharpen + vignette + grain ≈ 3× that; a keyframed mask (geq) ≈ 8×) — they only
have to put the decision on the right side of «clearly heavy» / «clearly light». Change them HERE, nowhere else.
"""
from __future__ import annotations

import dataclasses

# ---------------------------------------------------------------- the knobs (the only place)
#: the site must be expected to need MORE than this many seconds before a node is even considered
HEAVY_SITE_SECONDS = 45.0
#: the node (an NVIDIA encoder and a desktop CPU) renders this many times faster than the site's two threads
NODE_SPEEDUP = 6.0
#: job pick-up (the node polls), file checks, the upload hand-shake
NODE_FIXED_SECONDS = 20.0
#: the node's total must be under this share of the site's time — a small win is not worth the risk of a fallback
NODE_MARGIN = 0.7
#: bytes/second the site → node line is assumed to carry (the owner's line: 15 KB/s … 3 MB/s) and the way back
LINK_DOWN_BPS = 1_500_000.0
LINK_UP_BPS = 500_000.0
#: the node gets this many times its own estimate (at least `NODE_MIN_BUDGET`, at most `NODE_MAX_BUDGET`) before the site takes over
BUDGET_FACTOR = 2.5
NODE_MIN_BUDGET = 90.0
NODE_MAX_BUDGET = 1200.0
#: a draft job the node has not picked up after this long goes back to the site (a final render waits longer)
DRAFT_QUEUE_GRACE = 30.0

# how long the site needs: seconds of render per second of video, for the reference picture (1280x720 at 30 fps)
SITE_SECONDS_PER_REF_SECOND = 0.5
REF_PIXELS_PER_SECOND = 1280 * 720 * 30
#: what a draft's file weighs per second of video at the reference picture (x264 veryfast, crf 27 ≈ 1 Mbit/s)
DRAFT_BYTES_PER_REF_SECOND = 130_000

#: extra cost, in «reference seconds» per second of clip, on top of the plain clip (decoded, scaled and encoded = 1.0)
COST = {
    "layer": 0.5,            # a clip above the base track (an overlay)
    "denoise": 0.6, "blur": 0.5, "sharpen": 0.3, "vignette": 0.2, "grain": 0.25, "color": 0.1,
    "chroma": 0.9, "lut": 0.3, "mask": 0.5, "mask_animated": 7.0, "matte": 0.8, "ramp": 0.5, "effect": 0.4,
    "keyframes": 0.3, "rotate": 0.3, "blend": 0.3, "transition": 1.0, "title": 0.3,
}
_COLOR_HEAVY = ("denoise", "blur", "sharpen", "vignette", "grain")


# ---------------------------------------------------------------- the estimate

def _clip_extra(clip, on_base: bool) -> float:
    """Extra cost per second of this clip (see COST)."""
    if getattr(clip, "kind", "") == "text":
        return COST["title"]
    extra = 0.0 if on_base else COST["layer"]
    color = getattr(clip, "color", None) or {}
    for key in _COLOR_HEAVY:
        if float(color.get(key) or 0) > 0.4:
            extra += COST[key]
    if any(k not in _COLOR_HEAVY and k != "saturation" and color.get(k) for k in color) or float(color.get("saturation", 100) or 100) != 100:
        extra += COST["color"]
    if getattr(clip, "chroma", None):
        extra += COST["chroma"]
    if getattr(clip, "lut_file", ""):
        extra += COST["lut"]
    mask = getattr(clip, "mask", None) or {}
    if mask or getattr(clip, "mask_file", ""):
        animated_mask = bool(mask.get("kf")) or (bool(mask) and bool(getattr(clip, "animated", False)))    # one `geq` video per frame
        extra += COST["mask_animated"] if animated_mask else COST["mask"]
    if getattr(clip, "matte_file", ""):
        extra += COST["matte"]
    if getattr(clip, "ramp", None) or getattr(clip, "segs", None):
        extra += COST["ramp"]
    extra += COST["effect"] * len(getattr(clip, "effects", None) or [])
    if getattr(clip, "animated", False):
        extra += COST["keyframes"]
    if getattr(clip, "rot", 0.0):
        extra += COST["rotate"]
    if getattr(clip, "blend", "normal") != "normal":
        extra += COST["blend"]
    return extra


def _units(timeline) -> float:
    """Reference seconds of work in the timeline's picture: its length (the base layer) plus each clip's extra cost for its length."""
    units = float(timeline.length)
    video = [t for t in timeline.tracks if t.kind in ("video", "text")]
    first_video = next((t for t in timeline.tracks if t.kind == "video"), None)
    for track in video:
        for clip in track.clips:
            length = float(getattr(clip, "length", None) or getattr(clip, "duration", 0.0) or 0.0)
            units += length * _clip_extra(clip, on_base=(track is first_video))
            if getattr(clip, "transition", None):
                units += COST["transition"] * float((clip.transition or {}).get("duration") or 0.5)
            nested = getattr(clip, "nested", None)
            if nested is not None:
                units += _units(nested)
    return units


def pixel_factor(width: int, height: int, fps: float) -> float:
    """How much heavier than the reference picture (1280x720 at 30 fps) this one is."""
    return max(0.1, (float(width) * float(height) * float(fps or 30)) / REF_PIXELS_PER_SECOND)


def estimate_site_seconds(timeline, *, width: int | None = None, height: int | None = None, fps: float | None = None) -> float:
    """Roughly how long the site would take to render this timeline at the given picture (default: the timeline's own)."""
    k = pixel_factor(width or timeline.width, height or timeline.height, fps or timeline.fps)
    return SITE_SECONDS_PER_REF_SECOND * k * _units(timeline)


def estimate_output_bytes(length: float, width: int, height: int, fps: float) -> int:
    """About how big the draft file is (what the node would have to upload)."""
    return int(DRAFT_BYTES_PER_REF_SECOND * pixel_factor(width, height, fps) * max(0.0, float(length)))


# ---------------------------------------------------------------- the decision

@dataclasses.dataclass
class Decision:
    where: str                       # "node" | "server"
    reason: str                      # a short code: offline | busy | light | transfer_bound | node
    site_seconds: float = 0.0
    node_seconds: float | None = None
    uncached_bytes: int = 0

    @property
    def on_node(self) -> bool:
        return self.where == "node"

    @property
    def budget(self) -> float:
        """How long the node may take before the site renders the draft after all."""
        node_s = self.node_seconds or 0.0
        return max(NODE_MIN_BUDGET, min(NODE_MAX_BUDGET, BUDGET_FACTOR * node_s))


def node_seconds(site_seconds: float, uncached_bytes: int, out_bytes: int) -> float:
    """The node's expected total: fixed overhead + download of what it lacks + its own render + upload of the result."""
    return (NODE_FIXED_SECONDS + float(uncached_bytes) / LINK_DOWN_BPS + float(site_seconds) / NODE_SPEEDUP + float(out_bytes) / LINK_UP_BPS)


def decide(site_seconds: float, *, node_online: bool, node_busy: bool = False, uncached_bytes: int = 0, out_bytes: int = 0) -> Decision:
    """Site or node for this draft? `uncached_bytes` = originals (and fonts, LUTs …) the node does not hold yet; pass the sum of
    ALL of them when the node's cache is unknown (an old agent) — the transfer then counts in full."""
    if not node_online:
        return Decision("server", "offline", site_seconds)
    if node_busy:
        return Decision("server", "busy", site_seconds)
    if site_seconds <= HEAVY_SITE_SECONDS:
        return Decision("server", "light", site_seconds)
    node_s = node_seconds(site_seconds, uncached_bytes, out_bytes)
    if node_s > NODE_MARGIN * site_seconds:
        return Decision("server", "transfer_bound", site_seconds, node_s, uncached_bytes)
    return Decision("node", "node", site_seconds, node_s, uncached_bytes)


def uncached_bytes(files: dict, node_cache) -> int:
    """Sum of the sizes of the job's files whose sha256 is not in the node's cache report (16-hex prefixes).
    `node_cache` None (the node does not report one) ⇒ everything counts."""
    have = set(node_cache or [])
    total = 0
    for meta in files.values():
        if str(meta.get("sha256", ""))[:16] not in have:
            total += int(meta.get("size") or 0)
    return total
