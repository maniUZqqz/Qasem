"""The «دستی» video workspace's media: the bin (what a shop can put on a timeline) and the resolver that turns a
clip's ``ref`` into a file — only at render time, on the server. The browser never names a path.

Refs:

    video:<id>          a video the shop uploaded                       (UploadedVideo.video)
    edited:<id>         the automatic/semi-automatic cut of that video   (UploadedVideo.edited)
    script:<id>         a finished generated video                       (VideoScript, best cut: music > voiced > raw)
    audio:<id>          a sound from the audio library                  (AudioAsset)
    pimg:<id>           a product photo                                  (ProductImage)
    photo:<id>          a photo from the photo editor library            (PhotoAsset.original)
    gimg:<id>           a generated image                                (GeneratedImage)
    sticker:<key>       a built-in sticker (transparent PNG)                (services/editing/stickers.py)
    lut:<key>           the shop's imported .cube colour LUT                 (never on the timeline itself: a clip's `lut`)
    matte:<key>         a background-removal matte video (grey)             (never on the timeline itself: a clip's `matte`)
    seq:<id>            a nested sequence of this project                    (resolved by timeline.from_project)
"""
from __future__ import annotations

import contextlib
import logging
import re
from pathlib import Path

from django.conf import settings

from services.editing import luts, mattes, stickers
from services.editing import timeline as tl
from services.media import files as media

logger = logging.getLogger(__name__)

#: A browser plays these in <video> without help; anything else (MOV from an iPhone, MKV, AVI) wants a proxy.
BROWSER_VIDEO = (".mp4", ".m4v", ".webm")
#: Taller than this and scrubbing in the panel gets heavy: a proxy is offered.
PROXY_OVER_HEIGHT = 576
SIZE_STICKER = stickers.SIZE

_PROBE_CACHE: dict[tuple[str, float], dict] = {}


class RefError(tl.TimelineError):
    """A clip points at something that is not there (or not the shop's)."""


def parse_ref(ref: str) -> tuple[str, int]:
    kind, _, raw = str(ref or "").partition(":")
    try:
        return kind, int(raw)
    except ValueError:
        raise RefError(f"منبع «{ref}» نامعتبر است.") from None


def _probe(path: Path) -> dict:
    """{duration, has_audio, width, height} from ffprobe, cached by (path, mtime)."""
    try:
        key = (str(path), path.stat().st_mtime)
    except OSError:
        return {}
    if key in _PROBE_CACHE:
        return _PROBE_CACHE[key]
    from services.video.ffmpeg import probe

    info = {"duration": 0.0, "has_audio": False, "width": 0, "height": 0}
    try:
        data = probe(path)
        info["duration"] = float((data.get("format") or {}).get("duration") or 0)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video" and not info["width"]:
                info["width"], info["height"] = int(stream.get("width") or 0), int(stream.get("height") or 0)
            if stream.get("codec_type") == "audio":
                info["has_audio"] = True
    except Exception as exc:  # noqa: BLE001
        logger.info("probe of %s failed: %s", path, exc)
    if len(_PROBE_CACHE) > 500:
        _PROBE_CACHE.clear()
    _PROBE_CACHE[key] = info
    return info


def _field_path(field) -> Path | None:
    try:
        if field and field.name:
            p = Path(field.path)
            return p if p.is_file() else None
    except (ValueError, NotImplementedError):
        return None
    return None


def proxy_path(kind: str, pk: int) -> Path:
    folder = {"video": f"upload_{pk}", "edited": f"upload_{pk}", "script": f"script_{pk}"}.get(kind)
    if folder is None:
        raise RefError("برای این نوع منبع پیش‌نمایشِ سبک ساخته نمی‌شود.")
    name = "edited_proxy.mp4" if kind == "edited" else "proxy.mp4"
    return Path(settings.MEDIA_ROOT) / "generated" / "editing" / folder / name


def _rel_url(path: Path) -> str:
    return settings.MEDIA_URL.rstrip("/") + "/" + media.media_rel(path)


def locate(store, ref: str) -> dict:
    """ref → {field|path, title, kind, source}. Raises RefError for anything that is not the store's own."""
    from apps.ai.models import AudioAsset
    from apps.photoedit.models import PhotoAsset
    from apps.products.models import ProductImage

    from .models import GeneratedImage, UploadedVideo, VideoScript

    head, _, tail = str(ref or "").partition(":")
    if head == "sticker":
        path = stickers.path_of(tail)
        return {"path": path, "title": stickers.title_of(tail), "kind": "image", "source": "sticker", "obj": None}
    if head == "lut":
        path = luts.path_of(store.pk, tail)
        if path is None:
            raise RefError("LUT پیدا نشد (شاید پاک شده).")
        return {"path": path, "title": "LUT", "kind": "lut", "source": "lut", "obj": None}
    if head == "matte":
        row = mattes.get(store.pk, tail)
        if row is None:
            raise RefError("ماتِ حذفِ پس‌زمینه پیدا نشد (شاید پاک شده).")
        return {"path": mattes.path_of(store.pk, tail), "title": "مات", "kind": "matte", "source": "matte", "obj": None, "matte": row}
    kind, pk = parse_ref(ref)
    if kind in ("video", "edited"):
        up = UploadedVideo.objects.filter(pk=pk, store=store).first()
        field = (up.edited if kind == "edited" else up.video) if up else None
        if up is None or not field:
            raise RefError(f"ویدیوی «{ref}» پیدا نشد.")
        return {"field": field, "title": (up.title or f"ویدیو {pk}") + (" (تدوین‌شده)" if kind == "edited" else ""),
                "kind": "video", "source": kind, "obj": up}
    if kind == "script":
        sc = VideoScript.objects.filter(pk=pk, store=store).select_related("product").first()
        field = next((f for f in (sc.final_video_music, sc.final_video_voiced, sc.final_video) if f), None) if sc else None
        if sc is None or not field:
            raise RefError(f"ویدیوی ساخته‌شدهٔ «{ref}» پیدا نشد.")
        return {"field": field, "title": f"{sc.product.name} — ویدیوی ساخته‌شده", "kind": "video", "source": "script",
                "obj": sc}
    if kind == "audio":
        from services.audio import studio

        asset = AudioAsset.objects.filter(pk=pk, store=store).first()
        path = studio.asset_path(asset) if asset else None
        if asset is None or path is None:
            raise RefError(f"صدای «{ref}» پیدا نشد.")
        return {"path": Path(path), "title": asset.title or asset.get_kind_display(), "kind": "audio", "source": "audio",
                "obj": asset}
    if kind == "pimg":
        pi = ProductImage.objects.filter(pk=pk, product__store=store).select_related("product").first()
        if pi is None or not _field_path(pi.image):
            raise RefError(f"عکسِ محصولِ «{ref}» پیدا نشد.")
        return {"field": pi.image, "title": f"{pi.product.name} — عکس", "kind": "image", "source": "product", "obj": pi}
    if kind == "gimg":
        gi = GeneratedImage.objects.filter(pk=pk, store=store).select_related("product").first()
        if gi is None or not _field_path(gi.image):
            raise RefError(f"تصویرِ ساخته‌شدهٔ «{ref}» پیدا نشد.")
        return {"field": gi.image, "title": f"{gi.product.name} — {gi.get_kind_display()}", "kind": "image",
                "source": "generated", "obj": gi}
    if kind == "photo":
        a = PhotoAsset.objects.filter(pk=pk, store=store).first()
        path = Path(settings.MEDIA_ROOT) / a.original if a else None
        if a is None or path is None or not path.is_file():
            raise RefError(f"عکسِ «{ref}» پیدا نشد.")
        return {"path": path, "title": a.title or f"عکس {pk}", "kind": "image", "source": "photo", "obj": a}
    raise RefError(f"منبع «{ref}» نامعتبر است.")


def describe(store, ref: str) -> dict:
    """What the panel needs to put a clip on the timeline (no file is read except ffprobe's metadata)."""
    found = locate(store, ref)
    path = found.get("path") or _field_path(found.get("field"))
    if path is None:
        raise RefError(f"فایلِ «{ref}» روی سرور پیدا نشد.")
    if found["source"] in ("sticker", "lut", "matte"):
        out = {"ref": ref, "title": found["title"], "kind": found["kind"], "source": found["source"], "duration": 0.0, "has_audio": False,
               "width": SIZE_STICKER if found["source"] == "sticker" else 0, "height": SIZE_STICKER if found["source"] == "sticker" else 0,
               "path": path, "proxy": "not_needed", "proxy_url": None, "auth": False}
        if found["source"] == "sticker":
            out["url"] = _rel_url(path)
        if found.get("matte"):
            out["s0"] = found["matte"]["s0"]
        return out
    facts = _probe(path) if found["kind"] != "image" else {}
    kind, pk = parse_ref(ref)
    duration = facts.get("duration", 0.0)
    has_audio = bool(facts.get("has_audio")) if found["kind"] == "video" else found["kind"] == "audio"
    out = {
        "ref": ref, "title": found["title"], "kind": found["kind"], "source": found["source"],
        "duration": round(duration, 2), "has_audio": has_audio,
        "width": facts.get("width", 0), "height": facts.get("height", 0), "path": path,
    }
    if found["kind"] == "audio":
        out["url"] = f"/api/v1/stores/{store.pk}/audio/assets/{pk}/file/"
        out["auth"] = True
    else:
        out["url"] = _rel_url(path)
        out["auth"] = False
    out["proxy"], out["proxy_url"] = "not_needed", None
    if found["kind"] == "video":
        wants = path.suffix.lower() not in BROWSER_VIDEO or facts.get("height", 0) > PROXY_OVER_HEIGHT
        try:
            pp = proxy_path(kind, pk)
        except RefError:
            pp = None
        if pp is not None and pp.is_file() and pp.stat().st_size > 0:
            out["proxy"], out["proxy_url"] = "ready", _rel_url(pp)
        elif wants:
            out["proxy"] = "needed"
    return out


def public(item: dict) -> dict:
    return {k: v for k, v in item.items() if k != "path"}


def bin_items(store, limit: int = 40) -> dict:
    """Everything a shop can drag onto the timeline, grouped for the media bin."""
    from apps.ai.models import AudioAsset
    from apps.photoedit.models import PhotoAsset
    from apps.products.models import ProductImage

    from .models import UploadedVideo, VideoScript

    def safe(ref):
        try:
            return public(describe(store, ref))
        except tl.TimelineError:
            return None

    videos = []
    for up in UploadedVideo.objects.filter(store=store).exclude(state="FAILED")[:limit]:
        for ref, present in ((f"video:{up.pk}", bool(up.video)), (f"edited:{up.pk}", bool(up.edited))):
            if present and (item := safe(ref)):
                videos.append(item)
    for sc in VideoScript.objects.filter(store=store).exclude(final_video="")[:limit]:
        if item := safe(f"script:{sc.pk}"):
            videos.append(item)
    audio = [item for a in AudioAsset.objects.filter(store=store, status="READY", saved=True)[:limit]
             if (item := safe(f"audio:{a.pk}"))]
    images = [item for p in ProductImage.objects.filter(product__store=store).order_by("-id")[:limit]
              if (item := safe(f"pimg:{p.pk}"))]
    images += [item for a in PhotoAsset.objects.filter(store=store)[:limit] if (item := safe(f"photo:{a.pk}"))]
    sticker_items = []
    for row in stickers.available():
        item = safe(f"sticker:{row['key']}")
        if item:
            sticker_items.append({**item, "title": row["title"], "group": row["group"]})
    return {"videos": videos, "audio": audio, "images": images, "stickers": sticker_items}


@contextlib.contextmanager
def sources(store):
    """A resolver for `timeline.from_project`: ref → real local file, kept readable for the whole `with` block."""
    stack = contextlib.ExitStack()
    cache: dict[str, dict] = {}

    def resolve(ref: str) -> dict:
        if ref in cache:
            return cache[ref]
        found = locate(store, ref)
        if "path" in found:
            path = found["path"]
        else:
            path = stack.enter_context(media.reading(found["field"]))
        facts = _probe(Path(path)) if found["kind"] in ("video", "audio") else {}
        info = {
            "path": str(path), "kind": found["kind"],
            "has_audio": bool(facts.get("has_audio")) if found["kind"] == "video" else found["kind"] == "audio",
            "duration": float(facts.get("duration") or 0.0),
            "width": int(facts.get("width") or 0), "height": int(facts.get("height") or 0),
        }
        if found.get("matte"):
            info["s0"] = float(found["matte"].get("s0") or 0.0)
        cache[ref] = info
        return info

    try:
        yield resolve
    finally:
        stack.close()


def check(store, data: dict) -> dict:
    """Would this project render? Same rules as the renderer, without touching a frame."""
    def resolve(ref):
        item = describe(store, ref)
        return {"path": str(item["path"]), "kind": item["kind"], "has_audio": item["has_audio"],
                "duration": item["duration"], "width": item.get("width", 0), "height": item.get("height", 0),
                "s0": item.get("s0", 0.0)}

    try:
        line = tl.from_project(data, resolve)
        line.validate()
        tl.program_operations(data)
    except tl.TimelineError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "error": "", "length": round(line.length, 2), "gaps": line.as_dict()["gaps"],
            "size": f"{line.width}x{line.height}"}


# ------------------------------------------------------------------ subtitles

_SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def parse_srt(text: str) -> list[dict]:
    lines = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        rows = [r for r in block.split("\n") if r.strip()]
        for i, row in enumerate(rows):
            m = _SRT_TIME.search(row)
            if not m:
                continue
            g = [int(x) for x in m.groups()]
            start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
            end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
            body = " ".join(rows[i + 1:]).strip()
            if body and end > start:
                lines.append({"start": round(start, 2), "end": round(end, 2), "text": body[:200]})
            break
    return lines


def subtitle_lines(store, ref: str) -> list[dict]:
    """The subtitle lines of an uploaded video (SRT), in SOURCE seconds — the panel offsets them onto the timeline."""
    kind, pk = parse_ref(ref)
    found = locate(store, ref)
    field = getattr(found.get("obj"), "subtitles", None)
    if kind not in ("video", "edited", "script") or not field:
        raise RefError("برای این ویدیو زیرنویسی ساخته نشده است؛ اول از بخش «زیرنویس» بسازید.")
    with media.reading(field) as path:
        return parse_srt(Path(path).read_text(encoding="utf-8", errors="replace"))
