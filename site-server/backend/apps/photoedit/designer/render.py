"""از «حالتِ ادیتور» (همان JSON ِ پروژه) به کارهای سرورِ سایت و تصویر.

``state_ops`` همتای پایتونیِ ``buildProOperations`` ِ مرورگر (حالتِ «ساختِ سریع») است؛ پس پیش‌نمایشِ طراح و خروجیِ «ساخت»
یک خط‌لوله دارند. ترتیب همان ``catalog.SERVER_ORDER_V2`` است: develop ⇐ rotate ⇐ crop_rect ⇐ crop_format ⇐ رنگ ⇐ compose ⇐ resize ⇐ export.
"""
from __future__ import annotations

import io

from PIL import Image

from .. import catalog, layers as layers_mod, ops, services

FULL = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
TONE_KEYS = ("auto_tone", "look", "color")
PREVIEW_SIDE = 1280


def default_state() -> dict:
    return {"fv": 2, "turn": 0, "straighten": 0, "flipH": False, "flipV": False, "crop": dict(FULL), "adjust": {}, "curve": {},
            "spots": [], "tools": {}, "kitAuto": False, "out": {"format": "jpeg", "quality": 92, "max_kb": 0, "long_edge": 0},
            "layers": [{"id": "base", "type": "base", "name": "عکس", "visible": True, "locked": False, "opacity": 1,
                        "blend": "normal", "mask": None}], "persp": None}


def _is_full(c) -> bool:
    return c["x"] <= 0.0005 and c["y"] <= 0.0005 and c["w"] >= 0.9995 and c["h"] >= 0.9995


def has_overlays(state: dict) -> bool:
    ls = state.get("layers") or []
    return any(l.get("type") != "base" for l in ls) or any(
        l.get("type") == "base" and (l.get("mask") or l.get("opacity", 1) < 1 or l.get("blend", "normal") != "normal"
                                    or not l.get("visible", True)) for l in ls)


def state_ops(state: dict, project_id: int = 0, part: str = "all") -> list[dict]:
    """part: «pre» (تا پیش از compose)، «post» (compose و بعدش)، «all». کارها هنوز وارسی نشده‌اند (normalize_operations)."""
    out: list[dict] = []

    def add(tool, params):
        out.append({"tool": tool, "params": params})

    adjust, curve = state.get("adjust") or {}, state.get("curve") or {}
    if part in ("pre", "all"):
        if adjust or curve or state.get("spots"):
            add("develop", {"adjust": adjust, "curve": curve, "spots": state.get("spots") or []})
        if state.get("turn") or state.get("straighten") or state.get("flipH") or state.get("flipV"):
            add("rotate", {"turn": str(state.get("turn") or 0), "straighten": state.get("straighten") or 0,
                           "flip_h": bool(state.get("flipH")), "flip_v": bool(state.get("flipV"))})
        c = state.get("crop") or FULL
        if not _is_full(c):
            r = lambda v: round(v * 1000) / 10  # noqa: E731
            add("crop_rect", {"x": r(c["x"]), "y": r(c["y"]), "w": r(c["w"]), "h": r(c["h"])})
        tools = state.get("tools") or {}
        if tools.get("crop_format"):
            add("crop_format", tools["crop_format"])
        for k in TONE_KEYS:
            if tools.get(k):
                add(k, tools[k])
    if part in ("post", "all"):
        if has_overlays(state):
            add("compose", {"project": project_id, "layers": state["layers"]})
        o = state.get("out") or {}
        if o.get("long_edge"):
            add("resize", {"long_edge": o["long_edge"]})
    if part == "all":
        o = state.get("out") or {}
        add("export", {"format": o.get("format", "jpeg"), "quality": o.get("quality", 92), "max_kb": o.get("max_kb", 0)})
    return out


def normalized(state: dict, project_id: int = 0, part: str = "all", store=None) -> list[dict]:
    clean = catalog.normalize_operations(state_ops(state, project_id, part))
    if store is not None:
        for o in clean:
            if o["tool"] == "compose":
                layers_mod.normalize_layers(o["params"]["layers"], store=store, base="one")
    return clean


def source_image(asset) -> Image.Image:
    img = services.preview_source(asset)
    img.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE), Image.Resampling.LANCZOS)
    return img


def _ctx(asset, img: Image.Image) -> dict:
    ctx = services.server_ctx(asset.store)
    ctx["scale"] = (img.width / asset.width) if asset.width else 1.0
    return ctx


def render_frame(asset, state: dict, src: Image.Image | None = None) -> tuple[Image.Image, list[str]]:
    """بومِ نهایی بی لایه‌ها (همان ورودیِ compose) ⇒ (تصویر، یادداشت‌ها)."""
    img = (src or source_image(asset)).copy()
    ctx = _ctx(asset, img)
    pre = normalized(state, 0, "pre")
    out, _ = ops.run(img, [o for o in pre if o["tool"] != "export"], ctx)
    return out, ctx["notes"]


def compose_layers(asset, frame: Image.Image, layers: list[dict], project_id: int = 0) -> tuple[Image.Image, list[str]]:
    """لایه‌ها روی بومِ قاب‌شده ⇒ (تصویر، یادداشت‌ها). ``layers`` باید یک لایهٔ base داشته باشد."""
    ctx = services.server_ctx(asset.store)
    ctx["scale"] = (frame.width / asset.width) if asset.width else 1.0
    norm = layers_mod.normalize_layers(layers, store=asset.store, base="one")
    out = layers_mod.compose(frame, norm, ctx, project=project_id)
    return out, ctx["notes"]


def render_state(asset, state: dict, frame: Image.Image | None = None) -> tuple[Image.Image, Image.Image, list[str]]:
    """⇒ (نتیجه، بومِ قاب‌شده، یادداشت‌ها)."""
    notes: list[str] = []
    if frame is None:
        frame, n1 = render_frame(asset, state)
        notes += n1
    if has_overlays(state):
        out, n2 = compose_layers(asset, frame, state["layers"])
        notes += n2
    else:
        out = frame
    return out, frame, notes


def to_jpeg(img: Image.Image, quality: int = 86, max_side: int = PREVIEW_SIDE) -> bytes:
    return ops.jpeg_bytes(img, max_side, quality)


def to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
