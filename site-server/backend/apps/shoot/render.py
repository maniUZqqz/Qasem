"""تدوینِ خودکار: برداشت‌ها ⇐ ویدیوی تبلیغاتیِ ۹:۱۶ (یا ۱:۱). همه روی سرورِ سایت با ffmpeg (nice).

۱. بهترین برداشتِ هر نما (پذیرفته‌شده، بیشترین امتیاز).
۲. برش به اندازهٔ برنامه (نیم‌ثانیهٔ اولِ لرزانِ «ضبط را زدم» کنار می‌رود).
۳. لرزش‌گیری با vidstab (دو گذر) اگر ffmpeg دارد.
۴. اصلاحِ نور و رنگ از روی روشناییِ اندازه‌گیری‌شدهٔ همان برداشت (eq).
۵. کادر: پُرکردنِ ۹:۱۶؛ برداشتِ افقی روی نسخهٔ محوشدهٔ خودش.
۶. متنِ هر نما (نام، ویژگی‌ها) به شکلِ PNG ِ راست‌به‌چپ روی تصویر با محو شدن.
۷. ترتیبِ برنامه + گذار (xfade) + کارتِ پایانی (همان طرحِ پوستر: نام، قیمت، دعوت به خرید، لوگو).
۸. گویندهٔ اختیاری (موتورِ گفتارِ سایت) + موسیقی از کتابخانهٔ صدا با داکینگ (services.audio.music).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from PIL import Image, ImageDraw

from . import media, poster
from .models import ShootOutput, ShootTake
from .services import best_take

logger = logging.getLogger(__name__)

SIZES = {"9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350)}
FPS = 30
XF = 0.4
TRANSITIONS = {"fade": "fade", "slide": "slideleft", "zoom": "zoomin", "dissolve": "dissolve", "none": ""}
MIN_SEG = 1.2
STILL_SECONDS = 2.6
MAX_STILLS = 4


def _even(x: float) -> int:
    return int(round(x / 2)) * 2


def fit_graph(src_w: int, src_h: int, W: int, H: int, inp: str, out: str) -> str:
    """کادرِ مقصد: نزدیک به همان نسبت ⇐ برش؛ خیلی متفاوت (افقی در ۹:۱۶) ⇐ روی نسخهٔ محوشدهٔ خودش."""
    ar_s = (src_w or W) / max(1, (src_h or H))
    ar_d = W / H
    if abs(ar_s / ar_d - 1) < 0.28:
        return f"[{inp}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1[{out}]"
    return (f"[{inp}]split=2[{out}a][{out}b];"
            f"[{out}a]scale={_even(W / 4)}:{_even(H / 4)}:force_original_aspect_ratio=increase,"
            f"crop={_even(W / 4)}:{_even(H / 4)},boxblur=10:2,scale={W}:{H},eq=brightness=-0.06[{out}bg];"
            f"[{out}b]scale={W}:{H}:force_original_aspect_ratio=decrease,setsar=1[{out}fg];"
            f"[{out}bg][{out}fg]overlay=(W-w)/2:(H-h)/2,setsar=1[{out}]")


def grade_filter(brightness) -> str:
    try:
        b = float(brightness)
    except (TypeError, ValueError):
        b = 120.0
    shift = max(-0.08, min(0.1, (120.0 - b) / 255.0 * 0.6))
    return f"eq=brightness={shift:.3f}:contrast=1.05:saturation=1.08"


def caption_png(text: str, W: int, H: int, path: Path, *, style: str = "lower") -> Path | None:
    text = (text or "").strip()
    if not text:
        return None
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    big = style == "title"
    f = poster._font(int(W * (0.075 if big else 0.052)), True)
    lines = poster._wrap(d, text, f, int(W * 0.84), 2)
    lh = poster._line_h(f)
    block = lh * len(lines)
    pad = int(f.size * 0.55)
    y = int(H * (0.12 if big else 0.72))
    widths = [poster._width(d, ln, f) for ln in lines]
    bw = int(max(widths) + pad * 2)
    d.rounded_rectangle([(W - bw) // 2, y - pad // 2, (W + bw) // 2, y + block + pad // 2], radius=pad,
                        fill=(0, 0, 0, 120 if big else 150))
    for ln in lines:
        poster._text_center(d, y, ln, f, (255, 255, 255), W, (0, 0, 0, 160))
        y += lh
    img.save(path)
    return path


def _caption_tail(dur: float) -> str:
    out_at = max(0.5, dur - 0.65)
    return (f"[1:v]format=rgba,fade=t=in:st=0.2:d=0.35:alpha=1,fade=t=out:st={out_at:.2f}:d=0.35:alpha=1[cap];"
            f"[g][cap]overlay=0:0:shortest=1,format=yuv420p[out]")


def _encode_args(out: Path) -> list:
    return ["-an", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", out]


def segment_video(take: ShootTake, start: float, dur: float, W: int, H: int, work: Path, idx: int,
                  caption: Path | None, stabilize: bool) -> Path:
    src = media.abs_path(take.file)
    out = work / f"seg{idx:02d}.mp4"
    pre = f"[0:v]fps={FPS},format=yuv420p[src];" + fit_graph(take.width, take.height, W, H, "src", "fit")
    stab = ""
    if stabilize:
        trf = work / f"seg{idx:02d}.trf"
        media.run_ff(["-y", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", src, "-filter_complex",
                      pre + f";[fit]vidstabdetect=shakiness=6:accuracy=12:result={trf}[d]", "-map", "[d]",
                      "-f", "null", "-"])
        stab = f"vidstabtransform=input={trf}:smoothing=12:zoom=3:optzoom=0,unsharp=5:5:0.5:3:3:0.2,"
    grade = grade_filter((take.checks or {}).get("metrics", {}).get("brightness"))
    graph = pre + f";[fit]{stab}{grade},format=yuv420p[g]"
    args = ["-y", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", src]
    if caption:
        args += ["-loop", "1", "-t", f"{dur:.2f}", "-i", caption]
        graph += ";" + _caption_tail(dur)
    else:
        graph += ";[g]null[out]"
    media.run_ff(args + ["-filter_complex", graph, "-map", "[out]"] + _encode_args(out))
    return out


def segment_still(image_path: Path, dur: float, W: int, H: int, work: Path, idx: int, caption: Path | None,
                  *, zoom: bool = True) -> Path:
    out = work / f"seg{idx:02d}.mp4"
    with Image.open(image_path) as im:
        iw, ih = im.size
    graph = f"[0:v]format=yuv420p[src];" + fit_graph(iw, ih, W, H, "src", "fit")
    if zoom:
        zw, zh = _even(W * 1.08), _even(H * 1.08)
        graph += (f";[fit]scale={zw}:{zh},crop={W}:{H}:x='(in_w-out_w)*t/{dur:.2f}':y='(in_h-out_h)/2',"
                  f"fps={FPS},format=yuv420p[g]")
    else:
        graph += f";[fit]fps={FPS},format=yuv420p[g]"
    args = ["-y", "-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.2f}", "-i", image_path]
    if caption:
        args += ["-loop", "1", "-t", f"{dur:.2f}", "-i", caption]
        graph += ";" + _caption_tail(dur)
    else:
        graph += ";[g]null[out]"
    media.run_ff(args + ["-filter_complex", graph, "-map", "[out]", "-t", f"{dur:.2f}"] + _encode_args(out))
    return out


def join(segments: list[tuple[Path, float]], out: Path, transition: str) -> float:
    xname = TRANSITIONS.get(transition, "fade")
    if xname and not media.has_filter("xfade"):
        xname = ""
    args = ["-y"]
    for p, _d in segments:
        args += ["-i", p]
    parts = [f"[{i}:v]settb=AVTB,fps={FPS},format=yuv420p,setsar=1[s{i}]" for i in range(len(segments))]
    if len(segments) == 1:
        parts.append("[s0]null[v]")
        total = segments[0][1]
    elif xname:
        prev, offset = "s0", segments[0][1] - XF
        for i in range(1, len(segments)):
            label = "v" if i == len(segments) - 1 else f"x{i}"
            parts.append(f"[{prev}][s{i}]xfade=transition={xname}:duration={XF}:offset={offset:.3f}[{label}]")
            prev = label
            offset += segments[i][1] - XF
        total = sum(d for _p, d in segments) - XF * (len(segments) - 1)
    else:
        parts.append("".join(f"[s{i}]" for i in range(len(segments))) + f"concat=n={len(segments)}:v=1:a=0[v]")
        total = sum(d for _p, d in segments)
    media.run_ff(args + ["-filter_complex", ";".join(parts), "-map", "[v]", "-an", "-r", str(FPS),
                         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                         "-profile:v", "high", "-level", "4.1", "-movflags", "+faststart", out])
    return total


def add_audio(silent: Path, out: Path, total: float, voice_mp3: Path | None) -> Path:
    if voice_mp3:
        media.run_ff(["-y", "-i", silent, "-i", voice_mp3, "-filter_complex",
                      "[1:a]adelay=700|700,aresample=48000,aformat=channel_layouts=stereo,apad[a]",
                      "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
                      "-t", f"{total:.2f}", "-movflags", "+faststart", out])
    else:
        media.run_ff(["-y", "-i", silent, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v",
                      "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-t", f"{total:.2f}",
                      "-movflags", "+faststart", out])
    return out


def _trim_window(take_dur: float, want: float) -> tuple[float, float]:
    if take_dur <= 0:
        return 0.0, want
    if take_dur >= want + 0.6:
        return min(0.5, take_dur - want), want
    dur = max(MIN_SEG, min(want, take_dur - 0.1))
    return max(0.0, (take_dur - dur) / 2), dur


def music_path(store, asset_id) -> tuple[Path | None, str]:
    if not asset_id:
        return None, ""
    from apps.ai.models import AudioAsset
    from services.audio import studio

    asset = AudioAsset.objects.filter(store=store, pk=asset_id, status=AudioAsset.Status.READY).first()
    if asset is None:
        return None, ""
    return studio.asset_path(asset), asset.title or asset.text[:40]


def render_video(output: ShootOutput, user=None, progress=lambda f, m: None) -> dict:
    from services.audio import music as music_mod
    from services.video.ffmpeg import probe_duration

    from . import voice

    session = output.session
    plan = session.plan or {}
    opts = output.options or {}
    W, H = SIZES.get(output.aspect, SIZES["9:16"])
    work = media.abs_path(f"{session.dir_rel}/work/o{output.pk}")
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    notes, steps = [], []
    caps = media.capabilities()
    stabilize = bool(opts.get("stabilize", True)) and caps["stabilize"]
    texts = opts.get("texts") or {}
    headline = (texts.get("title") or plan.get("ad", {}).get("headline") or session.product.name).strip()
    feats = texts.get("features") if isinstance(texts.get("features"), list) else plan.get("features") or []

    # ── گوینده (اول، تا طولِ کارتِ پایانی را بدانیم)
    voice_mp3, voice_dur, voice_engine = None, 0.0, ""
    vo_text = (opts.get("voiceover_text") or plan.get("ad", {}).get("voiceover") or "").strip()
    if opts.get("voiceover") and vo_text:
        progress(0.05, "ساختِ صدای گوینده")
        try:
            voice_mp3, voice_engine = voice.voiceover(session.store, vo_text[:600], work / "voiceover.mp3")
            voice_dur = probe_duration(voice_mp3)
            steps.append({"step": "گوینده", "where": f"موتورِ گفتارِ سایت ({voice_engine})"})
        except Exception as exc:  # noqa: BLE001
            notes.append(f"گوینده ساخته نشد ({str(exc)[:120]}) ⇐ بی‌گوینده.")
            voice_mp3 = None

    # ── نماها
    shots = plan.get("video") or []
    segments: list[tuple[Path, float]] = []
    used = []
    for i, shot in enumerate(shots):
        take = best_take(session, shot["key"])
        if take is None or take.kind != ShootTake.Kind.VIDEO:
            notes.append(f"نمای «{shot.get('title')}» برداشتِ پذیرفته نداشت ⇐ کنار رفت.")
            continue
        progress(0.1 + 0.55 * i / max(1, len(shots)), f"تدوینِ نمای {i + 1} از {len(shots)}: {shot.get('title')}")
        start, dur = _trim_window(take.duration, float(shot.get("duration") or 4))
        k = len(segments)
        if k == 0:
            cap_text = headline
        elif isinstance(texts.get("features"), list):
            # متن‌هایی که کاربر در فرمِ تدوین عوض کرد بر متنِ برنامه مقدم است
            cap_text = feats[k - 1] if k - 1 < len(feats) else ""
        else:
            cap_text = shot.get("caption") or ""
        cap_text = cap_text.split(":")[-1].strip()
        cap = caption_png(cap_text, W, H, work / f"cap{i:02d}.png", style="title" if k == 0 else "lower")
        try:
            seg = segment_video(take, start, dur, W, H, work, len(segments), cap, stabilize)
        except Exception as exc:  # noqa: BLE001
            if not stabilize:
                raise
            notes.append(f"لرزش‌گیریِ نمای {i + 1} نشد ({str(exc)[:80]}) ⇐ بی‌لرزش‌گیری.")
            seg = segment_video(take, start, dur, W, H, work, len(segments), cap, False)
        segments.append((seg, dur))
        used.append({"shot": shot["key"], "take": take.pk, "start": round(start, 2), "seconds": round(dur, 2),
                     "score": take.score})

    # ── عکس‌ها وقتی ویدیو کم است
    photo_takes = []
    for shot in plan.get("photos") or []:
        t = best_take(session, shot["key"])
        if t is not None and t.kind == ShootTake.Kind.PHOTO:
            photo_takes.append((shot, t))
    if len(segments) < 3 and photo_takes:
        for shot, t in photo_takes[:max(0, MAX_STILLS - len(segments))]:
            k = len(segments)
            cap_text = headline if k == 0 else (feats[k - 1] if k - 1 < len(feats) else "").split(":")[-1].strip()
            cap = caption_png(cap_text, W, H, work / f"capp{k:02d}.png", style="title" if k == 0 else "lower")
            progress(0.6, f"عکسِ «{shot.get('title')}» به‌عنوانِ نما")
            segments.append((segment_still(media.abs_path(t.file), STILL_SECONDS, W, H, work, k, cap), STILL_SECONDS))
            used.append({"shot": shot["key"], "take": t.pk, "still": True, "seconds": STILL_SECONDS})
    if not segments:
        raise ValueError("هیچ برداشتِ پذیرفته‌ای نیست؛ اول دست‌کم یک نمای ویدیو یا یک عکس بگیرید.")

    # ── کارتِ پایانی (همان طرحِ پوستر)
    progress(0.7, "کارتِ پایانی")
    best_photo = photo_takes[0][1] if photo_takes else None
    if best_photo is not None:
        base_img = Image.open(media.abs_path(best_photo.file)).convert("RGB")
    else:
        frame = work / "outro_src.jpg"
        last = media.abs_path(best_take(session, used[0]["shot"]).file)
        media.run_ff(["-y", "-ss", "1", "-i", last, "-frames:v", "1", frame])
        base_img = Image.open(frame).convert("RGB")
    card = poster.compose(base_img, size=(W, H), template=opts.get("template") or "bold",
                          texts={"title": headline, "features": [], "price": texts.get("price", plan.get("ad", {})
                                                                                   .get("price", "")),
                                 "cta": texts.get("cta") or plan.get("ad", {}).get("cta", "")},
                          logo=poster.store_logo(session.store) if opts.get("logo", True) else None,
                          brand=poster.brand_color(session.store), store_name=session.store.name)
    card_path = work / "outro.png"
    card.save(card_path)
    est = sum(d for _p, d in segments) - XF * len(segments)
    outro_dur = 3.0
    if voice_dur and voice_dur + 1.4 > est + outro_dur:
        outro_dur = min(8.0, voice_dur + 1.4 - est)
    segments.append((segment_still(card_path, outro_dur, W, H, work, len(segments), None, zoom=False), outro_dur))

    # ── چسباندن + گذار
    progress(0.78, "چسباندنِ نماها و گذارها")
    silent = work / "silent.mp4"
    total = join(segments, silent, opts.get("transition") or "fade")
    steps += [
        {"step": "انتخابِ بهترین برداشت و برش به اندازهٔ برنامه", "where": "سرورِ سایت"},
        {"step": "لرزش‌گیری (vidstab)" if stabilize else "لرزش‌گیری (خاموش یا در دسترس نیست)",
         "where": "سرورِ سایت (ffmpeg)"},
        {"step": "اصلاحِ نور و رنگ، کادرِ " + output.aspect + "، متن‌ها، گذارها", "where": "سرورِ سایت (ffmpeg)"},
    ]

    # ── صدا
    progress(0.88, "صدا: گوینده و موسیقی")
    with_audio = work / "with_audio.mp4"
    add_audio(silent, with_audio, total, voice_mp3)
    final = work / "final.mp4"
    mpath, mtitle = music_path(session.store, opts.get("music"))
    if opts.get("music") and mpath is None:
        notes.append("موسیقیِ انتخاب‌شده در کتابخانه پیدا نشد ⇐ بی‌موسیقی.")
    if mpath is not None:
        try:
            level = float(opts.get("music_level_db", music_mod.MUSIC_DB))
            music_mod.under_narration(with_audio, music_mod.Track(path=mpath, level_db=level), final,
                                      duck=voice_mp3 is not None)
            steps.append({"step": f"موسیقی «{mtitle}»" + (" با داکینگ زیرِ گوینده" if voice_mp3 else ""),
                          "where": "سرورِ سایت (ffmpeg)"})
        except Exception as exc:  # noqa: BLE001
            notes.append(f"موسیقی ننشست ({str(exc)[:120]}).")
            final = with_audio
    else:
        final = with_audio

    rel = f"{session.dir_rel}/out/video_{output.aspect.replace(':', 'x')}_v{output.version}_{output.pk}.mp4"
    dest = media.abs_path(rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    final.replace(dest)
    thumb_rel = rel.replace(".mp4", ".jpg")
    media.run_ff(["-y", "-ss", "1", "-i", dest, "-frames:v", "1", "-vf", "scale=540:-2", media.abs_path(thumb_rel)])
    for p in work.iterdir():      # کارگاه پاک می‌شود؛ فقط خروجی می‌ماند
        p.unlink(missing_ok=True)
    try:
        work.rmdir()
    except OSError:
        pass
    return {"file": rel, "thumb": thumb_rel, "stats": {
        "seconds": round(total, 1), "render_seconds": round(time.monotonic() - t0, 1), "segments": used,
        "stabilized": stabilize, "voice_engine": voice_engine, "music": mtitle, "notes": notes, "steps": steps,
        "size": dest.stat().st_size}}


def render_poster(output: ShootOutput, user=None, progress=lambda f, m: None) -> dict:
    session = output.session
    plan = session.plan or {}
    opts = output.options or {}
    W, H = poster.SIZES.get(output.aspect, poster.SIZES["1:1"])
    texts = opts.get("texts") or {}
    take = None
    if opts.get("take"):
        take = session.takes.filter(pk=opts["take"], kind=ShootTake.Kind.PHOTO).first()
    if take is None:
        for shot in plan.get("photos") or []:
            take = best_take(session, shot["key"])
            if take is not None:
                break
    if take is None:
        raise ValueError("هیچ عکسِ پذیرفته‌ای نیست؛ اول دست‌کم یک زاویه عکس بگیرید.")
    t0 = time.monotonic()
    steps = [{"step": "انتخابِ بهترین عکس و اصلاحِ نور و رنگ", "where": "سرورِ سایت (Pillow)"}]
    cutout, note = None, ""
    if opts.get("cutout", True):
        progress(0.2, "حذفِ پس‌زمینه روی سرورِ پردازش (اگر روشن باشد)")
        cutout, note = poster.request_cutout(session, take, user)
        steps.append({"step": "حذفِ پس‌زمینه" if cutout is not None else "زمینهٔ محو و رنگی",
                      "where": "سرورِ پردازش (GPU)" if cutout is not None else "سرورِ سایت (Pillow)"})
    progress(0.8, "چیدنِ متن و قیمت")
    photo = Image.open(media.abs_path(take.file)).convert("RGB")
    img = poster.compose(
        photo, size=(W, H), template=output.template or "clean", cutout=cutout,
        texts={"title": texts.get("title") or plan.get("ad", {}).get("headline") or session.product.name,
               "features": texts.get("features") if isinstance(texts.get("features"), list)
               else plan.get("features") or [],
               "price": texts.get("price", plan.get("ad", {}).get("price", "")),
               "old_price": texts.get("old_price", ""),
               "cta": texts.get("cta") or plan.get("ad", {}).get("cta", "")},
        logo=poster.store_logo(session.store) if opts.get("logo", True) else None,
        brand=poster.brand_color(session.store), store_name=session.store.name)
    steps.append({"step": "طرحِ «" + poster.TEMPLATES.get(output.template, output.template) + "» با متن، قیمت، لوگو",
                  "where": "سرورِ سایت (Pillow)"})
    rel = f"{session.dir_rel}/out/poster_{output.aspect.replace(':', 'x')}_v{output.version}_{output.pk}.jpg"
    dest = media.abs_path(rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "JPEG", quality=92, optimize=True)
    thumb = img.copy()
    thumb.thumbnail((480, 480))
    thumb_rel = rel.replace(".jpg", "_t.jpg")
    thumb.save(media.abs_path(thumb_rel), "JPEG", quality=82)
    return {"file": rel, "thumb": thumb_rel, "stats": {
        "take": take.pk, "shot": take.shot, "cutout": cutout is not None, "notes": [note] if note else [],
        "steps": steps, "render_seconds": round(time.monotonic() - t0, 1), "size": dest.stat().st_size}}
