"""ساختنِ تصویر از سندِ شخصیت: پست/استوری، استیکر، SVG، بررسیِ رنگ و شبکهٔ «همهٔ ژست‌ها × اندازه‌ها».

سبک‌های برداری از ``figure`` می‌آیند و سبکِ آدمک‌چوبی از موتورِ ماسکوت؛ هر دو از همان ``compose`` (پس‌زمینه، حباب، کپشن، اندازه‌ها) می‌گذرند.
همه‌چیز خالص است: دیتابیس، GPU و هوش مصنوعی نمی‌خواهد.
"""
from __future__ import annotations

import time

from PIL import Image

from apps.mascot.engine import compose, poses, qa, scenes
from apps.mascot.engine import spec as MS

from . import doc as D
from . import figure as F
from . import vector as V

SIZE_KEYS = tuple(compose.SIZES)
VECTOR_STYLES = F.STYLE_KEYS


def actor_spec(doc: dict) -> dict:
    """سبکِ برداری ⇒ همان سند (موتورِ برداری می‌شناسدش)؛ آدمک‌چوبی ⇒ spec ِ ماسکوت."""
    d = D.normalize(doc)
    return d if d["style"] in VECTOR_STYLES else D.to_mascot_spec(d)


def actor(doc: dict, *, pose: str = "stand", expression: str = "happy", flip: bool = False, prop: str | None = None, **kw) -> dict:
    return {"spec": actor_spec(doc), "pose": pose, "expression": expression, "flip": flip, "prop": prop, **kw}


def scene(doc: dict, opts: dict, brand: list[str], *, scale: float = 1.0) -> dict:
    """``opts`` همان خروجیِ ``mascot.services.clean_options`` است."""
    w0, h0 = compose.size_of(opts["size"])
    sc: dict = {"size": opts["size"], "brand": brand, "position": opts["position"],
                "background": {"color": opts["background"]} if str(opts["background"]).startswith("#") else opts["background"],
                "actors": [actor(doc, pose=opts["pose"], expression=opts["expression"], flip=opts["flip"], prop=None if opts["prop"] == "auto" else opts["prop"])]}
    if scale != 1.0:
        sc["width"], sc["height"] = max(120, round(w0 * scale)), max(120, round(h0 * scale))
    if opts.get("bubble"):
        sc["bubbles"] = [{"actor": 0, **opts["bubble"]}]
    if opts.get("caption"):
        sc["caption"] = dict(opts["caption"])
    return sc


def still(doc: dict, opts: dict, brand: list[str], logo: Image.Image | None, *, scale: float = 1.0) -> tuple[Image.Image, dict]:
    return compose.compose_still(scene(doc, opts, brand, scale=scale), logo=logo)


def logo_for(doc: dict, logo: Image.Image | None) -> Image.Image | None:
    return logo if D.normalize(doc)["logo"] == "chest" else None


def sticker(doc: dict, *, pose: str = "thumbs_up", expression: str = "happy", prop: str | None = None, flip: bool = False, logo: Image.Image | None = None,
            crop: str = "full", height_px: int = 1500) -> tuple[Image.Image, dict]:
    return compose.sticker(actor_spec(doc), pose=pose, expression=expression, prop=prop, flip=flip, logo=logo_for(doc, logo), crop=crop, height_px=height_px)


def qa_shot(doc: dict, *, pose: str = "stand", expression: str = "happy", prop: str | None = None, flip: bool = False, logo: Image.Image | None = None):
    return compose.qa_layer(actor(doc, pose=pose, expression=expression, flip=flip, prop=prop), logo=logo_for(doc, logo))


def check_one(doc: dict, *, pose: str = "stand", expression: str = "happy", logo: Image.Image | None = None, flip: bool = False) -> dict:
    d = D.normalize(doc)
    shot = qa_shot(d, pose=pose, expression=expression, logo=logo, flip=flip)
    return qa.check_figure(shot.layer, D.palette(d))


def qa_public(res: dict) -> dict:
    return {"ok": res["ok"], "score": res["palette_score"], "colours": [{**{k: c.get(k) for k in ("role", "hex", "name", "found", "share")}, "name_fa": MS.fa_word(c.get("name") or "")} for c in res["colours"]],
            "notes": [qa.note_fa(n) for n in res["notes"]], "scope": res.get("scope", "figure")}


MIN_PX = 0.5


def canvas_for(size: str, min_px: float = MIN_PX) -> tuple[int, int]:
    w0, h0 = compose.size_of(size)
    frac = compose.SIZES[size]["figure"]["height"]
    h = min(h0, max(160, round(min_px * 900 / frac)))
    return max(120, round(h * w0 / h0)), h


def grid(doc: dict, *, logo: Image.Image | None = None, pose_list: list[str] | None = None, sizes: tuple[str, ...] | None = None, min_px: float = MIN_PX,
         expression: str = "happy", flip: bool = False) -> dict:
    """هر ژست × هر اندازه (چیدمانِ واقعیِ آن اندازه): شخصیت خالی نیست و همهٔ رنگ‌های امضا (کلیدِ رنگ) دیده می‌شوند."""
    t0 = time.time()
    d = D.normalize(doc)
    pal = D.palette(d)
    spec = actor_spec(d)
    lg = logo_for(d, logo)
    pose_list = list(pose_list or poses.names())
    sizes = tuple(sizes or SIZE_KEYS)
    failed, total = [], 0
    for size in sizes:
        w, h = canvas_for(size, min_px)
        base = compose.actor_defaults(size)
        for pz in pose_list:
            total += 1
            shot = compose.figure_layer({"spec": spec, "pose": pz, "expression": expression, "flip": flip, **base}, w, h, logo=lg, inside=0.02)
            res = qa.check_figure(shot.layer, pal)
            if not res["ok"]:
                failed.append({"pose": pz, "size": size, "notes": [qa.note_fa(n) for n in res["notes"]]})
    return {"total": total, "passed": total - len(failed), "failed": failed, "seconds": round(time.time() - t0, 2), "poses": len(pose_list), "sizes": len(sizes), "ok": not failed,
            "style": d["style"]}


def svg(doc: dict, *, pose: str = "stand", expression: str = "happy", prop: str | None = None, flip: bool = False, logo: Image.Image | None = None,
        background: str | None = None, view: str = "figure", title: str = "") -> tuple[str, dict]:
    """متنِ SVG. سبکِ آدمک‌چوبی برداری نیست: تصویرِ شفافش جاسازی می‌شود (``info.embedded`` درست است)."""
    d = D.normalize(doc)
    if d["style"] in VECTOR_STYLES:
        built = F.build(d, pose, expression, flip=flip, prop=prop, logo=logo_for(d, logo))
        bb = F.figure_bbox(built, flip)
        if view == "figure" and bb is not None:
            pad = 24.0
            vb = (bb[0] - pad, bb[1] - pad, bb[2] - bb[0] + 2 * pad, bb[3] - bb[1] + 2 * pad)
        else:
            vb = F.VIEW_BOX
        s = F.to_svg(built, view=vb, size=(int(vb[2]), int(vb[3])), background=background, title=title or d["name"], flip=flip)
        return s, {"embedded": False, "view": list(vb), "head": list(built.head), "frames": {k: list(v) for k, v in built.frames.items()}, "prop": built.prop}
    img, info = sticker(d, pose=pose, expression=expression, prop=prop, flip=flip, logo=logo, height_px=900)
    root = V.G(kids=[V.Img(img, 0, 0, img.width, img.height)])
    return V.to_svg(root, (0, 0, img.width, img.height), background=background, title=title or d["name"]), {"embedded": True, "view": [0, 0, img.width, img.height], "prop": info["prop"]}


def preview_frames(doc: dict, pose: str = "stand", expression: str = "happy") -> dict:
    """قابِ هر جزء (ماتریس‌ها) و مرکزِ سر در ژستِ داده‌شده؛ ادیتور با آن‌ها لایه‌های چسبیده به سر/بدن را روی بوم می‌گذارد (فقط سبک‌های برداری)."""
    d = D.normalize(doc)
    style = d["style"] if d["style"] in VECTOR_STYLES else "flat"
    built = F.build(d, pose, expression, style=style, with_layers=False)
    return {"head": list(built.head), "anchors": {k: list(v) for k, v in built.anchors.items()}, "hands": [list(h) for h in built.hands]}
