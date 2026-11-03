"""Keyframes: easing, evaluation, and ffmpeg expressions.

A property that animates is a list of keys ``{"t": seconds, "v": value, "e": easing}`` — ``t`` counts from the clip's
own start ON THE TIMELINE (so moving the clip moves its animation), ``e`` is the easing of the segment that LEAVES the
key. The browser evaluates the same maths (`keyframes.ts`) so the instant preview and the render agree:

    u = (t - t0) / (t1 - t0)
    linear       E(u) = u
    ease_in      E(u) = u²
    ease_out     E(u) = u (2 - u)
    ease_in_out  E(u) = u² (3 - 2u)          (smoothstep)
    hold         E(u) = 0                    (the value stays until the next key, then jumps)
    value(t) = v0 + (v1 - v0) E(u)           before the first key: v_first, after the last: v_last

`expr` renders that as one ffmpeg expression of a time variable (`t` for overlay/scale/rotate/volume, `T` for geq), so
a moving title or a fading logo is one filter option, not a frame-by-frame bake.
"""
from __future__ import annotations

EASINGS = ("linear", "ease_in", "ease_out", "ease_in_out", "hold")
MAX_KEYS = 24

EASING_TITLES = {
    "linear": "خطی", "ease_in": "شروعِ آرام", "ease_out": "پایانِ آرام", "ease_in_out": "آرام در دو سو", "hold": "ثابت (پرش)",
}


def ease(kind: str, u: float) -> float:
    u = 0.0 if u < 0 else 1.0 if u > 1 else u
    if kind == "ease_in":
        return u * u
    if kind == "ease_out":
        return u * (2 - u)
    if kind == "ease_in_out":
        return u * u * (3 - 2 * u)
    if kind == "hold":
        return 0.0
    return u


def clean_keys(raw, lo: float, hi: float, *, max_t: float = 86400.0) -> list[dict]:
    """Browser JSON → sorted, clamped, de-duplicated keys (≤ MAX_KEYS). Anything malformed is dropped, never raised."""
    keys: list[dict] = []
    for item in (raw if isinstance(raw, list) else [])[: MAX_KEYS * 2]:
        if not isinstance(item, dict):
            continue
        try:
            t = float(item.get("t"))
            v = float(item.get("v"))
        except (TypeError, ValueError):
            continue
        if t != t or v != v or abs(t) > max_t:
            continue
        e = str(item.get("e") or "linear")
        keys.append({"t": round(max(0.0, t), 3), "v": round(max(lo, min(hi, v)), 4), "e": e if e in EASINGS else "linear"})
    keys.sort(key=lambda k: k["t"])
    out: list[dict] = []
    for k in keys:
        if out and abs(out[-1]["t"] - k["t"]) < 0.001:
            out[-1] = k
        else:
            out.append(k)
    return out[:MAX_KEYS]


def value_at(keys: list[dict], t: float, default: float) -> float:
    if not keys:
        return default
    if t <= keys[0]["t"]:
        return keys[0]["v"]
    for a, b in zip(keys, keys[1:]):
        if t < b["t"]:
            u = (t - a["t"]) / max(1e-9, b["t"] - a["t"])
            return a["v"] + (b["v"] - a["v"]) * ease(a["e"], u)
    return keys[-1]["v"]


def _n(value: float) -> str:
    text = f"{float(value):.5f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def expr(keys: list[dict], default: float, var: str = "t") -> str:
    """The ffmpeg expression of `value_at` in the time variable `var` (e.g. ``t`` or ``(t-3.2)``)."""
    if not keys:
        return _n(default)
    if len(keys) == 1:
        return _n(keys[0]["v"])
    segments = []
    for a, b in zip(keys, keys[1:]):
        span = max(1e-6, b["t"] - a["t"])
        u = f"(({var})-{_n(a['t'])})/{_n(span)}"
        e = a["e"]
        if e == "hold" or abs(b["v"] - a["v"]) < 1e-9:
            seg = _n(a["v"])
        else:
            curve = {
                "linear": u,
                "ease_in": f"({u})*({u})",
                "ease_out": f"({u})*(2-({u}))",
                "ease_in_out": f"({u})*({u})*(3-2*({u}))",
            }[e]
            seg = f"{_n(a['v'])}+({_n(b['v'] - a['v'])})*({curve})"
        segments.append((b["t"], seg))
    out = _n(keys[-1]["v"])
    for end_t, seg in reversed(segments):
        out = f"if(lt(({var}),{_n(end_t)}),{seg},{out})"
    # before the first key the value is the first key's
    return f"if(lt(({var}),{_n(keys[0]['t'])}),{_n(keys[0]['v'])},{out})"


def shifted(keys: list[dict], dt: float) -> list[dict]:
    """Keys moved by `dt` seconds (used when a clip is cut at the head: its animation must stay where it was)."""
    return [{**k, "t": round(k["t"] + dt, 3)} for k in keys]


def sliced(keys: list[dict], t0: float, t1: float) -> list[dict]:
    """Keys re-based so t=0 is the old `t0`. The cut part keeps its exact values: the edges get keys of their own, and an
    eased segment that is cut in the middle is re-sampled (a handful of linear keys follow the original curve closely)."""
    if not keys:
        return []
    pts: list[tuple[float, float, str]] = []

    def edge(t: float, kind: str) -> None:
        pts.append((t, value_at(keys, t, keys[0]["v"]), kind))

    def run(a: float, b: float, kind: str) -> None:
        """Samples of one original segment between a and b (exclusive of a, inclusive of b)."""
        if kind in ("linear", "hold") or b - a < 0.05:
            return
        for i in range(1, 6):
            t = a + (b - a) * i / 6
            pts.append((t, value_at(keys, t, keys[0]["v"]), "linear"))

    edge(t0, _inherit_ease(keys, t0))
    inner = [k for k in keys if t0 < k["t"] < t1]
    # the part of the segment that starts before t0 and ends at the first inner key (or at t1)
    first_end = inner[0]["t"] if inner else t1
    prev = [k for k in keys if k["t"] <= t0]
    if prev and _inherit_ease(keys, t0) not in ("linear", "hold"):
        pts[0] = (t0, pts[0][1], "linear")
        run(t0, first_end, prev[-1]["e"])
    for i, k in enumerate(inner):
        pts.append((k["t"], k["v"], k["e"]))
        nxt = inner[i + 1]["t"] if i + 1 < len(inner) else t1
        if i + 1 == len(inner) and k["e"] not in ("linear", "hold"):
            pts[-1] = (k["t"], k["v"], "linear")
            run(k["t"], nxt, k["e"])
    pts.append((t1, value_at(keys, t1, keys[-1]["v"]), "linear"))
    out = [{"t": round(t - t0, 3), "v": round(v, 4), "e": e} for t, v, e in sorted(pts, key=lambda p: p[0])]
    return out[:MAX_KEYS]


def _inherit_ease(keys: list[dict], t: float) -> str:
    prev = [k for k in keys if k["t"] <= t]
    return prev[-1]["e"] if prev else "linear"
