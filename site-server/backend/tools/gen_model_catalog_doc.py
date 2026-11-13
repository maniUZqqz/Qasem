#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Writes docs/compute/model-catalog-fa.md from processing/downloads/*.json (the single source of truth).

    python backend/tools/gen_model_catalog_doc.py [verify-log]

The tables (size, licence, 12 GB fit, `needs`, automatic, source@commit, sha256 prefix) are generated, never typed by hand, so the
document cannot drift from what the node really downloads. `verify-log` = the output of `gen_model_manifests.py --verify`;
its summary line goes into the document.
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOWNLOADS = os.path.join(ROOT, "processing", "downloads")
OUT = os.path.join(ROOT, "docs", "compute", "model-catalog-fa.md")
FA = "۰۱۲۳۴۵۶۷۸۹"

GROUPS = [("image", "تصویر"), ("video", "ویدیو"), ("upscale", "بزرگ‌کردن و ترمیم"), ("control", "کنترل و ثبات"), ("depth", "عمق و سه‌بعدی")]
LICENSE = {"open": "تجاری مجاز", "restricted": "با شرط", "noncommercial": "فقط غیرتجاری"}
FIT = {"full": "جا می‌شود", "offload": "با کمی کندی", "tight": "سنگین و کند"}
FEATURES = {"image_studio": "ساختِ تصویر", "photo_enhance": "بزرگ‌کردنِ عکس", "smooth_motion": "نرم‌کردنِ حرکت", "depth_3d": "عمق و سه‌بعدی",
            "design_styles": "سبک‌های طراحی", "video_ai": "ویدیوی AI سبک", "face_restore": "ترمیمِ چهره",
            "thumbnails": "بندانگشتی و پست", "consistency": "ثباتِ چهره و سبک", "image_edit": "ویرایشِ تصویر با دستور"}


def fa(n):
    return str(n).translate(str.maketrans("0123456789", FA))


def size(b):
    mb = b / 2 ** 20
    if mb < 1000:
        return "%s مگابایت" % fa(max(1, round(mb)))
    gb = mb / 1024
    return "%s گیگابایت" % fa(("%.0f" if gb >= 10 else "%.1f") % gb).replace(".", "٫")


def main():
    docs = {}
    for path in sorted(glob.glob(os.path.join(DOWNLOADS, "*.json"))):
        d = json.load(open(path, encoding="utf-8"))
        if d.get("package_info"):
            docs[os.path.basename(path)] = d
    packages = {}
    for name, d in docs.items():
        for it in d["items"]:
            row = packages.setdefault(it["package"], {"file": name, "info": d["package_info"][it["package"]], "items": []})
            row["items"].append(it)
    verify = ""
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        lines = [x for x in open(sys.argv[1], encoding="utf-8").read().splitlines() if x.strip()]
        ok = sum(1 for x in lines if x.rstrip().endswith(" ok"))
        verify = "%s آدرس روی huggingface.co و hf-mirror.com سنجیده شد؛ %s مورد درست و اندازهٔ گزارش‌شدهٔ سرور برابرِ اندازهٔ ثبت‌شده؛ %s" % (
            fa(ok // 2), fa(ok), "مشکل: " + fa(next((x for x in lines if x.startswith("verify:")), "verify: ?").split()[1]))
    out = []
    w = out.append
    w("# فهرستِ مدل‌ها: ComfyUI و Hugging Face (دانلودِ مدل‌ها)")
    w("")
    w("> این فایل را `backend/tools/gen_model_catalog_doc.py` از `processing/downloads/*.json` می‌سازد؛ دستی ویرایش نشود.")
    w("")
    w("مالک (۱۴۰۵/۰۸/۲۳): «دوباره فقط Ollama گذاشتی؛ قرار بود هاگینگ‌فیس، ComfyUI و منبع‌های دیگرِ مفید هم باشد» و «کارت را پیدا نکردم».")
    w("")
    w("## کجاست؟")
    w("")
    w("پنل ⇐ **ابزارها ⇐ دانلودِ مدل‌ها** (`/panel/tools/models`). همین‌جا مدل‌های Ollama، بسته‌های ComfyUI / Hugging Face (گروه‌بندی‌شده)، "
      "دانلودِ خودکار، فضای دیسک و پیشرفتِ دانلود یک‌جاست. از «سرورهای پردازش» (کارتِ «دانلودِ مدل‌ها») و «موتورهای AI» هم پیوند دارد.")
    w("")
    w("## بسته‌ها")
    w("")
    w("هر بسته چند فایل دارد؛ اندازه و sha256 از API ِ Hugging Face گرفته شده (commit ِ سنجاق‌شده)، و گره پس از دانلود دوباره می‌سنجد. "
      "ستونِ «۱۲GB» یعنی روی RTX 3060 با ۱۲ گیگابایت چقدر راحت اجرا می‌شود. «خودکار» یعنی با روشن‌بودنِ قابلیت‌ش خودش می‌آید "
      "(فقط مجوزِ «تجاری مجاز»).")
    w("")
    for key, title in GROUPS:
        rows = [(pk, r) for pk, r in packages.items() if r["info"]["display"] == key]
        if not rows:
            continue
        rows.sort(key=lambda kv: (kv[1]["info"]["priority"], kv[0]))
        w("### %s" % title)
        w("")
        w("| بسته | نام | حجم | مجوز | ۱۲GB | نیاز دارد | خودکار | قابلیت‌ها |")
        w("|---|---|---|---|---|---|---|---|")
        for pk, r in rows:
            i = r["info"]
            total = sum(x["size"] for x in r["items"])
            auto = "بله (قابلیتِ روشن)" if i["auto"] else "نه (یک کلیک)" if i["license_class"] == "open" else "هرگز"
            w("| `%s` | %s | %s | %s (%s) | %s | %s | %s | %s |" % (
                pk, i["title_fa"], size(total), LICENSE[i["license_class"]], i["license"],
                FIT[i["vram"]["fit"]], "، ".join("`%s`" % n for n in i["needs"]) or "—", auto,
                "، ".join(FEATURES.get(f, f) for f in i["features"])))
        w("")
        for pk, r in rows:
            w("**`%s`** — %s" % (pk, r["info"]["note_fa"]))
            w("")
            w("| فایل | حجم | sha256 | مقصد | منبع |")
            w("|---|---|---|---|---|")
            for x in r["items"]:
                src = x.get("source") or x.get("url", "")
                short = src.replace("https://huggingface.co/", "").replace("https://github.com/", "")
                if "/blob/" in short:
                    repo, rest = short.split("/blob/", 1)
                    short = "%s@%s/%s" % (repo, rest[:8], rest.split("/", 1)[1])
                w("| `%s` | %s | `%s…` | `%s` | `%s` |" % (x["id"].split(":", 1)[1], size(x["size"]), (x.get("sha256") or x.get("ref", ""))[:12],
                                                          x["dest"].replace("{COMFYUI}\\", "").replace("{MODELS}\\", "models\\"), short))
            w("")
    total = sum(x["size"] for r in packages.values() for x in r["items"])
    w("جمعِ همهٔ بسته‌های این فهرست حدودِ %s است؛ **هیچ‌کدام در مجموعهٔ پیش‌فرضِ گره نیست** (همه اختیاری‌اند) و هیچ فایلِ چندگیگابایتی روی سرورِ سایت دانلود نشده." % size(total))
    w("")
    if verify:
        w("**بازبینیِ آدرس‌ها (۱۴۰۵/۰۸/۲۳):** %s." % verify)
        w("")
    w("## دانلودِ خودکار")
    w("")
    w("1. هر قابلیت یک سوئیچ دارد (پنل ⇐ دانلودِ مدل‌ها ⇐ «دانلودِ خودکارِ مدل‌ها»). پیش‌فرضِ روشن: ساختِ تصویر، بزرگ‌کردنِ عکس، نرم‌کردنِ حرکت، عمق و سه‌بعدی؛ "
      "پیش‌فرضِ خاموش: سبک‌های طراحی، ویدیوی AI سبک، ترمیمِ چهره.")
    w("2. سایت با هر heartbeat بلوکِ `models_auto` را می‌فرستد: فهرستِ مرتبِ بسته‌هایی که قابلیت‌های روشن لازم دارند (فقط «تجاری مجاز»)، ذخیرهٔ دیسک (۲۵ گیگابایت) و حدِ «بزرگ» (۱٫۵ گیگابایت).")
    w("3. گره (`processing/model_auto.py`، هر ۱۰ دقیقه و بلافاصله پس از عوضِ تنظیم) دیسکِ آزاد را می‌سنجد: آزاد − ذخیره − آنچه همین الان برنامه‌ریزی شده. "
      "بسته‌ای که جا نشود شروع نمی‌شود و «جای دیسک کافی نیست» نشان داده می‌شود.")
    w("4. بسته‌های کوچک بلافاصله (طبقِ «زمان‌بندیِ دانلود» ِ سرورهای پردازش)، بزرگ‌ها **فقط در بازهٔ شبانه** (حتی اگر حالتِ کلی «الان» باشد) — ادامه‌پذیر (`.part` + Range)، با sha256؛ "
      "اگر بازه وسطِ دانلود تمام شود تمیز می‌ایستد و شبِ بعد ادامه می‌دهد.")
    w("5. سه شکستِ پیاپیِ یک بسته ⇒ یک روز استراحت (دلیل در پنل)؛ یک کلیکِ دستی یا فردا دوباره تلاش می‌شود.")
    w("6. هر چیزی که نصب است (حتی با نامِ دیگر در هر پوشهٔ ComfyUI؛ مثلاً «FLUX.1 [dev] FP8.safetensors») دوباره دانلود نمی‌شود.")
    w("")
    w("## سمتِ سرورِ پردازش (`download_models.py` 1.4)")
    w("")
    w("- `--list` همهٔ بسته‌ها را با مجوز/۱۲GB/وضعیت نشان می‌دهد؛ `--only <بسته>` فایل‌های یک بسته و نیازهایش؛ `--catalog` همهٔ کاتالوگ به‌صورت JSON؛ `--status` وضعیتِ نصب + دیسکِ آزاد.")
    w("- `needs`: هر بسته با نیازهایش می‌آید (همهٔ مدل‌های FLUX ⇐ `flux-common`؛ `ipadapter-sdxl` ⇐ `sdxl-base` و `nodes-ipadapter-plus`).")
    w("- `--all` مجوزِ «با شرط» و «غیرتجاری» را نمی‌گیرد (فقط وقتی نامشان صریح بیاید)؛ این‌ها همیشه اختیاری‌اند.")
    w("- `nodes-ipadapter-plus` یک نودِ ComfyUI است (git در `custom_nodes`، commit سنجاق‌شده) و بعد از نصب باید ComfyUI یک بار دوباره راه بیفتد.")
    w("")
    w("## عمداً نیامد")
    w("")
    w("- **PuLID**: به وزن‌های InsightFace (پژوهشی/غیرتجاری) و ساختِ بومیِ `insightface` روی ویندوز نیاز دارد که بی‌دخالتِ آدم نصب‌شدنی نیست؛ ثباتِ چهره را FLUX Kontext و IP-Adapter پوشش می‌دهند.")
    w("- **Depth-Anything V2 Base/Large/Giant**: CC BY-NC 4.0؛ فقط Small (Apache-2.0).")
    w("- **نودِ ترمیمِ چهرهٔ ComfyUI** (مثلاً `facerestore_cf`): نیازمندیِ pip ِ سنگین (torch/opencv/…) که ComfyUI را خراب می‌کند و مجوزِ مشخص ندارد؛ فایل‌های GFPGAN/CodeFormer در پوشه‌ای که چنین نودهایی می‌خوانند گذاشته می‌شود.")
    w("- **FLUX Fill با fp8 رسمی**: سازنده نسخهٔ fp8 منتشر نکرده؛ بازنشرِ غیررسمی (بدونِ تغییر، همان مجوزِ غیرتجاری) از `wjndd/flux1-fill-dev-fp8` با `provenance` نشانه‌گذاری شده.")
    w("- **ModelScope**: آینهٔ دوم نیامد؛ منبع‌ها `huggingface.co` و `hf-mirror.com` هستند (هر دو سنجیده شد و گره هر دو را امتحان می‌کند).")
    w("")
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")
    print("wrote", OUT, len(out), "lines")


if __name__ == "__main__":
    main()
