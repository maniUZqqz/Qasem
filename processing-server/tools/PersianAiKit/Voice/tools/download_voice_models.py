# دانلودِ مدل‌های صدا (VOICE-SETUP.md) — فقط کتابخانهٔ استانداردِ پایتون (۳٫۸ به بالا)، بی pip.
#
#   python tools/download_voice_models.py --list                      فهرستِ مدل‌ها، حجم و مجوز
#   python tools/download_voice_models.py --tier light --dry-run      فقط وارسی: لینک‌ها زنده‌اند؟ چقدر جا لازم است؟
#   python tools/download_voice_models.py --tier light                دانلود در models/
#   python tools/download_voice_models.py --only pocket-fa,sa3-small-sfx
#   python tools/download_voice_models.py --tier heavy --token hf_xxx  مدل‌های gated (اول در سایت درخواستِ دسترسی)
#
# هر فایل: اول در «نام.part»، بعد وارسیِ اندازه و SHA-256 (از خودِ Hugging Face) و جابه‌جایی ⇒ قطعِ اینترنت یا برق فایلِ
# نیمه نمی‌گذارد و اجرای دوباره از همان‌جا ادامه می‌دهد. پیش از شروع، جای خالیِ دیسک سنجیده می‌شود.
# Hugging Face در دسترس نیست؟  --hf-endpoint https://hf-mirror.com   (یا متغیرِ HF_ENDPOINT)
# سرور اینترنت ندارد؟ روی کامپیوترِ دیگری با --dest بگیرید و پوشه را کپی کنید.
import argparse
import fnmatch
import hashlib
import http.client
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def hf(repo, *patterns, sub="", rev="main"):
    """فایل‌هایی از یک مخزنِ Hugging Face (الگوی * مجاز) ⇒ در پوشهٔ sub. نامِ مسیرِ درونِ مخزن حفظ می‌شود."""
    return {"kind": "hf", "repo": repo, "patterns": list(patterns) or ["*"], "sub": sub, "rev": rev}


def url(u, name, size=None):
    """یک فایلِ مستقیم (GitHub release و …)."""
    return {"kind": "url", "url": u, "name": name, "size": size}


# ─────────────────────────── فهرستِ مدل‌ها ───────────────────────────
# tier: light (CPUِ معمولی، ۸GB RAM) · heavy (سرور: GPUِ NVIDIA یا CPUِ پرهسته)
# needs: tts (گفتار) · clone (کلونِ صدا) · sfx (صدای هر چیز) · helper (کمکی)
MODELS = [
    # ── سبک ──
    dict(id="piper-mana", tier="light", needs="tts", size_mb=64, license="MIT",
         dest="piper/voices",
         note="صدای ششمِ Piper (Mana، سنجیده با MOS) — کنارِ پنج صدای کیت",
         files=[hf("MahtaFetrat/Mana-Persian-Piper", "fa_IR-mana-medium.onnx", "fa_IR-mana-medium.onnx.json")]),
    dict(id="ezafe-albert", tier="light", needs="tts", size_mb=44, license="نامشخص (کارتِ مدل مجوز ندارد)",
         dest="text/ezafe-albert",
         note="پیدا کردنِ کسرهٔ اضافه برای Piper (MOS ۲٫۴۱ ⇒ ۳٫۱۴ در مقالهٔ LCA)",
         files=[hf("abreza/persian-ezafe-albert", "quantized/*")]),
    dict(id="pocket-fa", tier="light", needs="tts,clone", size_mb=490, license="CC-BY-NC-4.0 (فقط غیرتجاری)",
         dest="tts/pocket-fa",
         note="گفتارِ طبیعی‌تر + کلون از ۵ ثانیه صدا، بی torch",
         files=[hf("Nimaone/pocket-tts-farsi-v2-onnx", "*.onnx", "*.onnx.data", "*.npz", "manifest.json", "README.md"),
                hf("mehdi-hf/pocket-tts-farsi-v2", "tokenizer_ph.model", "normalize_fa.py", "model.yaml", "README.md", sub="v2")]),
    dict(id="knn-vc", tier="light", needs="clone", size_mb=1330, license="MIT (با یک بندِ شوخی؛ LICENSE را ببینید)",
         dest="clone/knn-vc",
         note="کلونِ دقیق‌تر از ۵ تا ۱۰ دقیقه صدای خوانده‌شده (روی خروجیِ هر موتورِ گفتار)",
         files=[url("https://github.com/bshall/knn-vc/releases/download/v0.1/WavLM-Large.pt", "WavLM-Large.pt", 1262006081),
                url("https://github.com/bshall/knn-vc/releases/download/v0.1/prematch_g_02500000.pt", "prematch_g_02500000.pt", 66196869)]),
    dict(id="openvoice-v2", tier="light", needs="clone", size_mb=131, license="MIT",
         dest="clone/openvoice-v2",
         note="کلونِ سریع و ارزان (فقط رنگِ صدا) — جایگزینِ سبکِ kNN-VC",
         files=[hf("myshell-ai/OpenVoiceV2", "converter/*")]),
    # DiT: w8a32 (۰٫۴۵GB؛ fp32 ۱٫۸GB است و در RAM همان‌قدر جا می‌گیرد) · رمزگشا: w8a8 (پیش‌فرضِ رسمی، بی افتِ کیفیت)
    dict(id="sa3-small-sfx", tier="light", needs="sfx", size_mb=1130,
         license="Stability AI Community (رایگان زیرِ ۱M$ درآمدِ سالانه) + Gemma Terms",
         dest="sfx/sa3-small",
         note="صدای هر چیز از روی توصیفِ انگلیسی، ۴۴٫۱kHz استریو",
         files=[hf("stabilityai/stable-audio-3-optimized", "tokenizer.model", "LICENSE.md", "LICENSE_GEMMA.md", "NOTICE",
                   "tflite/sa3-sm-sfx/dit_w8a32.tflite", "tflite/t5gemma/encoder_fp16.tflite", "tflite/same-s/dec_w8a8.tflite")]),
    dict(id="m2m100-ct2", tier="light", needs="helper", size_mb=500, license="MIT",
         dest="text/m2m100-ct2",
         note="ترجمهٔ توصیفِ فارسیِ صدا به انگلیسی برای sa3 (CTranslate2 int8)",
         files=[hf("jncraton/m2m100_418M-ct2-int8")]),

    # ── سنگین (سرور) ── Stable Audio 3 با PyTorch از کشِ Hugging Face بار می‌شود ⇒ با «hf download» (VOICE-SETUP.md ۵٫۳)
    dict(id="omnivoice", tier="heavy", needs="tts,clone", size_mb=3270, license="وزن‌ها CC-BY-NC (کد Apache-2.0)",
         dest="tts/omnivoice",
         note="طبیعی‌ترین فارسیِ سنجیده (CER ۱٫۹۰ در برابرِ ۱٫۵۷ِ صدای واقعی)؛ کلون از ۳ تا ۱۰ ثانیه؛ GPU",
         files=[hf("k2-fsa/OmniVoice")]),
    dict(id="omnivoice-gguf", tier="heavy", needs="tts,clone", size_mb=945, license="CC-BY-NC",
         dest="tts/omnivoice-gguf",
         note="همان OmniVoice برای CPUِ پرهسته با omnivoice.cpp (سرعتِ CPU سنجیده نشده)",
         files=[hf("Serveurperso/OmniVoice-GGUF", "omnivoice-base-Q8_0.gguf", "omnivoice-tokenizer-Q8_0.gguf", "README.md")]),
    dict(id="chatterbox-fa", tier="heavy", needs="tts,clone", size_mb=3210, license="CC-BY-NC-4.0 · gated (قبولِ شرایط در سایت)",
         dest="tts/chatterbox-fa",
         note="Chatterbox فارسی؛ کلون از ۳ تا ۱۰ ثانیه؛ نشانِ پنهانِ Perth در خروجی؛ GPU",
         files=[hf("ResembleAI/chatterbox", "ve.pt", "s3gen.pt", "grapheme_mtl_merged_expanded_v1.json", "conds.pt", "Cangjie5_TC.json"),
                hf("Thomcles/Chatterbox-TTS-Persian-Farsi", "t3_fa.safetensors", "LICENCE", "README.md")]),
    dict(id="parsvoice-xtts", tier="heavy", needs="tts,clone", size_mb=5670, license="CPML (غیرتجاری) · gated",
         dest="tts/parsvoice-xtts",
         note="XTTS آموزش‌دیده روی ۲۲۰۰ ساعت فارسی (MOS ۳٫۶)؛ کلون از ۶ تا ۱۵ ثانیه؛ GPU",
         files=[hf("MohammadJRanjbar/ParsVoice-XTTS", "model.pth", "config.json", "vocab.json", "README.md")]),
    dict(id="moss-realtime-fa", tier="heavy", needs="tts,clone", size_mb=11830, license="Apache-2.0 (تجاری مجاز)",
         dest="tts/moss-realtime-fa",
         note="تنها گزینهٔ کلون‌دار با مجوزِ تجاری؛ کلون از ۱۰ تا ۳۰ ثانیه؛ کیفیتِ فارسی سنجیده نشده؛ GPU",
         files=[hf("OpenMOSS-Team/MOSS-TTS-Realtime", sub="base"),
                hf("hamidfzm/MOSS-TTS-Realtime-Persian-lora", sub="lora"),
                hf("OpenMOSS-Team/MOSS-Audio-Tokenizer", "*.safetensors", "*.json", "*.py", "README.md", sub="codec")]),
    dict(id="piper-train-base", tier="heavy", needs="clone", size_mb=850, license="MIT (دادهٔ Mana: CC0)",
         dest="train/piper-mana",
         note="نقطهٔ شروعِ آموزشِ صدای Piperِ اختصاصی روی GPU (piper1-gpl)",
         files=[hf("MahtaFetrat/Mana-Persian-Piper", "ckpt/*", "fa_IR-mana-medium.onnx.json")]),
    dict(id="piper-train-base-gyro", tier="heavy", needs="clone", size_mb=850, license="MIT",
         dest="train/piper-gyro",
         note="نقطهٔ شروعِ دیگر (gyro، فونم‌های espeak) — اگر Mana با فونم‌سازِ espeak جور نشد",
         files=[hf("gyroing/Persian-Piper-Model-gyro", "1145-last.ckpt", "*.json")]),
]


class Gated(Exception):
    pass


# ─────────────────────────── کمکی ───────────────────────────

def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024.0


def request(u, token=None, method="GET", headers=None):
    h = {"User-Agent": "PersianAiKit-downloader/1.0"}
    if token and ("huggingface" in u or "hf-mirror" in u):
        h["Authorization"] = "Bearer " + token
    h.update(headers or {})
    return urllib.request.Request(u, method=method, headers=h)


def hf_tree(endpoint, repo, rev, token):
    """همهٔ فایل‌های مخزن با اندازه و SHA-256 (فایل‌های LFS)."""
    u = f"{endpoint}/api/models/{repo}/tree/{urllib.parse.quote(rev)}?recursive=true"
    files = []
    while u:                                   # فهرستِ بلند چند صفحه است (سرآیندِ Link)
        for attempt in range(1, 6):
            try:
                with urllib.request.urlopen(request(u, token), timeout=60) as r:
                    items = json.load(r)
                    nxt = re.search(r'<([^>]+)>;\s*rel="next"', r.headers.get("Link") or "")
                break
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise Gated(f"{repo}: دسترسی نیست (gated) — در huggingface.co/{repo} شرایط را بپذیرید و --token بگذارید.")
                if e.code == 404:
                    raise SystemExit(f"✗ {repo}: مخزن پیدا نشد (نامش عوض شده یا پاک شده).")
                err = e
            except (urllib.error.URLError, http.client.HTTPException, ConnectionError, TimeoutError, ValueError) as e:
                err = e                        # ValueError: JSONِ نیمه‌کاره
            print(f"    فهرستِ {repo} نیامد ({err!r}); تلاشِ {attempt} از ۵ …")
            time.sleep(min(30, 3 * attempt))
        else:
            raise SystemExit(f"✗ {repo}: فهرستِ فایل‌ها گرفته نشد — اینترنت یا --hf-endpoint را وارسی کنید.")
        files += [i for i in items if i.get("type") == "file"]
        u = nxt.group(1) if nxt else None
    return files


def plan(model, endpoint, token):
    """مدل ⇒ فهرستِ (نشانی، مسیرِ مقصد، اندازه، sha256)."""
    out = []
    for f in model["files"]:
        if f["kind"] == "url":
            out.append((f["url"], f["name"], f["size"], None))
            continue
        tree = hf_tree(endpoint, f["repo"], f["rev"], token)
        picked = [t for t in tree if any(fnmatch.fnmatch(t["path"], p) for p in f["patterns"])]
        if not picked:
            raise SystemExit(f"✗ {model['id']}: در {f['repo']} فایلی با {f['patterns']} نیست (مخزن عوض شده؟)")
        for t in picked:
            sha = (t.get("lfs") or {}).get("oid")
            src = f"{endpoint}/{f['repo']}/resolve/{urllib.parse.quote(f['rev'])}/{urllib.parse.quote(t['path'])}"
            rel = str(Path(f["sub"]) / t["path"]) if f["sub"] else t["path"]
            out.append((src, rel, t.get("size"), sha))
    return out


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(src, dst, size, sha, token):
    """دانلود با ادامه از جای قطع (.part + Range)، وارسیِ اندازه و sha256، بعد جابه‌جایی."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and (size is None or dst.stat().st_size == size):
        return "هست"
    part = dst.with_name(dst.name + ".part")
    for attempt in range(1, 6):
        have = part.stat().st_size if part.exists() else 0
        if size is not None and have > size:
            part.unlink()
            have = 0
        if size is not None and have == size:   # دفعهٔ قبل تمام شد ولی جابه‌جا نشد
            break
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with urllib.request.urlopen(request(src, token, headers=headers), timeout=60) as r:
                if have and r.status != 206:           # سرور ادامه را نپذیرفت ⇒ از اول
                    have = 0
                mode = "ab" if have else "wb"
                total = size or (have + int(r.headers.get("Content-Length") or 0)) or None
                t0, done, last = time.time(), have, 0.0
                with open(part, mode) as out:
                    while True:
                        block = r.read(1 << 20)
                        if not block:
                            break
                        out.write(block)
                        done += len(block)
                        now = time.time()
                        if now - last > 2:
                            speed = (done - have) / max(now - t0, 1e-6)
                            pct = f"{100 * done / total:5.1f}%" if total else ""
                            print(f"\r    {dst.name}: {human(done)} {pct}  {human(speed)}/s   ", end="", flush=True)
                            last = now
            print()
            break
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise SystemExit(f"✗ {dst.name}: دسترسی نیست (gated) — در سایتِ Hugging Face شرایطِ این مدل را بپذیرید و --token بگذارید.")
            if e.code == 416:                    # .part از قبل کامل بود
                break
            print(f"\n    خطای {e.code}; تلاشِ {attempt} از ۵ …")
            time.sleep(min(30, 3 * attempt))
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError, OSError) as e:
            if isinstance(e, OSError) and getattr(e, "errno", None) == 28:
                raise SystemExit("✗ دیسک پر شد. فایلِ .part می‌ماند؛ بعد از آزاد کردنِ جا دوباره اجرا کنید.")
            print(f"\n    قطع شد ({e}); تلاشِ {attempt} از ۵ …")
            time.sleep(min(30, 3 * attempt))
    else:
        raise SystemExit(f"✗ {dst.name} دانلود نشد.")
    if size is not None and part.stat().st_size != size:
        raise SystemExit(f"✗ {dst.name}: اندازه {part.stat().st_size} است، باید {size} باشد — دوباره اجرا کنید.")
    if sha and sha256_of(part) != sha:
        part.unlink()
        raise SystemExit(f"✗ {dst.name}: SHA-256 نمی‌خورد (فایل خراب بود و پاک شد) — دوباره اجرا کنید.")
    os.replace(part, dst)
    return "گرفته شد"


def main():
    ap = argparse.ArgumentParser(description="دانلودِ مدل‌های صدای PersianAiKit (راهنما: VOICE-SETUP.md)")
    ap.add_argument("--tier", choices=["light", "heavy", "all"], help="کدام سطح")
    ap.add_argument("--only", help="فقط این‌ها (شناسه‌ها با ویرگول)")
    ap.add_argument("--list", action="store_true", help="فقط فهرست")
    ap.add_argument("--dry-run", action="store_true", help="فقط وارسیِ لینک‌ها و جای دیسک، بی دانلود")
    ap.add_argument("--dest", default=str(ROOT / "models"), help="پوشهٔ مدل‌ها (پیش‌فرض: models کنارِ پروژه)")
    ap.add_argument("--hf-endpoint", default=os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/"))
    ap.add_argument("--token", default=os.environ.get("HF_TOKEN"), help="توکنِ Hugging Face برای مدل‌های gated")
    a = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    chosen = MODELS
    if a.only:
        ids = {x.strip() for x in a.only.split(",") if x.strip()}
        unknown = ids - {m["id"] for m in MODELS}
        if unknown:
            raise SystemExit("شناسهٔ ناشناخته: " + ", ".join(sorted(unknown)) + " — فهرست: --list")
        chosen = [m for m in MODELS if m["id"] in ids]
    elif a.tier and a.tier != "all":
        chosen = [m for m in MODELS if m["tier"] == a.tier]
    elif not a.tier and not a.list:
        ap.error("--tier یا --only یا --list لازم است")

    if a.list:
        for m in chosen:
            print(f"{m['id']:22s} {m['tier']:6s} {m['needs']:10s} ~{m['size_mb']:>6} MB  {m['license']}\n{'':22s} {m['note']}")
        return

    dest = Path(a.dest).resolve()
    jobs, need = [], 0
    for m in chosen:
        try:
            files = plan(m, a.hf_endpoint, a.token)
        except Gated as e:
            if not a.dry_run:
                raise SystemExit("✗ " + str(e))
            print(f"⚠ {m['id']:22s} {e}")
            continue
        for src, rel, size, sha in files:
            target = dest / m["dest"] / rel
            if not (target.exists() and size is not None and target.stat().st_size == size):
                need += size or 0
            jobs.append((m, src, target, size, sha))
        print(f"✓ {m['id']:22s} {len(files)} فایل، {human(sum(s or 0 for _, _, s, _ in files))} — {m['license']}")

    dest.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(dest).free
    margin = 2 * 1024 ** 3   # ویندوز برای حافظهٔ مجازی هم جا لازم دارد
    print(f"\nلازم: {human(need)} · آزاد: {human(free)} در {dest}")
    if need + margin > free:
        raise SystemExit(f"✗ جا کم است: دست‌کم {human(need + margin)} آزاد لازم است (۲GB حاشیه برای ویندوز).")
    if a.dry_run:
        print("وارسی تمام شد (بی دانلود).")
        return
    for m, src, target, size, sha in jobs:
        state = fetch(src, target, size, sha, a.token)
        print(f"  {state:9s} {m['id']}/{target.relative_to(dest / m['dest'])}")
    print("\nتمام شد ✓")


if __name__ == "__main__":
    main()
