"""سندِ کاتالوگ: ساختِ خودکارِ صفحه‌ها از محصولات، ساختنِ صحنه، و «چک‌لیستِ چاپخانه» (همان چک‌لیستِ راهنمای فایل‌ها).

سند (data):
    {"v": 1, "kind": "catalog", "settings": {...catalog_pages.DEFAULTS...}, "products": [snapshot...], "pages": [spec...], "meta": {...}}
spec صفحه: {"id": "p1", "type": "grid", ..., "overrides": {شناسهٔ عنصر: {...}}, "extra": [عنصر...], "notes": ""}
"""
from __future__ import annotations

import math

from . import brand, catalog_pages as cp, images, products as prod, scene, typeset

KIND = "catalog"
MAX_PAGES = 120
LOGO_REF = "logo"


class StoreInfo:
    """هرچه صحنه از فروشگاه لازم دارد (بی‌نیاز از دیتابیس؛ برای آزمون و نمونه‌ها ساخته می‌شود)."""

    def __init__(self, name: str = "", kit: dict | None = None, contacts: list | None = None, has_logo: bool = False, persona: dict | None = None, store=None):
        self.name = name
        self.kit = kit
        self.contacts = contacts or []
        self.has_logo = has_logo
        self.persona = persona or {}
        self.store = store

    @classmethod
    def from_store(cls, store, settings: dict | None = None) -> "StoreInfo":
        k = brand.kit(store, settings)
        return cls(name=store.name, kit=k, contacts=brand.contacts(store), has_logo=k["has_logo"], persona=k["persona"], store=store)

    def kit_for(self, settings: dict) -> dict:
        if self.store is not None:
            return brand.kit(self.store, settings)
        return self.kit or brand.kit(None, settings)


def _jalali_season(now=None) -> str:
    import datetime as dt

    try:
        from apps.common.versioning import gregorian_to_jalali

        d = now or dt.date.today()
        jy, jm, _ = gregorian_to_jalali(d.year, d.month, d.day)
        season = ("بهار", "تابستان", "پاییز", "زمستان")[(jm - 1) // 3]
        return f"{season} {jy}"
    except Exception:  # noqa: BLE001
        return ""


def new_page_id(data: dict) -> str:
    used = {p.get("id") for p in data.get("pages", [])}
    n = len(used) + 1
    while f"p{n}" in used:
        n += 1
    return f"p{n}"


def default_pages(items: list[dict], settings: dict, info: StoreInfo, options: dict, src: images.ImageSource | None = None) -> list[dict]:
    """محصولات ⇒ فهرستِ صفحه‌ها: جلد، فهرست، دربارهٔ ما، محصولِ ویژه، شبکه، فهرستِ قیمت، لوک‌بوک، صفحه‌های اضافه، پشتِ جلد."""
    s = {**cp.DEFAULTS, **settings}
    opts = options or {}
    cols, rows = int(s.get("grid_cols") or 2), int(s.get("grid_rows") or 3)
    pages: list[dict] = []

    def add(**spec) -> dict:
        spec["id"] = f"p{len(pages) + 1}"
        pages.append(spec)
        return spec

    first_img = next((i["images"][0] for i in items if i.get("images")), "")
    add(type="cover", image=opts.get("cover_image", first_img), title=s.get("title", ""), subtitle=s.get("subtitle", ""), date_text=s.get("date_text") or _jalali_season())
    if opts.get("toc", True):
        add(type="toc")
    about = opts.get("about")
    if about is None:
        about = [ln.strip() for ln in (info.persona.get("about") or "").split("\n") if ln.strip()][:4]
    if about and opts.get("with_about", True):
        add(type="text", title=f"دربارهٔ {info.name}" if info.name else "دربارهٔ ما", kicker="معرفی", paragraphs=about)
    for ex in opts.get("pre_pages", []):
        add(**{k: v for k, v in ex.items() if k != "id"})
    by_id = {p["id"]: p for p in items}
    featured = [i for i in (opts.get("featured") or []) if i in by_id]
    for pid in featured[:4]:
        add(type="hero", product=pid)
    layout = opts.get("layout", "mix")
    rest = [p for p in items if p["id"] not in featured or layout == "grid_all"]
    cats: dict[str, list[dict]] = {}
    for p in rest:
        cats.setdefault(p.get("category") or "", []).append(p)
    multi = len([c for c in cats if c]) >= 2
    per = max(1, cols * rows)
    for cat, group in cats.items():
        title = cat or "محصولات"
        if multi and opts.get("dividers", False):
            add(type="divider", title=title, subtitle=f"{typeset.digits(str(len(group)), s['digits'])} محصول")
        if layout in ("mix", "grid", "grid_all", "hero_first"):
            for i in range(0, len(group), per):
                chunk = group[i:i + per]
                add(type="grid", title=title if i == 0 else f"{title} (ادامه)", cols=cols, rows=rows, products=[p["id"] for p in chunk])
        if layout == "list":
            for i in range(0, len(group), 12):
                add(type="price_list", title=title, products=[p["id"] for p in group[i:i + 12]])
    if layout == "mix" and s.get("show_prices", True) and len(items) >= 4:
        shown = [p for p in items if p.get("price") is not None]
        for i in range(0, len(shown), 12):
            add(type="price_list", title="فهرستِ قیمت", products=[p["id"] for p in shown[i:i + 12]],
                note="قیمت‌ها همان مقدارِ ثبت‌شده در فروشگاه است.")
    if opts.get("lookbook", True):
        refs = prod.distinct_images(items, src) if src is not None else []
        if len(refs) >= 3:
            names = {r: next((p["name"] for p in items if r in p.get("images", [])), "") for r in refs}
            add(type="lookbook", title="لوک‌بوک", images=refs[:4], captions=[names[r] for r in refs[:4]])
    for ex in opts.get("extra_pages", []):
        add(**{k: v for k, v in ex.items() if k != "id"})
    add(type="back", title=info.name, text=opts.get("back_text", ""), **({"contacts": opts["back_contacts"]} if opts.get("back_contacts") else {}))
    return pages[:MAX_PAGES]


def new_doc(info: StoreInfo, items: list[dict], settings: dict | None = None, options: dict | None = None, src: images.ImageSource | None = None) -> dict:
    s = {**cp.DEFAULTS, **(settings or {})}
    if not s.get("title"):
        s["title"] = info.name
    return {"v": 1, "kind": KIND, "settings": s, "products": items, "pages": default_pages(items, s, info, options or {}, src), "meta": {"built_for": info.name}}


# ───────────────────────────── ساختنِ صحنه

def build_scene(data: dict, info: StoreInfo, src: images.ImageSource | None = None) -> dict:
    s = {**cp.DEFAULTS, **(data.get("settings") or {})}
    kit = info.kit_for(s)
    items = {int(p["id"]): p for p in data.get("products", [])}
    specs = [p for p in data.get("pages", []) if isinstance(p, dict) and p.get("type") in cp.PAGE_TYPES][:MAX_PAGES]
    ctx = cp.Ctx(s, kit, items, info.name, info.contacts, total=len(specs), has_logo=info.has_logo)
    ctx.toc = [{"id": sp["id"], "index": i, "title": cp.page_title(sp, ctx)} for i, sp in enumerate(specs) if sp["type"] not in ("cover", "toc", "divider")]
    pages = []
    for i, sp in enumerate(specs):
        ctx.index = i
        page = cp.build_page(sp, ctx)
        page["section"] = sp["type"]
        pages.append(scene.finalize_page(page, digits_mode=s.get("digits", "fa")))
    return {"kind": KIND, "unit": "mm", "pages": pages, "settings": s, "palette": kit["palette"], "fonts": kit["fonts"], "rtl": True,
            "toc": [{"id": t["id"], "title": t["title"], "index": t["index"]} for t in ctx.toc]}


def bookmarks(sc: dict) -> list[tuple[str, int, int]]:
    out = []
    for i, p in enumerate(sc["pages"]):
        if p.get("section") in ("cover",):
            out.append((p["name"] or "جلد", i, 0))
        elif p.get("section") not in ("toc",):
            out.append((p["name"], i, 0))
        else:
            out.append((p["name"], i, 0))
    return out


# ───────────────────────────── چک‌لیستِ چاپخانه

def image_dpi(sc: dict, src: images.ImageSource) -> list[dict]:
    """dpi ِ مؤثرِ هر عکس در اندازهٔ چاپ (برای قاعدهٔ «دست‌کم ۳۰۰ dpi»)."""
    out = []
    for p in sc["pages"]:
        for e in p["elements"]:
            if e["type"] != "image" or e.get("role") == "logo" or e["w"] <= 0 or e["h"] <= 0:
                continue
            size = src.size(e.get("src", ""))
            if not size:
                out.append({"page": p["id"], "el": e["id"], "dpi": 0, "missing": True})
                continue
            crop, dest = images.fit_rect(size[0], size[1], e["w"], e["h"], e.get("fit", "cover"), e.get("focus"))
            w_in = (dest[2] / 25.4)
            dpi = (crop[2] - crop[0]) / w_in if w_in > 0 else 0
            out.append({"page": p["id"], "el": e["id"], "dpi": int(round(dpi)), "missing": False, "w_mm": round(e["w"], 1)})
    return out


def empty_pages(data: dict, sc: dict) -> list[dict]:
    """صفحه‌هایی که بی‌هیچ محتوا چاپ می‌شوند: «محصولِ ویژه» بدونِ محصول، «لوک‌بوک» بدونِ عکس، شبکه/فهرستِ قیمت بدونِ محصول، گام‌ها و متنِ خالی.
    ⇒ [{id, name, type, why}]. صفحه‌ای که کاربر خودش عنصر به آن افزوده خالی حساب نمی‌شود."""
    known = set()
    for p in data.get("products", []):
        try:
            known.add(int(p["id"]))
        except (KeyError, TypeError, ValueError):
            continue

    def has_product(v) -> bool:
        try:
            return int(v) in known
        except (TypeError, ValueError):
            return False

    specs = {sp.get("id"): sp for sp in data.get("pages", []) if isinstance(sp, dict)}
    out = []
    for pg in sc["pages"]:
        sp = specs.get(pg.get("id")) or {}
        if sp.get("extra"):
            continue
        t = pg.get("type") or sp.get("type")
        why = ""
        if t == "hero" and not has_product(sp.get("product")):
            why = "محصولی برایش انتخاب نشده"
        elif t == "lookbook" and not [r for r in (sp.get("images") or []) if r]:
            why = "عکسی ندارد"
        elif t in ("grid", "price_list") and not any(has_product(v) for v in (sp.get("products") or [])):
            why = "محصولی ندارد"
        elif t == "steps" and not [s for s in (sp.get("steps") or []) if isinstance(s, dict) and (s.get("title") or s.get("text"))]:
            why = "گامی ندارد"
        elif t == "text" and not (sp.get("image") or [x for x in (sp.get("paragraphs") or []) if str(x).strip()]):
            why = "متن و عکسی ندارد"
        elif not any(e.get("role") != "decor" for e in pg.get("elements", [])):
            why = "چیزی روی صفحه نیست"
        if why:
            out.append({"id": pg.get("id"), "name": pg.get("name") or str(pg.get("id")), "type": t, "why": why})
    return out


def preflight(data: dict, sc: dict, src: images.ImageSource) -> list[dict]:
    """⇒ چک‌لیست: [{key، level: ok|warn|info، title، detail}] — هر مورد معادلِ یک خطِ «چک‌لیستِ فایلِ کاتالوگ برای چاپخانه» ِ راهنما."""
    s = sc["settings"]
    W, H = sc["pages"][0]["w"], sc["pages"][0]["h"]
    n = len(sc["pages"])
    out: list[dict] = []

    def add(key, level, title, detail=""):
        out.append({"key": key, "level": level, "title": title, "detail": detail})

    fa = lambda v: typeset.digits(str(v), "fa")  # noqa: E731
    add("size", "ok", f"اندازهٔ صفحه {s.get('page_size', 'A4')} ({fa(int(W))}×{fa(int(H))} میلی‌متر)", "")
    bleed = float(s.get("bleed", 0))
    add("bleed", "ok" if bleed >= 3 else "warn", f"خونریزی {fa(bleed)} میلی‌متر از هر طرف", "" if bleed >= 3 else "بیشتر چاپخانه‌ها فایلِ بدونِ خونریزیِ ۳ میلی‌متر را قبول نمی‌کنند.")
    add("marks", "ok", "علامتِ برش (Crop marks) در «PDF چاپی»", "")
    dp = image_dpi(sc, src)
    low = [d for d in dp if not d["missing"] and 0 < d["dpi"] < 300]
    miss = [d for d in dp if d["missing"]]
    if miss:
        add("missing", "warn", f"{fa(len(miss))} عکس پیدا نشد", "جای عکسِ گم‌شده خالی (طوسی) می‌ماند؛ عکس را دوباره انتخاب کنید.")
    if low:
        worst = min(d["dpi"] for d in low)
        add("dpi", "warn", f"{fa(len(low))} عکس کمتر از ۳۰۰ dpi دارد (کمترین {fa(worst)})", "برای چاپِ تیز عکسِ بزرگ‌تر بگذارید؛ برای مشاهدهٔ روی صفحه مشکلی نیست.")
    else:
        add("dpi", "ok", "عکس‌ها دست‌کم ۳۰۰ dpi در اندازهٔ چاپ‌اند", "" if dp else "عکسی در کاتالوگ نیست.")
    add("fonts", "ok", "فونت‌ها به منحنی (Outline) تبدیل می‌شوند", "چاپخانه نیازی به نصبِ فونت ندارد؛ متن در «PDF چاپی» انتخاب‌پذیر نیست (در «PDF نمایشی» متنِ قابل‌جست‌وجو و کپی هست).")
    add("color", "info", "رنگ‌ها RGB‌اند", "CMYK و PDF/X واقعی را چاپخانه از همین PDF می‌سازد؛ اگر چیز دیگری خواست از او بپرسید.")
    safe = 5.0
    bad_safe = []
    for p in sc["pages"]:
        for e in p["elements"]:
            if e["type"] == "text" and e.get("text", "").strip() and not e.get("role") in ("decor",):
                if e["x"] < safe - 0.01 or e["y"] < safe - 0.01 or e["x"] + e["w"] > p["w"] - safe + 0.01 or e["y"] + e["h"] > p["h"] - safe + 0.01:
                    bad_safe.append(p["name"])
                    break
    add("safe", "ok" if not bad_safe else "warn", "متن‌ها دست‌کم ۵ میلی‌متر از لبهٔ برش فاصله دارند" if not bad_safe else f"متنِ نزدیک به لبه در {fa(len(bad_safe))} صفحه",
        "" if not bad_safe else "، ".join(bad_safe[:4]))
    over = [p["name"] for p in sc["pages"] for e in p["elements"] if scene.text_problem(e)]
    add("overflow", "ok" if not over else "warn", "هیچ متنی بریده یا سرریز نشده" if not over else f"{fa(len(over))} متن بیش از جعبه‌اش بود (کوتاه یا بریده شد)",
        "" if not over else "، ".join(sorted(set(over))[:4]))
    empt = empty_pages(data, sc)
    add("empty", "ok" if not empt else "warn", "هیچ صفحهٔ خالی نیست" if not empt else f"{fa(len(empt))} صفحه خالی است و سفید چاپ می‌شود",
        "" if not empt else "؛ ".join(f"«{e['name']}» ({e['why']})" for e in empt[:4]) + " — محصول یا عکس را اضافه کنید، یا صفحه را حذف کنید.")
    add("single", "ok", "صفحه‌ها تکی‌اند (نه دوتایی/Spread)", "")
    add("mult4", "ok" if n % 4 == 0 else "info", f"تعداد صفحه‌ها {fa(n)}" + (" (مضرب ۴)" if n % 4 == 0 else ""),
        "" if n % 4 == 0 else "برای کاتالوگِ منگنه‌ای تعدادِ صفحه باید مضرب ۴ باشد (۸، ۱۲، ۱۶…). با «افزودنِ صفحهٔ یادداشت» تکمیل کنید.")
    no_price = [p["name"] for p in data.get("products", []) if p.get("price") is None]
    if s.get("show_prices", True) and no_price:
        add("prices", "info", f"{fa(len(no_price))} محصول قیمتِ ثبت‌شده ندارد", "برای این محصولات قیمتی نوشته نمی‌شود.")
    return out
