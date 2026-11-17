"""سندِ طراحیِ UI/UX («Figma-lite» پیش از سایت‌ساز): فریم‌های دسکتاپ/تبلت/گوشی، قطعه‌های سایت‌ساز، توکن‌ها، پیوندِ نمونهٔ اولیه و «ساختِ سایت از این طرح».

سند (data): {"v":1,"kind":"ui","settings":{…ui_frames.DEFAULTS…},"frames":[{id,name,device,mode?,of?,children:[گره…],x,y}],"meta":{}}
گرهٔ بلوک همان بلوکِ سایت‌ساز است (id، type، props، style، children) با ``t: "block"``؛ پس تبدیل به سایت بی‌ضرر و دقیق است.
"""
from __future__ import annotations

import copy
import json
import re

from . import colors, fonts, scene, typeset, ui_blocks as ub, ui_frames as uf

KIND = "ui"
MAX_FRAMES = 30
MAX_NODES = 300
LINK_KEYS = ("btn_link", "btn1_link", "link", "cta_link", "announce_link")


def new_id(prefix: str = "n") -> str:
    import uuid

    return prefix + uuid.uuid4().hex[:8]


def block_node(btype: str, **props) -> dict:
    """بلوکِ سایت‌ساز با مشخصه‌های پیش‌فرضِ خودش (از catalog.default_props) + t=block."""
    try:
        from apps.projects.builder.catalog import default_props

        p = default_props(btype)
    except Exception:  # noqa: BLE001
        p = {}
    p.update(props)
    node = {"id": new_id("b"), "t": "block", "type": btype, "props": p, "style": {}}
    if btype in ("section", "columns", "column"):
        node["children"] = []
    return node


def block_catalog() -> dict:
    """بلوک‌های قابلِ استفاده در طراحی (همان فهرستِ سایت‌ساز)؛ ⇒ {groups، blocks:[{type,label,group,fields,defaults}]}."""
    try:
        from apps.projects.builder import catalog

        cj = catalog.catalog_json()
        allowed = []
        for b in cj["blocks"]:
            if b.get("hidden") or b["type"] in ("column", "custom_html"):
                continue
            allowed.append({"type": b["type"], "label": b["label"], "group": b["group"], "hint": b.get("hint", ""), "fields": b.get("fields", []), "defaults": b.get("defaults", {}),
                            "category": b.get("category", ""), "scope": b.get("scope", [])})
        return {"groups": cj["groups"], "blocks": allowed, "components": cj.get("components", {})}
    except Exception:  # noqa: BLE001
        return {"groups": [], "blocks": [], "components": {}}


def _mark_blocks(node: dict) -> None:
    node["t"] = "block"
    for c in node.get("children") or []:
        if isinstance(c, dict):
            _mark_blocks(c)                                       # فرزندِ «بخش» هم بلوک است؛ بدونِ t فهرستِ لایه‌ها نامش را «undefined» می‌نوشت


def _from_builder_blocks(blocks: list[dict]) -> list[dict]:
    out = []
    for b in blocks:
        nb = copy.deepcopy(b)
        _mark_blocks(nb)
        out.append(nb)
    return out


def starter_blocks(kind: str, info) -> list[dict]:
    """نمونهٔ شروع: «landing» = سربرگ، قهرمان، ویژگی‌ها، گام‌ها، قیمت، پرسش، دعوت، پابرگ (با متنِ پیش‌فرضِ سایت‌ساز)."""
    if kind == "blank":
        return []
    name = getattr(info, "name", "") or "برند"
    nodes = [block_node("c_nav_classic", btn="شروع کنید", btn_link="#", sticky=True),
             block_node("c_hero_center_glow", title=f"{name}؛ تیترِ اصلی را این‌جا بنویس", subtitle="در یکی دو جمله بگو چه کاری انجام می‌دهی و چرا مشتری باید تو را انتخاب کند."),
             block_node("c_feat_icon_grid"), block_node("c_steps_horizontal"), block_node("c_price_three_tier"), block_node("c_faq_two_col"), block_node("c_cta_center_box"),
             block_node("c_footer_columns")]
    return nodes


def new_frame(name: str, device: str, children: list[dict], *, of: str = "", mode: str = "", fid: str = "") -> dict:
    f = {"id": fid or new_id("f"), "name": name, "device": device if device in ub.DEVICES else "desktop", "children": children}
    if of:
        f["of"] = of
    if mode in ("light", "dark"):
        f["mode"] = mode
    return f


def new_doc(info, *, template: str = "landing", settings: dict | None = None, devices: tuple = ("desktop", "phone"), blocks: list[dict] | None = None,
            name: str = "صفحهٔ اصلی") -> dict:
    s = {**uf.DEFAULTS, **(settings or {})}
    nodes = _from_builder_blocks(blocks) if blocks is not None else starter_blocks(template, info)
    frames = []
    main = new_frame(name, "desktop", nodes, fid="f1") if "desktop" in devices else None
    if main:
        frames.append(main)
    for dev in devices:
        if dev == "desktop":
            continue
        frames.append(new_frame(f"{name} · {uf.DEVICE_NAMES.get(dev, dev)}", dev, copy.deepcopy(nodes), of=main["id"] if main else "", fid=new_id("f")))
    if not frames:
        frames.append(new_frame(name, devices[0], nodes, fid="f1"))
    if not s.get("menu"):
        s["menu"] = ["خانه", "امکانات", "قیمت", "تماس"]
    return {"v": 1, "kind": KIND, "settings": s, "frames": frames, "meta": {"template": template}}


# ───────────────────────────── ویرایش‌ها (ops)

def _frame(data: dict, fid: str) -> dict | None:
    return next((f for f in data["frames"] if f.get("id") == fid), None)


def _walk(nodes: list[dict]):
    for n in nodes:
        yield n
        for c in n.get("children", []) or []:
            if isinstance(c, dict):
                yield from _walk([c])


def find_node(frame: dict, nid: str) -> tuple[list, int] | None:
    """(فهرستِ والد، شاخص) برای یک گره."""
    def rec(lst):
        for i, n in enumerate(lst):
            if n.get("id") == nid:
                return lst, i
            kids = n.get("children")
            if isinstance(kids, list):
                r = rec(kids)
                if r:
                    return r
        return None
    return rec(frame["children"])


def count_nodes(data: dict) -> int:
    return sum(1 for f in data["frames"] for _ in _walk(f.get("children", [])))


def clean_node(n, depth: int = 0) -> dict | None:
    """گرهِ کاربر ⇒ گرهٔ ایمن (نوع‌های مجاز، متنِ کوتاه‌شده، JSONِ قابلِ‌ذخیره)."""
    if not isinstance(n, dict) or depth > 10:
        return None
    t = n.get("t")
    if t not in ("block", "frame", "text", "button", "image", "rect", "input", "spacer", "icon"):
        return None
    try:
        out = json.loads(json.dumps(n, ensure_ascii=False))
    except (TypeError, ValueError):
        return None
    out["id"] = out.get("id") if isinstance(out.get("id"), str) and re.match(r"^[A-Za-z0-9_-]{1,32}$", out.get("id", "")) else new_id("n")
    if t == "block" and not isinstance(out.get("type"), str):
        return None
    if isinstance(out.get("children"), list):
        out["children"] = [c for c in (clean_node(c, depth + 1) for c in out["children"]) if c]
    for k in ("text", "label", "placeholder"):
        if isinstance(out.get(k), str):
            out[k] = typeset.clean_text(out[k], 600)
    return out


def _block_family(n: dict) -> str:
    t = str(n.get("type") or "") if n.get("t") in (None, "block") else ""
    key = t[2:] if t.startswith("c_") else t
    return "nav" if t == "site_header" else key.split("_")[0] if key else ""


def _default_index(target: list, node: dict, *, top: bool) -> int:
    """جای پیش‌فرضِ قطعهٔ تازه در بالاترین سطحِ فریم: سربرگ اول، پابرگ آخر و هر چیز دیگر پیش از پابرگ.
    (پیش‌تر هر قطعه بعد از پابرگ می‌افتاد و کاربر باید با دست بالا می‌آوردش.)"""
    if not top:
        return len(target)
    fam = _block_family(node)
    if fam == "nav":
        return 0
    if fam == "footer":
        return len(target)
    i = len(target)
    while i > 0 and _block_family(target[i - 1]) == "footer":
        i -= 1                                                    # بعد از آخرین قطعهٔ غیرِ پابرگ
    return i


def apply_ops(data: dict, ops: list[dict]) -> dict:
    """ops روی سند (درجا) ⇒ همان سند. خطا ⇒ ValueError(متنِ فارسی)."""
    for op in (ops or [])[:60]:
        k = op.get("op")
        if k == "set_settings":
            for key, v in (op.get("set") or {}).items():
                if key in uf.DEFAULTS:
                    data["settings"][key] = v
        elif k == "add_frame":
            if len(data["frames"]) >= MAX_FRAMES:
                raise ValueError("بیش از ۳۰ فریم نمی‌شود.")
            dev = op.get("device") if op.get("device") in ub.DEVICES else "desktop"
            src = _frame(data, op.get("copy_of")) if op.get("copy_of") else None
            kids = copy.deepcopy(src["children"]) if src else []
            if src:
                _regen_ids(kids)
            f = new_frame(str(op.get("name") or f"فریم {len(data['frames']) + 1}")[:60], dev, kids, of=op.get("of", ""), mode=op.get("mode", ""))
            data["frames"].append(f)
        elif k == "update_frame":
            f = _frame(data, op.get("frame"))
            if f is None:
                raise ValueError("فریم پیدا نشد.")
            for key in ("name", "device", "mode", "w", "x", "y", "of"):
                if key in (op.get("set") or {}):
                    v = op["set"][key]
                    if key == "device" and v not in ub.DEVICES:
                        continue
                    if key == "mode" and v not in ("light", "dark", ""):
                        continue
                    f[key] = v[:60] if isinstance(v, str) else v
        elif k == "delete_frame":
            if len(data["frames"]) <= 1:
                raise ValueError("دست‌کم یک فریم باید بماند.")
            data["frames"] = [f for f in data["frames"] if f["id"] != op.get("frame")]
            for f in data["frames"]:
                for n in _walk(f["children"]):
                    if isinstance(n.get("link"), dict) and n["link"].get("frame") == op.get("frame"):
                        n.pop("link", None)
        elif k == "add_node":
            f = _frame(data, op.get("frame"))
            if f is None:
                raise ValueError("فریم پیدا نشد.")
            if count_nodes(data) >= MAX_NODES:
                raise ValueError("تعدادِ گره‌ها از سقف گذشت.")
            node = op.get("node") if isinstance(op.get("node"), dict) else block_node(str(op.get("type") or "c_hero_center_glow"))
            node = clean_node(node)
            if node is None:
                raise ValueError("گرهٔ نامعتبر.")
            target = f["children"]
            if op.get("parent"):
                r = find_node(f, op["parent"])
                if r:
                    p = r[0][r[1]]
                    p.setdefault("children", [])
                    target = p["children"]
            idx = op.get("index")
            if isinstance(idx, int) and 0 <= idx <= len(target):
                target.insert(idx, node)
            else:
                target.insert(_default_index(target, node, top=target is f["children"]), node)
        elif k == "update_node":
            f = _frame(data, op.get("frame"))
            r = find_node(f, op.get("node")) if f else None
            if not r:
                raise ValueError("گره پیدا نشد.")
            n = r[0][r[1]]
            patch = op.get("set") or {}
            for key, v in patch.items():
                if key in ("id", "t", "children"):
                    continue
                if key == "props" and isinstance(v, dict):
                    n.setdefault("props", {}).update(json.loads(json.dumps(v, ensure_ascii=False)))
                else:
                    n[key] = v
            for key in (op.get("unset") or []):
                n.pop(key, None)
        elif k == "remove_node":
            f = _frame(data, op.get("frame"))
            r = find_node(f, op.get("node")) if f else None
            if r:
                r[0].pop(r[1])
        elif k == "move_node":
            f = _frame(data, op.get("frame"))
            r = find_node(f, op.get("node")) if f else None
            if r:
                n = r[0].pop(r[1])
                to = max(0, min(len(r[0]), int(op.get("to", 0))))
                r[0].insert(to, n)
        elif k == "set_link":
            f = _frame(data, op.get("frame"))
            r = find_node(f, op.get("node")) if f else None
            if not r:
                raise ValueError("گره پیدا نشد.")
            n = r[0][r[1]]
            if op.get("to"):
                if not _frame(data, op["to"]):
                    raise ValueError("فریمِ مقصد پیدا نشد.")
                n["link"] = {"frame": op["to"]}
            else:
                n.pop("link", None)
        elif k == "sync_responsive":
            src = _frame(data, op.get("frame"))
            if src is None:
                raise ValueError("فریم پیدا نشد.")
            for f in data["frames"]:
                if f.get("of") == src["id"]:
                    f["children"] = copy.deepcopy(src["children"])
        else:
            raise ValueError(f"عملِ «{k}» را نمی‌شناسم.")
    return data


def _regen_ids(nodes: list[dict]) -> None:
    for n in nodes:
        n["id"] = new_id("b" if n.get("t") == "block" else "n")
        if isinstance(n.get("children"), list):
            _regen_ids(n["children"])


# ───────────────────────────── پیوندها و بازبینی

def links(data: dict) -> list[dict]:
    """همهٔ پیوندهای نمونهٔ اولیه: [{from_frame، node، to}]."""
    out = []
    for f in data["frames"]:
        for n in _walk(f.get("children", [])):
            lk = n.get("link")
            if isinstance(lk, dict) and lk.get("frame"):
                out.append({"from": f["id"], "node": n["id"], "to": lk["frame"]})
    return out


def review(data: dict, sc: dict) -> list[dict]:
    out = []
    fa = lambda v: typeset.digits(str(v), "fa")  # noqa: E731

    def add(key, level, title, detail=""):
        out.append({"key": key, "level": level, "title": title, "detail": detail})

    t = sc["tokens"]
    pairs = [("متن روی زمینه", t["light"]["text"], t["light"]["bg"]), ("متنِ روی دکمهٔ اصلی", t["light"]["on_primary"], t["light"]["primary"]),
             ("متنِ کم‌رنگ روی زمینه", t["light"]["muted"], t["light"]["bg"]), ("متن روی زمینه (تیره)", t["dark"]["text"], t["dark"]["bg"]), ("متنِ روی دکمه (تیره)", t["dark"]["on_primary"], t["dark"]["primary"])]
    bad = [f"{n} {fa('%.1f' % colors.contrast(a, b))}" for n, a, b in pairs if colors.contrast(a, b) < 4.5]
    add("contrast", "ok" if not bad else "warn", "تباینِ رنگ‌ها دست‌کم ۴٫۵ است" if not bad else "تباینِ این جفت‌رنگ‌ها کم است", "" if not bad else "، ".join(bad))
    lk = links(data)
    dead = [x for x in lk if not _frame(data, x["to"])]
    add("links", "ok" if not dead else "warn", f"{fa(len(lk))} پیوندِ نمونهٔ اولیه" if lk else "هنوز پیوندی بین فریم‌ها نیست", "" if lk else "یک دکمه را انتخاب و «پیوند به فریم» را بزنید.")
    devs = {f["device"] for f in data["frames"]}
    add("devices", "ok" if len(devs) >= 2 else "info", "دسکتاپ و گوشی هر دو طراحی شده" if len(devs) >= 2 else "فقط یک دستگاه طراحی شده", "سایت باید روی گوشی هم خوب باشد؛ یک فریم گوشی اضافه کنید." if len(devs) < 2 else "")
    n_nav = sum(1 for f in data["frames"] for n in f.get("children", []) if str(n.get("type", "")).startswith(("c_nav", "site_header")))
    add("nav", "ok" if n_nav else "info", "سربرگ دارد" if n_nav else "سربرگ (منو) ندارد", "")
    return out


# ───────────────────────────── توکن‌ها (خروجی برای برنامه‌نویس)

def tokens_json(tokens: dict, settings: dict) -> dict:
    return {"style": tokens["style"], "colors": {"light": tokens["light"], "dark": tokens["dark"]}, "radius": tokens["radius"], "space": tokens["space"], "type": tokens["type"],
            "fonts": {"heading": fonts.clean(settings.get("font_head")), "body": fonts.clean(settings.get("font_body"))}}


def tokens_css(tokens: dict, settings: dict) -> str:
    fh, fb = fonts.clean(settings.get("font_head")), fonts.clean(settings.get("font_body"))
    fam = lambda k: fonts.FONT_INFO.get(k, {}).get("family", "Vazirmatn")  # noqa: E731

    def block(sel, pal):
        rows = "\n".join(f"  --{k.replace('_', '-')}: {v};" for k, v in pal.items())
        return f"{sel} {{\n{rows}\n}}"

    sp = "\n".join(f"  --space-{i + 1}: {v}px;" for i, v in enumerate(tokens["space"]))
    ty = "\n".join(f"  --text-{k}: {v}px;" for k, v in tokens["type"].items())
    return (f"/* توکن‌های طراحی — خروجیِ استودیوی طراحی (سبک: {tokens['style_label']}) */\n" + block(":root", tokens["light"]) + "\n" + block(":root[data-theme=\"dark\"]", tokens["dark"]) +
            f"\n:root {{\n  --radius: {int(tokens['radius'])}px;\n  --font-head: '{fam(fh)}', Tahoma, sans-serif;\n  --font-body: '{fam(fb)}', Tahoma, sans-serif;\n{sp}\n{ty}\n}}\n")


# ───────────────────────────── ساختِ سایت از این طرح

class SiteError(ValueError):
    pass


def _unique_slug(base: str) -> str:
    from apps.projects.models import Project

    base = re.sub(r"[^a-z0-9-]+", "-", base.lower()).strip("-") or "design"
    slug, n = base, 1
    while Project.objects.filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"
    return slug[:110]


def _slug_for(name: str, used: set[str], i: int) -> str:
    base = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    if not base:
        base = f"page-{i + 1}"
    s, n = base, 1
    while s in used:
        n += 1
        s = f"{base}-{n}"
    used.add(s)
    return s


def site_plan(data: dict) -> dict:
    """طرح ⇒ برنامهٔ سایت (بدونِ دیتابیس): صفحه‌ها، سربرگ، پابرگ و نگاشتِ فریم ⇒ نشانیِ صفحه."""
    pages_src = [f for f in data["frames"] if not f.get("of") and f.get("device") in ("desktop", "tablet", "phone")]
    desktops = [f for f in pages_src if f["device"] == "desktop"] or pages_src[:1]
    if not desktops:
        raise SiteError("فریمی برای ساختِ سایت نیست.")
    header = footer = None
    used: set[str] = set()
    pages = []
    for i, f in enumerate(desktops):
        kids = [n for n in f["children"] if n.get("t") == "block"]
        if header is None:
            h = next((n for n in kids if str(n.get("type", "")).startswith(("c_nav", "site_header"))), None)
            header = h
        if footer is None:
            fo = next((n for n in kids if str(n.get("type", "")).startswith(("c_footer",))), None)
            footer = fo
        body = [n for n in kids if not str(n.get("type", "")).startswith(("c_nav", "site_header", "c_footer"))]
        slug = "" if i == 0 else _slug_for(re.sub(r"[^A-Za-z0-9 -]+", "", f.get("name", "")) or f"page-{i + 1}", used, i)
        pages.append({"frame": f["id"], "title": f.get("name") or f"صفحهٔ {i + 1}", "slug": slug, "blocks": body, "home": i == 0})
    path_of = {p["frame"]: "/" + (p["slug"] + "/" if p["slug"] else "") for p in pages}
    for f in data["frames"]:                                    # فریم‌های واکنش‌گرا به صفحهٔ اصلی‌شان می‌روند
        if f.get("of") in path_of:
            path_of[f["id"]] = path_of[f["of"]]
    return {"pages": pages, "header": header, "footer": footer, "path_of": path_of}


def _apply_links(block: dict, path_of: dict) -> dict:
    """پیوندِ نمونهٔ اولیهٔ یک بلوک ⇒ مشخصه‌های پیوندِ خودِ بلوک (فقط وقتی خالی یا «#» است)."""
    b = copy.deepcopy(block)
    lk = b.get("link")
    props = b.setdefault("props", {})
    if isinstance(lk, dict) and lk.get("frame") in path_of:
        for k in LINK_KEYS:
            if k in props and (not props[k] or props[k] == "#"):
                props[k] = path_of[lk["frame"]]
    b.pop("link", None)
    b.pop("t", None)
    if isinstance(b.get("children"), list):
        b["children"] = [_apply_links(c, path_of) for c in b["children"] if isinstance(c, dict)]
    return b


def to_site(data: dict, info, *, name: str = "", slug: str = "", logo_bytes: bytes | None = None) -> dict:
    """طرح ⇒ پروژهٔ «پیش‌نویس» در سایت‌ساز (هیچ‌چیز منتشر یا اجرا نمی‌شود). ⇒ {project_id، slug، pages، url}."""
    from apps.projects.builder import publish as P, styles
    from apps.projects.builder import theme as theme_mod
    from apps.projects.builder.clean import clean_doc
    from apps.projects.models import Design, Page, Project, SiteTheme

    plan = site_plan(data)
    s = {**uf.DEFAULTS, **(data.get("settings") or {})}
    tokens = uf.tokens_for(s, uf.brand_primary_of(info))
    brand = tokens["light"]["primary"]
    site_name = getattr(info, "name", "") or name or "طرح"
    p = Project.objects.create(name=(name or f"{site_name} — پیش‌نویس از استودیوی طراحی")[:120], slug=_unique_slug(slug or f"design-{site_name}"), brand_color=brand, site_title=site_name[:120],
                               description="پیش‌نویسِ ساخته‌شده از «استودیوی طراحی»؛ منتشر نشده است.")
    logo_ref = ""
    if logo_bytes:
        try:
            from django.core.files.uploadedfile import SimpleUploadedFile

            from apps.projects.builder import media

            asset = media.save_upload(p, SimpleUploadedFile("logo.png", logo_bytes, content_type="image/png"), alt=site_name)
            logo_ref = f"m:{asset.pk}"
        except Exception:  # noqa: BLE001 — بدونِ لوگو هم کار می‌کند
            logo_ref = ""

    def fix(block):
        b = _apply_links(block, plan["path_of"])
        if logo_ref and "logo" in (b.get("props") or {}) and not b["props"].get("logo"):
            b["props"]["logo"] = logo_ref
            b["props"].setdefault("logo_alt", site_name)
        return b

    th = theme_mod.default_theme()
    th["colors"]["primary"] = brand
    key = tokens["style"] if tokens["style"] in styles.STYLES else None
    if key:
        th = styles.apply_to_theme(th, key, keep_brand=True)
    fh, fb = fonts.clean(s.get("font_head")), fonts.clean(s.get("font_body"))
    th["font_head"], th["font_body"] = ("estedad" if fh == "estedad" else "vazirmatn"), ("estedad" if fb == "estedad" else "vazirmatn")
    th = theme_mod.clean_theme(th)
    created = []
    for i, pg in enumerate(plan["pages"]):
        page = Page.objects.create(project=p, title=pg["title"][:120], slug=pg["slug"], kind="home" if pg["home"] else "static", body_html="", in_menu=not pg["home"], order=10 + i * 10)
        doc = clean_doc({"v": 1, "blocks": [fix(b) for b in pg["blocks"]]}, "page")
        Design.objects.create(project=p, target="page", page=page, draft=doc, synced_hash=P.fingerprint(p, "page", page))
        created.append({"frame": pg["frame"], "title": pg["title"], "slug": pg["slug"], "blocks": len(doc["blocks"]), "page_id": page.pk})
    for target, blk in (("header", plan["header"]), ("footer", plan["footer"])):
        doc = clean_doc({"v": 1, "blocks": [fix(blk)] if blk else []}, target)
        Design.objects.create(project=p, target=target, draft=doc, synced_hash=P.fingerprint(p, target, None))
    t, _ = SiteTheme.objects.get_or_create(project=p)
    t.draft = th
    t.menu = [{"id": f"m{i + 1}", "url": plan["path_of"][pg["frame"]], "label": pg["title"][:40]} for i, pg in enumerate(plan["pages"])]
    t.save()
    first = created[0]["page_id"] if created else None
    return {"project_id": p.pk, "slug": p.slug, "pages": created, "url": f"/panel/tools/studio/p/{p.slug}",
            "builder_url": f"/panel/tools/studio/p/{p.slug}/builder/page/{first}" if first else f"/panel/tools/studio/p/{p.slug}", "style": tokens["style"], "published": False, "exists": True}
