"""متنِ فارسیِ «نصبِ خودکارِ نیازمندی‌ها» برای پنل (۱۴۰۵/۰۸/۲۳).

عاملِ گره (processing/bootstrap.py) برای کنسولِ ویندوز انگلیسی می‌نویسد (کنسولِ فارسی خراب می‌شود)، ولی هر چه به پنل می‌رسد باید فارسی باشد:
عنوانِ هر گام (از requirements.d) و جمله‌های وضعیت («installing ...»، «waiting for: gpu-runtime»، «failed (try 2)») این‌جا هنگامِ ساختنِ پاسخِ
پنل ترجمه می‌شوند. چیزِ ناشناخته همان‌طور که هست می‌ماند (متنِ فنیِ خطا و مسیرها عمداً دست‌نخورده‌اند)."""
from __future__ import annotations

import copy
import re

_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

TITLES = {
    "Python packages of Abagram (FastAPI, Playwright ...)": "بسته‌های پایتونِ آباگرام (FastAPI، Playwright …)",
    "Browser for Abagram (Microsoft Edge / Chrome)": "مرورگرِ آباگرام (Edge یا Chrome)",
    "Python environment asr": "محیطِ پایتونِ تشخیصِ گفتار",
    "faster-whisper, CTranslate2, CUDA 12 runtime wheels": "faster-whisper، CTranslate2 و بسته‌های اجرای CUDA 12",
    "Whisper small model (484 MB)": "مدلِ Whisper کوچک (۴۸۴ مگابایت)",
    "CTranslate2 sees the GPU": "CTranslate2 کارتِ گرافیک را می‌بیند",
    "Whisper large-v3-turbo model (1.6 GB)": "مدلِ Whisper large-v3-turbo (۱٫۶ گیگابایت)",
    "Robust Video Matting (mobilenetv3 fp32, ONNX, 14 MB)": "مدلِ جداسازیِ پس‌زمینهٔ ویدیو (RVM، ۱۴ مگابایت)",
    "numpy + Pillow + onnxruntime are importable in venvs/matting": "numpy، Pillow و onnxruntime در محیطِ جداسازی بالا می‌آیند",
    "Blender 4.5.14 LTS (win-x64)": "Blender 4.5.14 LTS (ویندوز)",
    "Cycles sees the graphics card (OptiX, else CUDA)": "Cycles کارتِ گرافیک را می‌بیند (OptiX یا CUDA)",
    "MPFB character data (about 430 MB)": "دادهٔ شخصیت‌های MPFB (حدود ۴۳۰ مگابایت)",
    "ffmpeg with a working NVENC encoder": "ffmpeg با رمزگذاریِ NVENC",
    "Python environment (venvs/matting)": "محیطِ پایتونِ جداسازی (venvs/matting)",
    "numpy, Pillow, OpenCV, onnxruntime-directml": "numpy، Pillow، OpenCV و onnxruntime-directml",
    "onnxruntime offers a GPU provider": "onnxruntime روی کارتِ گرافیک کار می‌کند",
    "Node.js 20.18.0 (win-x64)": "Node.js 20.18.0 (ویندوز)",
}

#: نوعِ گام ⇐ عنوانِ فارسیِ عمومی، وقتی ویژگی عنوانِ خودش را نداده است
TYPE_TITLES = {"venv": "ساختنِ محیطِ پایتون", "pip": "نصبِ بسته‌های پایتون", "archive": "دانلود و بازکردنِ فایل‌ها", "files": "دانلودِ فایل‌های مدل",
               "ffmpeg-nvenc": "ffmpeg با NVENC", "ort-gpu": "onnxruntime روی کارتِ گرافیک", "cmd": "بررسی و نصب"}

#: (الگو، جایگزین) — برای «detail» و «why»
RULES = [
    (re.compile(r"^installing \.\.\.$"), "در حال نصب …"),
    (re.compile(r"^waiting for the download window$"), "منتظرِ بازهٔ دانلودِ شبانه (نصبِ نخست منتظر نمی‌ماند؛ این نصبِ دوباره است)"),
    (re.compile(r"^waiting for the previous step$"), "منتظرِ گامِ پیش از خود"),
    (re.compile(r"^waiting for: (.+)$"), r"منتظرِ نصبِ پیش‌نیاز: \1"),
    (re.compile(r"^failed \(try (\d+)\)$"), lambda m: "ناموفق (تلاشِ %s)؛ خودش دوباره تلاش می‌کند" % m.group(1).translate(_DIGITS)),
    (re.compile(r"^creating the Python environment (\S+)$"), r"ساختنِ محیطِ پایتونِ \1"),
    (re.compile(r"^pip install from (\S+)$"), r"نصبِ بسته‌ها از \1"),
    (re.compile(r"^pip failed on (\S+), trying the next source$"), r"نصب از \1 نشد؛ سراغِ منبعِ بعدی می‌رود"),
    (re.compile(r"^source failed \(.*\) - trying the next$"), "این منبع جواب نداد؛ سراغِ منبعِ بعدی می‌رود"),
    (re.compile(r"^downloading (.+)$"), r"دانلودِ \1"),
    (re.compile(r"^unpacking$"), "بازکردنِ فایل‌ها"),
    (re.compile(r"^no NVIDIA GPU on this computer$"), "کارتِ NVIDIA در این رایانه نیست"),
    (re.compile(r"^not for this operating system$"), "برای این سیستم‌عامل نیست"),
]


def fa_detail(text: str) -> str:
    text = str(text or "")
    for pattern, repl in RULES:
        if pattern.match(text):
            return pattern.sub(repl, text) if not callable(repl) else repl(pattern.match(text))
    return text


def translate(boot: dict) -> dict:
    """caps["bootstrap"] ⇒ همان با عنوان و جمله‌های وضعیتِ فارسی (نسخهٔ کپی؛ ورودی عوض نمی‌شود)."""
    if not isinstance(boot, dict) or not boot:
        return boot
    out = copy.deepcopy(boot)
    for feat in (out.get("features") or {}).values():
        if not isinstance(feat, dict):
            continue
        if feat.get("why"):
            feat["why"] = fa_detail(feat["why"])
        for item in feat.get("items") or []:
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            item["title"] = TITLES.get(title) or (TYPE_TITLES.get(item.get("type")) if title in (None, "", item.get("id")) else title) or title
            item["detail"] = fa_detail(item.get("detail"))
    return out
