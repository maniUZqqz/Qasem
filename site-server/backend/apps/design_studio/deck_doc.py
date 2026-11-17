"""سندِ ارائه (اسلاید): پیش‌نویسِ قاعده‌ای از محصولات و واقعیت‌های واقعی، پیش‌نویسِ هوش مصنوعی (با نگهبانِ عددِ ساختگی)، ساختنِ صحنه و بازبینی.

سند (data): {"v":1,"kind":"deck","settings":{…deck_slides.DEFAULTS…},"products":[…],"facts":[{value,label,source}],"brief":"","slides":[spec…],"meta":{}}
«واقعیت» (fact) فقط از دادهٔ ثبت‌شده یا از چیزی می‌آید که کاربر با منبعش وارد کرده؛ آمارِ بدونِ منبع در بازبینی هشدار می‌گیرد.
"""
from __future__ import annotations

from . import ai as ai_mod, brand, deck_slides as ds, guard, images, scene, typeset
from .catalog_doc import StoreInfo, _jalali_season

KIND = "deck"
MAX_SLIDES = 40
MAX_ITEMS = 8


def short_name(name: str, limit: int = 40) -> str:
    """نامِ محصول برای «منبع»ِ یک آمار: بریدنِ بلند در مرزِ واژه، بی‌پرانتزِ نیمه‌باز و با «…»؛ هرگز وسطِ واژه یا وسطِ پرانتز نمی‌برد."""
    t = typeset.clean_text(name, 400)
    if len(t) <= limit:
        return t
    cut = t[:limit]
    if not t[limit].isspace() and " " in cut:                    # وسطِ واژه ⇒ تا مرزِ واژهٔ پیشین
        cut = cut.rsplit(" ", 1)[0]
    for o, c in (("(", ")"), ("[", "]"), ("«", "»")):            # برشِ وسطِ پرانتز یا گیومه ⇒ از بازکننده به بعد کنار برود
        while cut.count(o) > cut.count(c):
            cut = cut[:cut.rfind(o)]
    cut = cut.rstrip(" ،,-–—:؛;")
    return (cut or t[:limit].rstrip()) + "…"


def auto_facts(items: list[dict], digits: str = "fa") -> list[dict]:
    """واقعیت‌های قابلِ‌اثباتِ فروشگاه: تعدادِ محصول و بازهٔ قیمتِ ثبت‌شده."""
    out = []
    if items:
        out.append({"value": typeset.digits(str(len(items)), digits), "label": "محصولِ ثبت‌شده در فروشگاه", "source": "فهرستِ محصولاتِ فروشگاه (پنل)"})
    priced = [p for p in items if p.get("price") and p["price"] > 0]
    if len(priced) >= 2:
        lo = min(priced, key=lambda p: p["price"])
        hi = max(priced, key=lambda p: p["price"])
        if lo["price"] != hi["price"]:
            out.append({"value": typeset.price_text(lo["price"], lo.get("currency", "IRT"), digits), "label": "کم‌ترین قیمتِ ثبت‌شده", "source": f"قیمتِ ثبت‌شدهٔ «{short_name(lo['name'])}»"})
            out.append({"value": typeset.price_text(hi["price"], hi.get("currency", "IRT"), digits), "label": "بیشترین قیمتِ ثبت‌شده", "source": f"قیمتِ ثبت‌شدهٔ «{short_name(hi['name'])}»"})
    return out


def _sentences(text: str, n: int = 4) -> list[str]:
    import re

    parts = [p.strip() for p in re.split(r"(?<=[.!؟?])\s+|\n+", text or "") if p.strip()]
    return parts[:n]


def rule_slides(info: StoreInfo, items: list[dict], settings: dict, options: dict, facts: list[dict], brief: str = "") -> list[dict]:
    """بدونِ هوش مصنوعی: اسلایدهایی که فقط از دادهٔ واقعی ساخته می‌شوند."""
    s = {**ds.DEFAULTS, **settings}
    opts = options or {}
    persona = info.persona or {}
    slides: list[dict] = []

    def add(**spec):
        spec["id"] = f"s{len(slides) + 1}"
        slides.append(spec)

    about = _sentences(persona.get("about", ""), 4)
    sub = opts.get("subtitle") or (_sentences(brief, 1) or about[:1] or [""])[0]
    add(type="title", title=s.get("title") or info.name, subtitle=sub, date=opts.get("date") or _jalali_season(), kicker=opts.get("kicker", ""),
        image=opts.get("cover_image", ""), notes=_note_title(persona))
    by_id = {p["id"]: p for p in items}
    featured = [i for i in (opts.get("featured") or []) if i in by_id]
    n_prod = int(opts.get("products_count", 3))
    chosen = featured[:n_prod] or [p["id"] for p in sorted((p for p in items if p.get("images") or p.get("short")), key=lambda p: -(p.get("price") or 0))][:n_prod]
    steps = [x for x in (opts.get("steps") or []) if isinstance(x, dict)]
    team = [x for x in (opts.get("team") or []) if isinstance(x, dict)]
    fact_rows = [f for f in (facts or []) if f.get("value") and f.get("label") and f.get("source")][:4]
    agenda_titles: list[str] = []
    if about:
        agenda_titles.append(f"دربارهٔ {info.name}" if info.name else "معرفی")
    for pid in chosen:
        agenda_titles.append(by_id[pid]["name"])
    if len(chosen) >= 2:
        agenda_titles.append("مقایسه")
    if fact_rows:
        agenda_titles.append("عدد‌های واقعی")
    if steps:
        agenda_titles.append(opts.get("steps_title") or "گام‌ها")
    if team:
        agenda_titles.append("تیم")
    add(type="agenda", title="دستورِ جلسه", items=[t[:60] for t in agenda_titles][:8], notes="مسیرِ ارائه را در ده ثانیه بگو و بگذر.")
    if about:
        add(type="text", title=f"دربارهٔ {info.name}" if info.name else "معرفی", bullets=about, notes=_note_text(persona))
    for pid in chosen:
        p = by_id[pid]
        add(type="product", product=pid, notes=_note_product(p, s))
    if len(chosen) >= 2:
        cols = []
        for pid in chosen[:3]:
            p = by_id[pid]
            cols.append({"product": pid, "points": [f"{k}: {v}" for k, v in p.get("attrs", [])][:4] or ([p["short"]] if p.get("short") else []), "highlight": pid == chosen[0]})
        add(type="comparison", title="مقایسه", items=cols, notes="فقط تفاوت‌های ثبت‌شده را بگو؛ چیزی اضافه نکن.")
    if fact_rows:
        add(type="stats", title="عددهای واقعی", items=fact_rows, notes="منبعِ هر عدد زیرِ همان نوشته شده است؛ اگر پرسیدند همان را بگو.")
    if steps:
        add(type="timeline", title=opts.get("steps_title") or "گام‌ها", steps=steps[:6], notes="گام‌ها را به ترتیب و کوتاه بگو.")
    if team:
        add(type="team", title="تیم", members=team[:6], notes="")
    cta = opts.get("cta") or {}
    contact = next((c for c in (info.contacts or []) if c.get("kind") in ("website", "telegram", "instagram")), None)
    add(type="cta", title=cta.get("title") or "گام بعدی با ما", text=cta.get("text") or "", button=cta.get("button") or (contact["value"] if contact else ""),
        link=cta.get("link", ""), note=cta.get("note", ""), notes="دعوتِ نهایی را یک جمله بگو و منتظرِ پرسش بمان.")
    return slides[:MAX_SLIDES]


def _note_title(persona: dict) -> str:
    bits = []
    if persona.get("tone"):
        bits.append(f"لحنِ برند: {persona['tone']}")
    if persona.get("audience"):
        bits.append(f"مخاطب: {persona['audience']}")
    return "\n".join(bits)


def _note_text(persona: dict) -> str:
    return f"توضیحِ ثبت‌شدهٔ فروشگاه: {persona['about']}" if persona.get("about") else ""


def _note_product(p: dict, s: dict) -> str:
    bits = []
    if p.get("desc") or p.get("short"):
        bits.append(f"توضیحِ ثبت‌شده: {p.get('desc') or p.get('short')}"[:600])
    price = typeset.price_text(p.get("price"), p.get("currency", "IRT"), s.get("digits", "fa"), s.get("zero_price_label", "رایگان"))
    if price:
        bits.append(f"قیمتِ ثبت‌شده: {price}")
    return "\n".join(bits)


# ───────────────────────────── هوش مصنوعی

SYSTEM = ("تو دستیارِ نوشتنِ ارائهٔ فارسیِ یک کسب‌وکارِ ایرانی هستی. فقط JSON معتبر برگردان. "
          "هرگز قیمت، آمار، درصد، نظرِ مشتری، نامِ آدم یا ادعایی نساز که در دادهٔ داده‌شده نیست. "
          "فقط از «شناسهٔ محصول»‌های داده‌شده استفاده کن. لحنِ برند را رعایت کن.")


def build_prompt(info: StoreInfo, items: list[dict], facts: list[dict], brief: str, settings: dict, max_slides: int = 9) -> str:
    persona = info.persona or {}
    prods = [{"id": p["id"], "name": p["name"], "price": typeset.price_text(p.get("price"), p.get("currency", "IRT"), "fa", settings.get("zero_price_label", "رایگان")),
              "short": (p.get("short") or "")[:200]} for p in items[:12]]
    payload = {"store": info.name, "about": persona.get("about", "")[:700], "audience": persona.get("audience", ""), "tone": persona.get("tone", "") or persona.get("voice", ""),
               "brief": brief[:600], "products": prods, "facts": [{"value": f["value"], "label": f["label"], "source": f["source"]} for f in facts[:8]]}
    import json

    return ("برای ارائه‌ای کوتاه (حداکثر %d اسلاید) پیش‌نویس بنویس. نوعِ اسلاید فقط یکی از: title, agenda, text, product, comparison, stats, timeline, cta.\n"
            "قالبِ خروجی: {\"slides\":[{\"type\":\"title\",\"title\":\"…\",\"subtitle\":\"…\",\"notes\":\"…\"},{\"type\":\"agenda\",\"items\":[\"…\"],\"notes\":\"…\"},"
            "{\"type\":\"text\",\"title\":\"…\",\"bullets\":[\"…\"]},{\"type\":\"product\",\"product\":<id>,\"text\":\"…\",\"points\":[\"…\"],\"notes\":\"…\"},"
            "{\"type\":\"comparison\",\"items\":[{\"product\":<id>,\"points\":[\"…\"]}]},{\"type\":\"stats\",\"items\":[{\"value\":\"…\",\"label\":\"…\",\"source\":\"…\"}]},"
            "{\"type\":\"timeline\",\"steps\":[{\"title\":\"…\",\"text\":\"…\"}]},{\"type\":\"cta\",\"title\":\"…\",\"text\":\"…\",\"button\":\"…\"}]}\n"
            "قواعد: عددها فقط از «facts» یا قیمتِ محصول‌ها؛ هر آمار با «source». یادداشتِ گوینده (notes) برای هر اسلاید یک تا سه جملهٔ کوتاه.\n"
            "دادهٔ واقعی:\n%s" % (max_slides, json.dumps(payload, ensure_ascii=False)))


def clean_ai(parsed, items: list[dict], facts: list[dict], brief: str, info: StoreInfo, settings: dict, options: dict | None = None) -> list[dict]:
    """JSON ِ مدل ⇒ فهرستِ اسلایدِ تمیز (نوع، شناسهٔ محصول و عددها وارسی می‌شود)."""
    opts = options or {}
    rows = parsed.get("slides") if isinstance(parsed, dict) else None
    if not isinstance(rows, list):
        return []
    by_id = {p["id"]: p for p in items}
    persona = info.persona or {}
    allowed = guard.corpus_numbers(
        brief, persona.get("about"), persona.get("audience"), info.name,
        *[f"{p['name']} {p.get('short', '')} {p.get('desc', '')} {p.get('price', '')} {' '.join(f'{k} {v}' for k, v in p.get('attrs', []))}" for p in items],
        *[f"{f.get('value', '')} {f.get('label', '')}" for f in facts])
    out: list[dict] = []

    def txt(v, n=200):
        v = typeset.clean_text(v, n)
        return "" if guard.unsupported(v, allowed) else v

    for r in rows[:MAX_SLIDES]:
        if not isinstance(r, dict) or r.get("type") not in ds.SLIDE_TYPES or r["type"] in ("team", "image", "section"):
            continue
        t = r["type"]
        sp: dict = {"type": t, "notes": txt(r.get("notes"), 500)}
        if t == "title":
            sp.update(title=txt(r.get("title"), 90) or info.name, subtitle=txt(r.get("subtitle"), 160))
        elif t == "agenda":
            sp.update(title="دستورِ جلسه", items=[txt(x, 60) for x in (r.get("items") or [])[:8] if txt(x, 60)])
            if not sp["items"]:
                continue
        elif t == "text":
            sp.update(title=txt(r.get("title"), 80), bullets=[txt(x, 200) for x in (r.get("bullets") or [])[:6] if txt(x, 200)])
            if not sp["bullets"]:
                continue
        elif t == "product":
            try:
                pid = int(r.get("product"))
            except (TypeError, ValueError):
                continue
            if pid not in by_id:
                continue
            sp.update(product=pid, title="", text=txt(r.get("text"), 240), points=[txt(x, 70) for x in (r.get("points") or [])[:4] if txt(x, 70)])
        elif t == "comparison":
            cols = []
            for it in (r.get("items") or [])[:3]:
                try:
                    pid = int(it.get("product"))
                except (TypeError, ValueError, AttributeError):
                    continue
                if pid in by_id:
                    cols.append({"product": pid, "points": [txt(x, 80) for x in (it.get("points") or [])[:5] if txt(x, 80)], "highlight": not cols})
            if len(cols) < 2:
                continue
            sp.update(title=txt(r.get("title"), 60) or "مقایسه", items=cols)
        elif t == "stats":
            real = {(f["value"], f["label"]) for f in facts}
            rows2 = []
            for it in (r.get("items") or [])[:4]:
                if not isinstance(it, dict):
                    continue
                v, lab, srcx = typeset.clean_text(it.get("value"), 30), typeset.clean_text(it.get("label"), 80), typeset.clean_text(it.get("source"), 100)
                if not (v and lab and srcx) or guard.unsupported(f"{v} {lab}", allowed):
                    continue
                rows2.append({"value": v, "label": lab, "source": srcx})
            if not rows2:
                continue
            sp.update(title=txt(r.get("title"), 60) or "عددهای واقعی", items=rows2)
        elif t == "timeline":
            st = [{"title": txt(x.get("title"), 40), "text": txt(x.get("text"), 160)} for x in (r.get("steps") or [])[:6] if isinstance(x, dict)]
            st = [x for x in st if x["title"]]
            if len(st) < 2:
                continue
            sp.update(title=txt(r.get("title"), 60) or "گام‌ها", steps=st)
        elif t == "cta":
            sp.update(title=txt(r.get("title"), 80) or "گام بعدی با ما", text=txt(r.get("text"), 160), button=txt(r.get("button"), 40), link="", note="")
        out.append(sp)
    for i, sp in enumerate(out, 1):
        sp["id"] = f"s{i}"
    return out


def new_deck(info: StoreInfo, items: list[dict], settings: dict | None = None, options: dict | None = None, *, brief: str = "", use_ai: bool = False,
             facts: list[dict] | None = None, store=None, ask=None) -> tuple[dict, dict]:
    """⇒ (data, ai). ai = {used، via: ai|rules، message}. شکستِ هوش مصنوعی ⇒ پیش‌نویسِ قاعده‌ای + دلیلِ فارسی (هرگز خطا)."""
    s = {**ds.DEFAULTS, **(settings or {})}
    if not s.get("title"):
        s["title"] = info.name
    fct = [f for f in (facts or []) if isinstance(f, dict)]
    if not fct:
        fct = auto_facts(items, s.get("digits", "fa"))
    slides = rule_slides(info, items, s, options or {}, fct, brief)
    ai = {"used": False, "via": "rules", "message": ""}
    if use_ai:
        try:
            asker = ask or (lambda prompt, system: ai_mod.default_ask(store, prompt, system, lambda d: (isinstance(d, dict) and isinstance(d.get("slides"), list) and bool(d["slides"]), ["slides خالی است"])))
            parsed, meta = asker(build_prompt(info, items, fct, brief, s), SYSTEM)
            drafted = clean_ai(parsed, items, fct, brief, info, s, options)
            if len(drafted) >= 3:
                # عنوان و پایانِ قطعی از قاعده‌ها می‌ماند اگر مدل نداد
                if drafted[0]["type"] != "title":
                    drafted.insert(0, slides[0])
                if drafted[-1]["type"] != "cta":
                    drafted.append(slides[-1])
                for i, sp in enumerate(drafted, 1):
                    sp["id"] = f"s{i}"
                slides = drafted[:MAX_SLIDES]
                ai = {"used": True, "via": "ai", "message": "پیش‌نویس را هوش مصنوعی نوشت؛ همهٔ عددها با دادهٔ واقعی سنجیده شد.", "model": (meta or {}).get("label", "")}
            else:
                ai["message"] = "پاسخِ هوش مصنوعی قابلِ‌استفاده نبود؛ پیش‌نویسِ قاعده‌ای ساخته شد."
        except ai_mod.AIUnavailable as exc:
            ai["message"] = f"هوش مصنوعی در دسترس نبود ({exc}); پیش‌نویس با قاعده‌های آماده ساخته شد."
        except Exception as exc:  # noqa: BLE001
            ai["message"] = f"هوش مصنوعی ناموفق بود ({exc.__class__.__name__}); پیش‌نویس با قاعده‌های آماده ساخته شد."
    data = {"v": 1, "kind": KIND, "settings": s, "products": items, "facts": fct, "brief": brief[:1200], "slides": slides, "meta": {"built_for": info.name, "ai": ai}}
    return data, ai


# ───────────────────────────── صحنه و بازبینی

def build_scene(data: dict, info: StoreInfo, src: images.ImageSource | None = None) -> dict:
    s = {**ds.DEFAULTS, **(data.get("settings") or {})}
    kit = info.kit_for(s)
    items = {int(p["id"]): p for p in data.get("products", [])}
    ctx = ds.Ctx(s, kit, items, info.name, info.contacts, info.has_logo)
    specs = [sp for sp in data.get("slides", []) if isinstance(sp, dict) and sp.get("type") in ds.SLIDE_TYPES][:MAX_SLIDES]
    ctx.total = len(specs)
    pages = []
    for i, sp in enumerate(specs):
        ctx.index = i
        pages.append(scene.finalize_page(ds.build_slide(sp, ctx), digits_mode=s.get("digits", "fa")))
    return {"kind": KIND, "unit": "px", "pages": pages, "settings": s, "palette": kit["palette"], "fonts": kit["fonts"], "rtl": True}


def review(data: dict, sc: dict) -> list[dict]:
    """بازبینیِ ارائه: جای‌گیرِ پرنشده، آمارِ بی‌منبع، اسلایدِ بی‌یادداشت، متنِ بریده."""
    out: list[dict] = []
    fa = lambda v: typeset.digits(str(v), "fa")  # noqa: E731

    def add(key, level, title, detail=""):
        out.append({"key": key, "level": level, "title": title, "detail": detail})

    phs = [p["name"] for p in sc["pages"] if any(e.get("ph") for e in p["elements"])]
    add("placeholders", "ok" if not phs else "warn", "همهٔ جای‌گیرها پر شده" if not phs else f"{fa(len(phs))} اسلاید هنوز جای‌گیرِ خالی دارد", "" if not phs else "، ".join(phs[:5]))
    nosrc = []
    for sp in data.get("slides", []):
        if sp.get("type") == "stats":
            for it in sp.get("items") or []:
                if isinstance(it, dict) and not str(it.get("source") or "").strip():
                    nosrc.append(str(it.get("label") or it.get("value") or ""))
    add("stats_source", "ok" if not nosrc else "warn", "هر آمار منبع دارد" if not nosrc else f"{fa(len(nosrc))} آمار بدونِ منبع است", "" if not nosrc else "آمارِ بی‌منبع را حذف کنید یا منبعش را بنویسید.")
    nonote = [p["name"] for p in sc["pages"] if not (p.get("notes") or "").strip() and p.get("type") not in ("section", "image")]
    fd = int((data.get("meta") or {}).get("facts_dropped") or 0)
    if fd:
        names = [str(x) for x in ((data.get("meta") or {}).get("facts_dropped_labels") or []) if x]
        add("facts_dropped", "warn", f"{fa(fd)} عددِ بدونِ منبع یا ناقص کنار گذاشته شد",
            ("«" + "»، «".join(names[:4]) + "» — " if names else "") + "هر عددِ ارائه باید برچسب و منبع داشته باشد؛ در اسلایدِ «آمار» با منبعش اضافه‌اش کنید.")
    add("notes", "ok" if not nonote else "info", "هر اسلاید یادداشتِ گوینده دارد" if not nonote else f"{fa(len(nonote))} اسلاید یادداشتِ گوینده ندارد", "")
    over = [p["name"] for p in sc["pages"] for e in p["elements"] if scene.text_problem(e)]
    add("overflow", "ok" if not over else "warn", "هیچ متنی بریده نشده" if not over else f"{fa(len(over))} متن بیش از جعبه‌اش بود", "" if not over else "، ".join(sorted(set(over))[:4]))
    add("count", "ok" if len(sc["pages"]) <= 20 else "info", f"{fa(len(sc['pages']))} اسلاید", "")
    return out
