"""آزمونِ متن و بینایی با Ollama روی کارت (مدل‌های خودِ مالک؛ هیچ مدلی عوض نمی‌شود)."""
from . import Spec, SelfTest, Verdict, caps_ok, png, register

TEXT_PREFERENCE = ("qwen3:8b", "qwen3:4b", "qwen2.5:7b", "llama3.1:8b", "llama3.2", "gemma3:4b", "gemma3", "mistral", "qwen3")
BIG_HINTS = ("32b", "30b", "70b", "72b", "coder", "-vl", "vl:", "vision", "llava", "embed")
VISION_HINTS = ("-vl", "vl:", "vl-", "vision", "llava", "minicpm-v", "moondream", "gemma3", "llama4")
VISION_PREFERENCE = ("qwen3-vl:8b", "qwen3-vl:4b", "qwen2.5vl:7b", "qwen2.5vl", "llava", "minicpm-v", "gemma3", "qwen3-vl:30b", "qwen3-vl")


def pick_text(models: list[str], configured: str = "") -> str:
    if configured and configured in models:
        return configured
    for pref in TEXT_PREFERENCE:
        for m in models:
            if m == pref or m.startswith(pref):
                if not any(h in m.lower() for h in BIG_HINTS):
                    return m
    small = [m for m in models if not any(h in m.lower() for h in BIG_HINTS)]
    return (small or models or [""])[0]


def vision_models(models: list[str]) -> list[str]:
    return [m for m in models if any(h in m.lower() for h in VISION_HINTS)]


def pick_vision(models: list[str], configured: str = "") -> str:
    vm = vision_models(models)
    if configured and configured in vm:
        return configured
    for pref in VISION_PREFERENCE:
        for m in vm:
            if m == pref or m.startswith(pref):
                return m
    return (vm or [""])[0]


def _configured(kind: str) -> str:
    try:
        from services.ai import priority

        cfg = priority.config()
        return priority.local_model(priority.VISION if kind == "vision" else priority.TEXT, cfg) or ""
    except Exception:  # noqa: BLE001
        return ""


def _text_available(node):
    ok, why = caps_ok(node, "ollama", why="Ollama روی این سرور نیست")
    if not ok:
        return ok, why
    models = [m for m in (node.capabilities or {}).get("ollama_models") or [] if isinstance(m, str)]
    return (True, "") if models else (False, "هیچ مدلی در Ollamaی این سرور نصب نیست")


def _vision_available(node):
    ok, why = _text_available(node)
    if not ok:
        return ok, why
    models = [m for m in (node.capabilities or {}).get("ollama_models") or [] if isinstance(m, str)]
    return (True, "") if vision_models(models) else (False, "مدلِ بینایی (مثل qwen3-vl) روی این سرور نصب نیست")


#: متنِ آزمون از واقعیت‌های برندِ «چغر» (docs/chagher/brand-facts-fa.md)؛ از مدل می‌خواهیم عدد و قیمت نیاورد
CHAGHER_PROMPT = ("«چغر» دستیار هوش مصنوعیِ مربی‌های ورزشی است و برنامهٔ ورزشی و غذاییِ هر ورزشکار را پیش‌نویس می‌کند؛ شعارش «با چغر چغرتر شو» است. "
                  "یک جملهٔ تبلیغاتیِ فارسیِ کوتاه برای معرفیِ چغر به مربی‌ها بنویس. عدد و قیمت نیاور.")


def persian_letters(text: str) -> int:
    return sum(1 for ch in text if 0x600 <= ord(ch) <= 0x6ff and ch.isalpha())


def build_text(ctx):
    model = pick_text(ctx.installed_ollama(), _configured("text"))
    return Spec("ollama.generate", {"model": model, "prompt": CHAGHER_PROMPT, "stream": False,
                                    "think": False, "options": {"num_predict": 160, "temperature": 0.2}},
                timeout_s=1500)


def _tps(data: dict):
    try:
        return round(data["eval_count"] / (data["eval_duration"] / 1e9), 1)
    except (KeyError, TypeError, ZeroDivisionError):
        return None


def check_text(ctx, job):
    data = ctx.read_json(job, "ollama.json")
    if not isinstance(data, dict):
        return Verdict.failed("جوابِ ollama.json نرسید.")
    text = str(data.get("response") or (data.get("message") or {}).get("content") or "").strip()
    meta = ctx.meta(job)
    if len(text) < 2:
        return Verdict.failed("مدلِ «%s» جوابِ خالی داد." % (job.payload or {}).get("model"), device=meta.get("device", ""))
    if persian_letters(text) < 6:
        return Verdict.failed("جوابِ مدلِ «%s» فارسی نیست یا خیلی کوتاه است: «%s»" % ((job.payload or {}).get("model"), text[:60]),
                              device=meta.get("device", ""))
    tps = _tps(data)
    detail = "«%s» · %s" % ((job.payload or {}).get("model"), text[:80].replace("\n", " "))
    if tps:
        detail += " · %s توکن در ثانیه" % tps
    return Verdict.passed(detail, extra={"tokens_per_s": tps, "num_ctx": meta.get("num_ctx")})


def build_vision(ctx):
    model = pick_vision(ctx.installed_ollama(), _configured("vision"))
    return Spec("ollama.generate", {"model": model, "prompt": "What is the main color of the big square in this picture? Answer with one word.",
                                    "images": ["selftest.png"], "stream": False, "think": False,
                                    "options": {"num_predict": 40, "temperature": 0}},
                files={"selftest.png": png("square")}, timeout_s=1800)


def check_vision(ctx, job):
    data = ctx.read_json(job, "ollama.json")
    if not isinstance(data, dict):
        return Verdict.failed("جوابِ ollama.json نرسید.")
    text = str(data.get("response") or (data.get("message") or {}).get("content") or "").strip().lower()
    if "red" in text or "قرمز" in text:
        return Verdict.passed("«%s» رنگِ مربع را «%s» تشخیص داد" % ((job.payload or {}).get("model"), text[:30]))
    return Verdict.failed("مدلِ بینایی رنگِ مربعِ قرمز را درست نگفت: «%s»" % text[:60])


register(SelfTest(key="ollama_text", label="متنِ هوشمند با Ollama (مدلِ خودِ شما)", group="text", kind="ollama.generate",
                  build=build_text, check=check_text, available=_text_available, gpu_required=True, order=30,
                  requeue={"kinds": ("ollama.generate", "ollama.chat")}, describe="یک جمله با مدلِ متنیِ کوچک؛ باید روی کارت اجرا شود"))
register(SelfTest(key="ollama_vision", label="بینایی با Ollama (qwen3-vl)", group="text", kind="ollama.generate",
                  build=build_vision, check=check_vision, available=_vision_available, gpu_required=False, order=31,
                  requeue={"kinds": ("ollama.generate", "ollama.chat")}, describe="رنگِ یک مربع را از روی عکس می‌گوید"))
