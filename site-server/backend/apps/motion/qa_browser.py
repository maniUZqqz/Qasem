"""اندازه‌گیری روی فریم‌های واقعی: همان بستهٔ رندر (Remotion) در حالتِ QA، با مرورگرِ بی‌سرِ سایت.

measure = make_measure(store, workdir, media_dir) ⇒ تابعی که طرح را می‌گیرد و «shot»ها را برمی‌گرداند (qa.geometry_findings همین‌ها را می‌سنجد):
  هر shot = {scene, kind(enter|late), frame, W, H, scale, safe, boxes[], _image (PIL)، image_rel (برای نمایش در پنل)}.
دو فریم برای هر صحنه (qa.key_frames)؛ تصویرها نصفِ اندازه (۵۴۰×۹۶۰) تا سبک بمانند. فقط وقتی ابزارِ رندرِ سایت آماده باشد کار می‌کند.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from django.conf import settings

from . import qa, runner

logger = logging.getLogger(__name__)

QA_SCALE = 0.5


def available() -> tuple[bool, str]:
    st = runner.site_status()
    if not st["ready"]:
        return False, "؛ ".join(st["reasons"])
    if not (runner.tools_dir() / "qa.mjs").is_file():
        return False, "ابزارِ کنترلِ کیفیت (qa.mjs) پیدا نشد"
    return True, ""


def media_dir_for(store_pk: int, tag: str) -> Path:
    return Path(settings.MEDIA_ROOT) / "generated" / "motion" / str(store_pk) / "qa" / tag


def rel_of(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(settings.MEDIA_ROOT).resolve())).replace("\\", "/")
    except ValueError:
        return ""


def make_measure(store, *, workdir: Path, media_dir: Path | None = None, prefix: str = "r", per_scene: int = 2, scale: float = QA_SCALE,
                 cancelled=None, frames_fn=None):
    """⇒ measure(spec). هر بار فراخوانی = یک دورِ سنجش (نامِ فایل‌ها prefix+شمارهٔ دور). `frames_fn(spec)` اگر داده شود فریم‌ها را خودش انتخاب می‌کند."""
    from . import services            # بعداً وارد می‌شود تا وابستگیِ چرخه‌ای نباشد

    calls = {"n": 0}

    def measure(spec: dict) -> list:
        ok, why = available()
        if not ok:
            raise runner.RenderError("کنترلِ هندسیِ کادر ممکن نیست: " + why, "setup")
        calls["n"] += 1
        n = calls["n"]
        work = Path(workdir) / f"qa{n}"
        shutil.rmtree(work, ignore_errors=True)
        (work / "assets").mkdir(parents=True)
        job_spec, files = services.materialize(store, spec)
        for key, (data, ext) in files.items():
            (work / "assets" / f"{key}{ext}").write_bytes(data)
        frames = (frames_fn or (lambda s: qa.key_frames(s, per_scene)))(spec)
        names = [f"{prefix}{n}-s{f['scene']}-{f['kind']}" for f in frames]
        job = {"props": {"spec": job_spec}, "assets_dir": str(work / "assets"), "out_dir": str(work / "out"), "scale": scale,
               "frames": [{"name": nm, "frame": f["frame"]} for nm, f in zip(names, frames)], "timeout_ms": 90000}
        done = runner.run_render(job, workdir=work, cancelled=cancelled, timeout=600, script="qa.mjs")
        data = json.loads(Path(done["results"]).read_text(encoding="utf-8"))
        by_name = {s["name"]: s for s in data["shots"]}
        shots = []
        for nm, f in zip(names, frames):
            s = by_name.get(nm)
            g = (s or {}).get("geometry") or {}
            if not s or not g or g.get("error"):
                raise runner.RenderError(f"از فریمِ {f['frame']} هندسه‌ای نرسید ({(g or {}).get('error', 'خالی')}).", "qa")
            img = qa.open_image(s["image"])
            rel = ""
            if media_dir is not None:
                media_dir.mkdir(parents=True, exist_ok=True)
                dest = media_dir / f"{nm}.jpg"
                shutil.copyfile(s["image"], dest)
                rel = rel_of(dest)
            shots.append({"scene": f["scene"], "kind": f["kind"], "frame": f["frame"], "W": g["W"], "H": g["H"], "scale": scale, "safe": g.get("safe") or {},
                          "platform": g.get("platform", ""), "boxes": g.get("boxes") or [], "_image": img, "image_rel": rel})
        shutil.rmtree(work, ignore_errors=True)
        return shots

    return measure
