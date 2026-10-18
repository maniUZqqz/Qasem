"""
Stand-ins for Ollama and ComfyUI, used by `python manage.py selftest`.

The point is NOT to pretend the models work. It is to reproduce the ways local
models actually misbehave, so the pipeline can be proven to survive them
without a 12 GB card:

* QwQ leaks its chain of thought (`<think>...</think>`) around the answer.
* Models wrap JSON in a ```json fence, or chat before and after it.
* Trailing commas, and a comma missing between two keys — the exact failure
  from the user's own log:
  `json.decoder.JSONDecodeError: Expecting ',' delimiter: line 27 column 4`.
* Output cut off mid-JSON when the token budget runs out.
* Qwen3-VL in JSON mode sometimes returns `response: ""` with the JSON inside
  `thinking` (this quirk is already handled in services/ai/ollama.py).
* A model that answers with valid JSON that is missing half the keys.
* A model that fails outright (HTTP 500), the way an out-of-VRAM run does.

ComfyUI is faked to the letter of services/comfyui/client.py: /upload/image,
/prompt, a /history that is empty for the first polls, /view that returns a
REAL png or mp4 (so ffmpeg's last-frame extraction and concat run for real),
and /free.

Run standalone for manual poking:
    python tools/fake_ai_stack.py 11500 8500
"""

import json
import re
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# --------------------------------------------------------------------------
# what a good answer looks like for each prompt the app sends
# --------------------------------------------------------------------------

VISION = {
    "what_is_visible": "هدفون بی‌سیم مشکی روی سطح ساده، هدبند پارچه‌ای و گوشی‌های بزرگ",
    "photo_quality": "متوسط؛ رزولوشن پایین و کمی نرم",
    "background": "ساده و روشن بدون عناصر مزاحم",
    "lighting": "یکنواخت اما بدون برجسته‌سازی جزئیات",
    "strengths": ["محصول کامل در قاب است", "پس‌زمینه تمیز"],
    "problems": ["رزولوشن پایین", "بازتاب نور روی بدنه"],
    "instagram_ready": False,
}

INTELLIGENCE = {
    "summary": "هدفون بی‌سیم میان‌رده با باتری بلند و نویز کنسلینگ فعال، مناسب استفاده روزمره و کاری.",
    "target_audience": [
        "دانشجویانی که در محیط شلوغ مطالعه می‌کنند",
        "کارمندان دورکار با جلسات آنلاین طولانی",
        "مسافران پروازهای چندساعته",
        "ورزشکاران باشگاهی",
    ],
    "selling_points": [
        "باتری ۴۰ ساعته یعنی یک هفته کاری بدون شارژ",
        "نویز کنسلینگ فعال برای محیط شلوغ",
        "وزن سبک برای استفاده چندساعته",
        "بلوتوث ۵.۳ با اتصال پایدار",
    ],
    "weaknesses": [
        "قیمت بالاتر از مدل‌های بی‌نام مشابه",
        "بدنه پلاستیکی به‌جای فلز",
        "کیف حمل سخت همراه محصول نیست",
        "تنوع رنگ محدود",
    ],
    "objections": [
        "قیمتش نسبت به مدل‌های مشابه زیاد نیست؟",
        "باتریش واقعاً ۴۰ ساعت دوام میاره؟",
        "برای ورزش مناسبه یا از گوش می‌افته؟",
        "گارانتی و خدمات پس از فروش داره؟",
    ],
    "marketing_angles": [
        "یک بار شارژ برای یک هفته کاری",
        "سکوت در محیط شلوغ",
        "سبک برای تمام روز",
        "قیمت منصفانه در برابر برندهای گران",
    ],
    "positioning": "گزینه میان‌ردهٔ کسی که باتری بلند و نویز کنسلینگ می‌خواهد بدون پرداخت هزینهٔ برندهای گران.",
    "recommended_tone": "صمیمی، مطمئن و بدون اغراق",
    "content_ideas": [
        "ریلز: تست باتری در طول یک هفتهٔ کاری",
        "پست: مقایسهٔ وزن با هدفون معمولی روی ترازو",
        "استوری: نظرسنجی دربارهٔ آزاردهنده‌ترین صدای محیط",
        "کاروسل: چهار موقعیت روزمرهٔ استفاده",
    ],
    "use_cases": [
        "پروازهای طولانی",
        "مطالعه در کافه",
        "تماس‌های کاری در خانه",
        "دویدن سبک در پارک",
    ],
}

MARKET = {
    "observations": [
        "دیجی‌کالا: مدل مشابه با باتری ۳۰ ساعته ۲٬۱۰۰٬۰۰۰ تومان",
        "ترب: پایین‌ترین قیمت رده ۱٬۸۵۰٬۰۰۰ تومان",
    ],
    "competitors": [
        {
            "name": "فروشگاه صوتی الف",
            "brand": "AudioX",
            "product": "هدفون AX-7",
            "price": "۲٬۱۰۰٬۰۰۰ تومان (دیجی‌کالا)",
            "where_sells": "دیجی‌کالا و اینستاگرام",
            "how_sells": "تخفیف دوره‌ای و ارسال رایگان",
            "strengths": ["قیمت پایین‌تر", "حضور قوی در دیجی‌کالا"],
            "weaknesses": ["باتری کمتر", "بدون نویز کنسلینگ فعال"],
            "source": "digikala",
        },
        {
            "name": "صوت‌گستر",
            "brand": "SoundLine",
            "product": "SL-Pro 2",
            "price": "۲٬۹۰۰٬۰۰۰ تومان (ترب)",
            "where_sells": "سایت اختصاصی",
            "how_sells": "تمرکز بر گارانتی ۱۸ ماهه",
            "strengths": ["گارانتی طولانی‌تر"],
            "weaknesses": ["گران‌تر از ما"],
            "source": "torob",
        },
    ],
    "comparison": [
        "باتری ما ۴۰ ساعت در برابر ۳۰ ساعت AX-7 — برتری ما",
        "قیمت ما ۳۵۰ هزار تومان بالاتر از AX-7 — نقطهٔ ضعف ما",
        "نویز کنسلینگ فعال داریم و AX-7 ندارد — برتری قابل نمایش",
        "گارانتی SL-Pro 2 طولانی‌تر است — باید پاسخ داشته باشیم",
    ],
    "competitor_positioning": ["احتمالاً AX-7 روی قیمت تمرکز دارد", "SL-Pro 2 روی گارانتی"],
    "common_messaging": ["تاکید بر ارسال رایگان", "تضمین اصالت کالا"],
    "content_patterns": ["ویدیوی آنباکسینگ", "مقایسهٔ کنار هم"],
    "pricing_observations": ["۲٬۱۰۰٬۰۰۰ تومان (دیجی‌کالا)", "۱٬۸۵۰٬۰۰۰ تومان (ترب)"],
    "common_customer_concerns": ["اصالت کالا", "مدت گارانتی"],
    "content_gaps": ["تست واقعی باتری در شرایط روزمره", "توضیح نویز کنسلینگ به زبان ساده"],
    "differentiation_opportunities": [
        "گارانتی تعویض ۷ روزهٔ بی‌قید و شرط",
        "ویدیوی تست باتری هفتگی به‌عنوان مدرک",
    ],
    "strategy_summary": (
        "روی «یک هفته بدون شارژ» به‌عنوان پیام اصلی تمرکز کنید و اختلاف قیمت با AX-7 "
        "را با باتری بلندتر و نویز کنسلینگ توجیه کنید. برای پاسخ به SL-Pro 2 یک "
        "گارانتی تعویض کوتاه‌مدت اضافه کنید."
    ),
    "confidence": "MEDIUM",
}

CAPTIONS = {
    "captions": [
        {
            "platform": "INSTAGRAM",
            "short": "چند بار در هفته هدفونت رو شارژ می‌کنی؟ 🔋",
            "medium": "۴۰ ساعت پخش یعنی یک هفتهٔ کاری کامل بدون کابل. 🎧",
            "long": "دوشنبه شارژ کردی، جمعه هنوز روشنه.\\nباتری ۴۰ ساعته و نویز کنسلینگ فعال.",
            "hashtags": ["#هدفون", "#بلوتوث", "#تک‌لند"],
            "cta": "برای سفارش دایرکت بده",
        },
        {
            "platform": "TELEGRAM",
            "short": "۴۰ ساعت پخش با یک بار شارژ",
            "medium": "هدفون TK-900 با نویز کنسلینگ فعال و باتری ۴۰ ساعته موجود شد.",
            "long": "مشخصات کامل TK-900:\\n- باتری ۴۰ ساعته\\n- نویز کنسلینگ فعال\\n- بلوتوث ۵.۳",
            "hashtags": ["#هدفون", "#TK900"],
            "cta": "برای ثبت سفارش روی لینک بزنید",
        },
        {
            "platform": "LINKEDIN",
            "short": "تمرکز در دفتر باز، بدون قطع تماس",
            "medium": "برای جلسات آنلاین طولانی، باتری بلند مهم‌تر از هر مشخصهٔ دیگری است.",
            "long": "در دفاتر باز، نویز محیط بزرگ‌ترین دشمن تمرکز است. TK-900 با نویز کنسلینگ فعال و باتری ۴۰ ساعته برای یک روز کاری کامل طراحی شده.",
            "hashtags": ["#بهره‌وری", "#دورکاری"],
            "cta": "برای مشاورهٔ خرید سازمانی پیام بدهید",
        },
    ]
}

IMAGE_DIRECTION = {
    "concept_fa": "هدفون روی سطح تیره با نور کناری گرم؛ تمرکز کامل روی خود محصول.",
    "prompt_en": (
        "the exact same product, unchanged, wireless over-ear headphones on a dark "
        "matte surface, warm rim light, shallow depth of field, ultra sharp focus, "
        "fine surface texture, professional studio lighting, high dynamic range, "
        "8k product photography, no text, no letters, no typography"
    ),
    "negative_en": (
        "blurry, soft focus, low resolution, pixelated, jpeg artifacts, noise, "
        "text, letters, words, typography, watermark, deformed product"
    ),
    "headline_fa": "یک هفته بدون شارژ",
    "subline_fa": "باتری ۴۰ ساعته با نویز کنسلینگ فعال",
}

VIDEO_SCRIPT = {
    "concept": "سه صحنهٔ کوتاه که باتری بلند هدفون را نشان می‌دهد.",
    "cta": "همین حالا از تک‌لند سفارش بده",
    "scenes": [
        {
            "index": 1,
            "duration": 5,
            "visual_prompt": (
                "the exact same wireless headphones on a dark desk beside a laptop, "
                "warm morning light, sharp focus, no text, no letters, no logos"
            ),
            "motion_prompt": "slow push-in",
            "narration": "صبح دوشنبه، یک بار شارژ",
            "transition": "NEW_SCENE",
        },
        {
            "index": 2,
            "duration": 5,
            "visual_prompt": (
                "the same headphones worn in a busy cafe, background softly blurred, "
                "sharp focus on the product, no text, no letters, no logos"
            ),
            "motion_prompt": "gentle orbit to the right",
            "narration": "چهل ساعت پخش بدون قطع شدن",
            "transition": "CONTINUE",
        },
        {
            "index": 3,
            "duration": 5,
            "visual_prompt": (
                "the same headphones back on the desk at night, warm lamp light, "
                "sharp focus, no text, no letters, no logos"
            ),
            "motion_prompt": "slow tilt up",
            "narration": "جمعه هنوز روشن است",
            "transition": "CONTINUE",
        },
    ],
}

SALES = {
    "reply": "سلام! هدفون TK-900 با باتری ۴۰ ساعته ۲٬۴۵۰٬۰۰۰ تومان است و موجود داریم.",
    "action": "ANSWER",
    "product_ids": [],
    "order": None,
    "handoff_reason": "",
}

# The customer message and the catalog both sit inside the sales prompt, so the
# fake can answer the way a real agent would: buying words produce an order
# request, paying words a payment request, a complaint a ticket. Everything the
# fake proposes is still validated in code against the database, which is
# exactly the behaviour under test.
CUSTOMER_MESSAGE_RE = re.compile(
    r"NEW CUSTOMER MESSAGE:\n(.*?)\n\nRespond with", re.DOTALL
)
CATALOG_ID_RE = re.compile(r'"id":(\d+)')

SALES_TRIGGERS = (
    (("می‌خرم", "میخرم", "سفارش بده", "ثبت کن", "همین رو می‌خواهم"), "CREATE_ORDER"),
    (("پرداخت", "کارت", "واریز", "چطور پول"), "REQUEST_PAYMENT"),
    (("خراب", "شکسته", "شکایت", "مشکل دارم"), "CREATE_TICKET"),
    (("تخفیف ویژه", "استثنا", "قیمت خاص"), "ESCALATE"),
)


def sales_answer(prompt: str) -> dict:
    """A sales turn that reacts to what the customer actually said."""
    message_match = CUSTOMER_MESSAGE_RE.search(prompt)
    message = message_match.group(1).strip() if message_match else ""
    catalog_ids = [int(i) for i in CATALOG_ID_RE.findall(prompt)]
    first_id = catalog_ids[0] if catalog_ids else None

    action = "ANSWER"
    for needles, candidate in SALES_TRIGGERS:
        if any(needle in message for needle in needles):
            action = candidate
            break

    answer = {
        "reply": "سلام! هدفون TK-900 با باتری ۴۰ ساعته ۲٬۴۵۰٬۰۰۰ تومان است و موجود داریم.",
        "intent": "PRODUCT_QUESTION",
        "action": action,
        "product_ids": [first_id] if first_id else [],
        "order": None,
        "ticket": None,
        "confidence": "HIGH",
        "needs_human": action == "ESCALATE",
    }
    if action == "CREATE_ORDER" and first_id:
        answer["reply"] = "عالی! یک عدد برایتان ثبت شد. برای نهایی‌کردن، مرحلهٔ پرداخت را می‌فرستم."
        answer["intent"] = "PURCHASE"
        answer["order"] = {"product_id": first_id, "variant_id": None, "quantity": 1}
    elif action == "REQUEST_PAYMENT":
        answer["reply"] = "مبلغ را به شمارهٔ کارت اعلام‌شده واریز کنید و عکس رسید را همین‌جا بفرستید."
        answer["intent"] = "PAYMENT"
    elif action == "CREATE_TICKET":
        answer["reply"] = "بابت این مشکل متأسفم. موضوع را ثبت کردم تا همکارانم پیگیری کنند."
        answer["intent"] = "COMPLAINT"
        answer["ticket"] = {
            "subject": "محصول آسیب‌دیده رسیده است",
            "description": message[:300] or "مشتری از آسیب‌دیدگی محصول گزارش داده است.",
            "urgent": True,
        }
    elif action == "ESCALATE":
        answer["reply"] = "این مورد را باید همکار انسانی بررسی کند؛ ارجاع دادم."
        answer["intent"] = "OTHER"
    return answer

INCOMPLETE = {"summary": "فقط یک خلاصهٔ ناقص بدون بقیهٔ کلیدها"}


#: Segment QC (services.video.qc): a clean verdict with the observed state the
#: continuity engine feeds forward. The simulator answers the categorical form
#: so the vision path is exercised end to end rather than falling back to
#: "nobody looked".
SEGMENT_QC = {
    "character_consistency": {"verdict": "ok", "note": "no person in the frames"},
    "object_consistency": {"verdict": "ok", "note": "same product in every frame"},
    "anatomy": {"verdict": "ok", "note": "no hands visible"},
    "artifacts": {"verdict": "ok", "note": ""},
    "observed": {
        "product_colours": ["cream", "beige"],
        "clothing": [],
        "background": "plain studio backdrop, soft light",
        "people": 0,
    },
    "notes": "",
}


def answer_for(prompt: str, system: str):
    """Pick the answer that matches the prompt actually being asked."""
    text = f"{system}\n{prompt}"
    if "object_consistency" in text and "character_consistency" in text:
        return SEGMENT_QC
    if "analyzing a product photo" in text:
        return VISION
    if "market and competitor analysis" in text:
        return MARKET
    if "social-media captions" in text:
        return CAPTIONS
    if "Design one image" in text or "creative director" in text:
        return IMAGE_DIRECTION
    if "advertising video script" in text or "video director" in text:
        return VIDEO_SCRIPT
    if "product_ids" in text or "handoff_reason" in text:
        return sales_answer(text)
    return INTELLIGENCE


def kind_of(prompt: str, system: str) -> str:
    text = f"{system}\n{prompt}"
    for needle, name in (
        ("analyzing a product photo", "vision"),
        ("market and competitor analysis", "market"),
        ("social-media captions", "captions"),
        ("Design one image", "image"),
        ("advertising video script", "video_script"),
        ("handoff_reason", "sales"),
    ):
        if needle in text:
            return name
    return "intelligence"


# --------------------------------------------------------------------------
# the ways a real local model mangles its own answer
# --------------------------------------------------------------------------

THINK_BLOCK = (
    "<think>\nOkay, the user wants a JSON object. Let me look at the product data.\n"
    "The price is given, so I must not invent a different one. I should keep every\n"
    "list to four items and write everything in Persian. Let me draft the summary\n"
    "first, then the audience, then the selling points...\n</think>\n\n"
)


def _break_a_comma(payload: str) -> str:
    """Delete the comma between two keys — the exact error from the real log."""
    matches = list(re.finditer(r'",\s*"', payload))
    if len(matches) < 3:
        return payload
    hit = matches[len(matches) // 2]
    return payload[: hit.start()] + '"\n    "' + payload[hit.end() :]


def shorten(answer):
    """What a model really returns when told its last answer was too long.

    Mirrors the instruction the app actually sends ("at most 3 items per list,
    one short sentence per string"): shorter, but still structurally complete —
    a real model does not drop a requested platform or scene to save room.
    """
    if isinstance(answer, dict):
        return {k: shorten(v) for k, v in answer.items()}
    if isinstance(answer, list):
        return [shorten(v) for v in answer[:3]]
    if isinstance(answer, str) and len(answer) > 80:
        return answer[:78].rstrip() + "…"
    return answer


def render(answer: dict, style: str) -> tuple[str, str]:
    """Return (response_field, thinking_field) the way `style` would emit them."""
    clean = json.dumps(answer, ensure_ascii=False, indent=2)

    if style == "clean":
        return clean, ""
    if style == "think":
        return THINK_BLOCK + clean, "the reasoning also shows up here"
    if style == "fenced":
        return "```json\n" + clean + "\n```", ""
    if style == "prose":
        return (
            "Sure! Here is the JSON you asked for:\n\n"
            + clean
            + "\n\nLet me know if you want a different tone."
        ), ""
    if style == "trailing_comma":
        return re.sub(r"(\n\s*)\}", r",\1}", clean, count=1), ""
    if style == "missing_comma":
        return _break_a_comma(clean), ""
    if style in ("truncated", "truncated_always"):
        return clean[: int(len(clean) * 0.72)], ""
    if style == "thinking_field":
        # Qwen3-VL + JSON mode: empty response, the JSON lands in `thinking`
        return "", clean
    return clean, ""


class FakeOllama(BaseHTTPRequestHandler):
    """Serves /api/tags, /api/ps and /api/generate."""

    models = [
        {"name": "qwq:32b", "model": "qwq:32b", "size": 19851337728},
        {"name": "qwen3-vl:30b", "model": "qwen3-vl:30b", "size": 19000000000},
        {"name": "qwen3-coder:30b", "model": "qwen3-coder:30b", "size": 18500000000},
        {"name": "nomic-embed-text:latest", "model": "nomic-embed-text:latest", "size": 274000000},
    ]

    # driven by the selftest through POST /_control
    state = {"style": "clean", "first_model_fails": False, "seen": {}, "calls": []}

    def _send(self, payload, code=200, raw=None, content_type="application/json; charset=utf-8"):
        body = raw if raw is not None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/tags":
            self._send({"models": self.models})
        elif path == "/api/ps":
            self._send({"models": []})
        elif path == "/_calls":
            self._send({"calls": self.state["calls"]})
        else:
            self._send({"status": "ok"})

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}

        if path == "/api/embed":
            # deterministic pseudo-vectors: same text -> same vector, different
            # texts -> different direction, so cosine ranking is meaningful
            inputs = payload.get("input") or []
            if isinstance(inputs, str):
                inputs = [inputs]
            self._send({"model": payload.get("model", "?"), "embeddings": [
                embed_vector(text) for text in inputs
            ]})
            return

        if path == "/_control":
            self.state["style"] = payload.get("style", "clean")
            self.state["first_model_fails"] = bool(payload.get("first_model_fails"))
            self.state["seen"] = {}
            self.state["calls"] = []
            self._send({"ok": True, **{k: self.state[k] for k in ("style", "first_model_fails")}})
            return

        prompt = payload.get("prompt", "") or ""
        system = payload.get("system", "") or ""
        model = payload.get("model", "?")

        # an unload ping (`keep_alive: 0`, no prompt) is not a generation
        if not prompt:
            self._send({"model": model, "response": "", "done": True})
            return

        kind = kind_of(prompt, system)
        seen = self.state["seen"]
        seen[kind] = seen.get(kind, 0) + 1
        attempt = seen[kind]
        self.state["calls"].append({"kind": kind, "model": model, "attempt": attempt})

        style = self.state["style"]

        # an out-of-VRAM run is what a 500 from /api/generate really looks like
        if style == "http_500" and attempt == 1:
            self._send({"error": "model requires more system memory than is available"}, code=500)
            return

        # "the first model answers with valid JSON that is missing half the keys"
        if self.state["first_model_fails"] and attempt == 1 and kind != "vision":
            answer = INCOMPLETE
            style = "clean"
        else:
            answer = answer_for(prompt, system)
            # a self-repair round asks the model to fix its own JSON; it should
            # succeed, otherwise the styles that need repair could never pass
            if "INVALID JSON" in prompt:
                style = "clean"
            # told that the last answer was cut off, a real model answers again
            # SHORTER and complete — unless we are simulating a model that just
            # cannot fit the task at all (`truncated_always`)
            elif "cut off because it was too long" in prompt:
                if style == "truncated_always":
                    answer, style = shorten(answer), "truncated"
                else:
                    answer, style = shorten(answer), "clean"

        response_text, thinking = render(answer, style)
        self._send(
            {
                "model": model,
                "response": response_text,
                "thinking": thinking,
                "done": True,
                "done_reason": "length"
                if style in ("truncated", "truncated_always")
                else "stop",
            }
        )

    def log_message(self, *args):
        pass


class FakeComfyUI(BaseHTTPRequestHandler):
    """Serves /upload/image, /prompt, /history/{id}, /view and /free."""

    # filled in by serve(): real bytes so ffmpeg can actually read them
    assets = {"png": b"", "mp4": b""}
    jobs = {}
    lock = threading.Lock()
    POLLS_BEFORE_READY = 1
    # ComfyUI renders at the size the workflow asks for, so the fake must too —
    # otherwise the poster overlay would be tested against the wrong canvas
    SIZE_RE = re.compile(rb'"(width|height)"\s*:\s*(\d+)')
    sizes = {}

    def _send(self, payload, code=200, raw=None, content_type="application/json"):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # what a real ComfyUI reports it can see in its models folder; deliberately
    # includes the underscore spelling from the ROADMAP so `manage.py checkmodels`
    # can be proven to catch a one-character filename mismatch
    installed_models = {
        "CheckpointLoaderSimple": ("ckpt_name", ["FLUX.1 [dev] FP8.safetensors"]),
        "UNETLoader": (
            "unet_name",
            [
                "wan_2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
                "wan_2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
            ],
        ),
        "CLIPLoader": ("clip_name", ["umt5_xxl_fp8_e4m3fn_scaled.safetensors"]),
        "VAELoader": ("vae_name", ["wan_2.1_vae.safetensors"]),
        "LoraLoaderModelOnly": (
            "lora_name",
            ["lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"],
        ),
        # The lip-sync custom node, so services.video.lipsync finds it
        # installed; its output video is the same fake clip as a segment's
        # (the filename prefix contains "segment_").
        "LatentSyncNode": ("seed", []),
    }

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/object_info/"):
            class_type = parsed.path.rsplit("/", 1)[-1]
            entry = self.installed_models.get(class_type)
            if entry is None:
                self._send({})
                return
            field, names = entry
            self._send({class_type: {"input": {"required": {field: [names, {}]}}}})
            return

        if parsed.path.startswith("/history/"):
            prompt_id = parsed.path.rsplit("/", 1)[-1]
            with self.lock:
                job = self.jobs.get(prompt_id)
                if job is None:
                    self._send({})
                    return
                job["polls"] += 1
                if job["polls"] <= self.POLLS_BEFORE_READY:
                    self._send({})  # still running, exactly like ComfyUI
                    return
                filename = job["filename"]
            self._send(
                {
                    prompt_id: {
                        "outputs": {
                            "9": {
                                "images": [
                                    {"filename": filename, "subfolder": "", "type": "output"}
                                ]
                            }
                        },
                        "status": {"completed": True, "status_str": "success"},
                    }
                }
            )
            return

        if parsed.path == "/view":
            name = (parse_qs(parsed.query).get("filename") or [""])[0]
            if name.endswith(".mp4"):
                self._send(None, raw=self.assets["mp4"], content_type="video/mp4")
                return
            with self.lock:
                size = self.sizes.get(name, (832, 480))
            self._send(None, raw=render_png(*size), content_type="image/png")
            return

        self._send({"status": "ok"})

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""

        if parsed.path == "/upload/image":
            # multipart; we only need to answer with a server-side name
            match = re.search(rb'filename="([^"]+)"', body)
            name = match.group(1).decode("utf-8", "replace") if match else "upload.png"
            self._send({"name": name, "subfolder": "", "type": "input"})
            return

        if parsed.path == "/prompt":
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                payload = {}
            text = json.dumps(payload)
            is_video = "segment_" in text
            prompt_id = f"fake-{len(self.jobs) + 1}"
            filename = f"out_{prompt_id}.mp4" if is_video else f"out_{prompt_id}.png"
            found = {k.decode(): int(v) for k, v in self.SIZE_RE.findall(body)}
            size = (found.get("width", 832), found.get("height", 480))
            with self.lock:
                self.jobs[prompt_id] = {"polls": 0, "filename": filename}
                self.sizes[filename] = size
            self._send({"prompt_id": prompt_id, "number": 1, "node_errors": {}})
            return

        if parsed.path == "/free":
            self._send({"ok": True})
            return

        self._send({"status": "ok"})

    def log_message(self, *args):
        pass


# --------------------------------------------------------------------------
# real asset bytes (a png Pillow can open, an mp4 ffmpeg can cut and concat)
# --------------------------------------------------------------------------


def embed_vector(text: str, dimensions: int = 64) -> list[float]:
    """A stable, content-derived unit vector — enough to rank by cosine."""
    import hashlib

    digest = hashlib.sha256((text or "").encode("utf-8")).digest()
    raw = [(digest[i % len(digest)] - 127.5) / 127.5 for i in range(dimensions)]
    norm = sum(v * v for v in raw) ** 0.5 or 1.0
    return [v / norm for v in raw]


def render_png(width: int, height: int) -> bytes:
    """A real PNG at exactly the size the workflow asked for."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), (28, 32, 64))
    draw = ImageDraw.Draw(image)
    for y in range(height):  # a gradient, so an overlay is visibly composited
        draw.line([(0, y), (width, y)], fill=(28 + y * 60 // height, 32, 64 + y * 90 // height))
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def build_assets() -> dict:
    """A real PNG and a real 1s MP4. Falls back to png-only if ffmpeg is absent."""
    tmp = Path(tempfile.mkdtemp(prefix="upmarket-fakecomfy-"))

    mp4_path = tmp / "clip.mp4"
    try:
        # The project's own idea of where ffmpeg is, not whatever happens to be
        # on PATH. On a machine where ffmpeg only exists inside the project
        # folder, a bare "ffmpeg" is not found, the except below quietly turns
        # that into an EMPTY mp4, and every video and voice step downstream then
        # fails with "Invalid data found when processing input" — which reads as
        # a broken pipeline and is really a broken fixture. It cost this test
        # two permanently red steps on the development machine.
        from services.video.ffmpeg import FFMPEG

        subprocess.run(
            [
                FFMPEG, "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=0x1c2040:s=832x480:d=1:r=16",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(mp4_path),
            ],
            check=True,
            capture_output=True,
        )
        mp4 = mp4_path.read_bytes()
    except Exception:
        mp4 = b""
    return {"png": render_png(832, 480), "mp4": mp4}


def serve(ollama_port: int = 11500, comfy_port: int = 8500):
    """Start both fakes on background threads; returns (ollama_url, comfy_url)."""
    FakeComfyUI.assets = build_assets()

    ollama = HTTPServer(("127.0.0.1", ollama_port), FakeOllama)
    comfy = HTTPServer(("127.0.0.1", comfy_port), FakeComfyUI)
    for server in (ollama, comfy):
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
    return (
        f"http://127.0.0.1:{ollama_port}",
        f"http://127.0.0.1:{comfy_port}",
        (ollama, comfy),
    )


if __name__ == "__main__":
    a = int(sys.argv[1]) if len(sys.argv) > 1 else 11500
    b = int(sys.argv[2]) if len(sys.argv) > 2 else 8500
    ollama_url, comfy_url, _servers = serve(a, b)
    print(f"fake Ollama  {ollama_url}")
    print(f"fake ComfyUI {comfy_url}")
    threading.Event().wait()
