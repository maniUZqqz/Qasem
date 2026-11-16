# -*- coding: utf-8 -*-
"""تبدیلِ قطعهٔ React/Tailwind به «قطعهٔ جاسازی‌شدهٔ امنِ» سایت‌ساز (HTML ساکن + CSSِ محدود به خودش + شکاف‌های متن/تصویر/پیوند).

مراحل (همه روی همین سرور، بی‌مرورگر و بی‌اینترنت؛ جعبه‌ابزار در /opt/nm-c21):

1. ``run_node`` — ``deploy/c21/convert.mjs``: esbuild کدِ «نمونهٔ استفاده» + کدِ قطعه را بسته‌بندی می‌کند، react-dom/server رندرش می‌کند، Tailwind v4
   فقط کلاس‌های به‌کاررفته را می‌سازد و postcss همه را زیرِ ``.nbc21-<کلید>`` می‌برد (و left/right را منطقی می‌کند تا راست‌به‌چپ آینه شود).
2. ``sanitize`` — HTMLِ رندرشده را با فهرستِ سفید پاک می‌کند (بی‌script، بی‌onclick، بی‌iframe، بی‌پیوندِ بیرونی، بی‌url() ) و
   متن‌ها، تصویرها و پیوندها را «شکاف» می‌کند تا روی بوم قابلِ ویرایش باشند.
3. ``store`` — ``NM_DATA_DIR/c21st/converted/<کلید>.json`` + ``index.json``.

چیزی که تبدیل نمی‌شود (کتابخانهٔ بیرونیِ ناشناخته، سه‌بعدی/canvas، فایلِ بیش از حد بزرگ) «فقط کاتالوگ» می‌ماند؛ علتش در رکورد (``error``) ثبت می‌شود.
"""
from __future__ import annotations

import hashlib
import html as html_mod
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from html.parser import HTMLParser
from pathlib import Path

from . import c21st

logger = logging.getLogger(__name__)

TOOLCHAIN = Path(os.environ.get("NM_C21_TOOLCHAIN", "/opt/nm-c21"))
NODE = os.environ.get("NM_C21_NODE", "node")
MAX_HTML = 70_000
MAX_CSS = 90_000
MAX_TEXTS = 60                 # = clean.MAX_ITEMS
MAX_LINKS = 30
MAX_IMAGES = 30
NODE_TIMEOUT = 120

SCOPE_PREFIX = "nbc21-"


class ConvertError(RuntimeError):
    """علتِ فارسی/انگلیسیِ کوتاه که در رکورد می‌ماند."""


def key_for(cid: str) -> str:
    return "x" + hashlib.sha1(cid.encode("utf-8")).hexdigest()[:9]


def scope_for(key: str) -> str:
    return SCOPE_PREFIX + key


def toolchain_ready() -> bool:
    return (TOOLCHAIN / "convert.mjs").is_file() and (TOOLCHAIN / "node_modules" / "esbuild").is_dir()


# ───────────────────────────── گره (esbuild + tailwind)

#: کدِ قطعه را نویسندهٔ دیگری نوشته و رندرِ سمتِ سرور آن را «اجرا» می‌کند؛ پس در یک «قفس» اجرا می‌شود:
#: محیطِ تمیز (هیچ کلید/رمزی از فرایندِ Celery نمی‌رسد)، کاربرِ nobody (اگر سرور root است)، بی‌شبکه (`unshare -n`) و سقفِ زمان و حافظه.
SAFE_ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "NODE_ENV": "production", "LANG": "C.UTF-8", "NODE_OPTIONS": "--max-old-space-size=1024"}
_NET_OK: dict = {}


def _net_isolation() -> list[str]:
    """پیشوندِ فرمان: ['unshare','-n'] (بی‌شبکه) و اگر سرور root است با «-S 65534 -G 65534» (همان‌جا به nobody می‌رود)؛ اگر کار نکرد []."""
    drop = _drop_ok()
    if drop not in _NET_OK:
        exe = shutil.which("unshare")
        prefix = [exe, "-n", "-S", "65534", "-G", "65534"] if (exe and drop) else [exe, "-n"]
        ok = False
        if exe:
            try:
                ok = subprocess.run(prefix + ["true"], capture_output=True, timeout=10).returncode == 0
            except (OSError, subprocess.SubprocessError):
                ok = False
        _NET_OK[drop] = prefix if ok else []
    return _NET_OK[drop]


def _drop_privileges():                                # در فرزند، پیش از exec
    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(65534)
        os.setuid(65534)


def _drop_ok() -> bool:
    """فقط وقتی سرور root است؛ NM_C21_RUN_AS=root برای محیط‌هایی که nobody نمی‌تواند به پوشهٔ داده برسد (مثلاً زیرِ /root)."""
    return os.geteuid() == 0 and os.environ.get("NM_C21_RUN_AS", "nobody") != "root"


def sandbox_kwargs(tmp: Path, prefix: list[str] | None = None) -> dict:
    kw = {"env": dict(SAFE_ENV), "cwd": str(TOOLCHAIN)}
    if _drop_ok():
        os.chown(tmp, 65534, 65534)
        if "-S" not in (prefix or []):                   # unshare خودش به nobody نمی‌برد ⇒ در فرزند
            kw["preexec_fn"] = _drop_privileges
    return kw


def run_node(job: dict, *, timeout: int = NODE_TIMEOUT, runner=subprocess.run) -> dict:
    """job ⇒ {ok, html, css, warnings, error?}؛ خطای ابزار ⇒ ConvertError. (در قفس؛ نگاه کنید به SAFE_ENV.)"""
    if not toolchain_ready() and runner is subprocess.run:
        raise ConvertError("جعبه‌ابزارِ تبدیل (/opt/nm-c21) نصب نیست؛ deploy/c21/install.sh را اجرا کنید.")
    tmp = Path(tempfile.mkdtemp(prefix="nm-c21-job-"))
    try:
        jp, op = tmp / "job.json", tmp / "out.json"
        jp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        os.chmod(tmp, 0o755)
        os.chmod(jp, 0o644)
        prefix = _net_isolation()
        try:
            r = runner(prefix + [NODE, str(TOOLCHAIN / "convert.mjs"), str(jp), str(op)], capture_output=True, text=True, timeout=timeout, **sandbox_kwargs(tmp, prefix))
        except subprocess.TimeoutExpired as exc:
            raise ConvertError("تبدیل بیش از %d ثانیه طول کشید" % timeout) from exc
        if not op.exists():
            raise ConvertError(("تبدیل خروجی نداد: " + (r.stderr or "")[-300:]).strip())
        return json.loads(op.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ───────────────────────────── پاک‌سازی و شکاف‌سازی

VOID = {"img", "br", "hr", "input", "source", "wbr", "meta", "link"}
SVG_VOID = {"path", "circle", "ellipse", "rect", "line", "polyline", "polygon", "stop", "use"}
HTML_TAGS = {"div", "span", "p", "a", "img", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "section", "header", "nav", "footer", "main", "article", "aside", "figure",
             "figcaption", "button", "strong", "em", "b", "i", "u", "small", "sup", "sub", "br", "hr", "blockquote", "cite", "code", "pre", "kbd", "table", "thead", "tbody", "tfoot", "tr",
             "td", "th", "caption", "dl", "dt", "dd", "details", "summary", "label", "input", "textarea", "select", "option", "mark", "time", "abbr", "address", "span", "svg", "form"}
SVG_TAGS = {"svg", "g", "path", "circle", "ellipse", "rect", "line", "polyline", "polygon", "defs", "lineargradient", "radialgradient", "stop", "clippath", "mask", "title", "desc",
            "symbol"}
DROP_WHOLE = {"script", "style", "iframe", "object", "embed", "link", "meta", "noscript", "template", "video", "audio", "source", "canvas", "map", "area", "base", "frame",
              "frameset", "param", "picture", "foreignobject", "image", "use", "animate", "animatetransform", "set", "filter"}
GLOBAL_ATTRS = {"class", "role", "tabindex", "title", "lang", "dir", "hidden", "alt", "width", "height", "type", "disabled", "placeholder", "colspan", "rowspan", "open", "datetime",
                "for", "checked", "readonly", "rows", "cols", "maxlength", "min", "max", "value", "aria-hidden", "aria-label", "aria-expanded", "aria-selected", "aria-current",
                "aria-disabled", "aria-hidden", "aria-orientation", "aria-roledescription", "aria-live", "aria-pressed", "aria-checked"}
SVG_ATTRS = {"viewbox", "d", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-miterlimit", "stroke-dasharray", "stroke-dashoffset", "cx", "cy", "r",
             "rx", "ry", "x", "y", "x1", "y1", "x2", "y2", "points", "transform", "offset", "stop-color", "stop-opacity", "gradientunits", "gradienttransform", "opacity", "fill-rule",
             "clip-rule", "clip-path", "preserveaspectratio", "xmlns", "focusable", "fill-opacity", "stroke-opacity", "mask", "fx", "fy", "spreadmethod", "clippathunits",
             "maskunits", "id", "vector-effect", "mask-type", "href"}
SAFE_STYLE_PROPS = {"width", "height", "min-width", "min-height", "max-width", "max-height", "color", "background", "background-color", "background-image", "background-size",
                    "background-position", "opacity", "transform", "transform-origin", "display", "position", "top", "bottom", "inset-inline-start", "inset-inline-end", "z-index",
                    "margin", "margin-top", "margin-bottom", "margin-inline-start", "margin-inline-end", "padding", "padding-top", "padding-bottom", "padding-inline-start",
                    "padding-inline-end", "flex", "flex-direction", "gap", "grid-template-columns", "grid-column", "aspect-ratio", "border-radius", "border", "border-color",
                    "box-shadow", "filter", "overflow", "font-size", "font-weight", "line-height", "text-align", "animation-delay", "animation-duration", "animation-direction",
                    "mask-image", "-webkit-mask-image", "--duration", "--gap", "--delay", "--index", "--size", "--x", "--y", "--angle", "left", "right"}
STYLE_PHYS = {"left": "inset-inline-start", "right": "inset-inline-end", "margin-left": "margin-inline-start", "margin-right": "margin-inline-end",
              "padding-left": "padding-inline-start", "padding-right": "padding-inline-end"}
BAD_VALUE = re.compile(r"url\(|expression\(|javascript:|@import|behavior|-moz-binding|<|>|\\", re.I)
CSS_BAD = re.compile(r"@import|expression\(|</style|javascript:|(?<![\w-])behaviou?r\s*:|-moz-binding", re.I)


class _Node:
    __slots__ = ("tag", "attrs", "kids", "svg")

    def __init__(self, tag, attrs, svg):
        self.tag, self.attrs, self.kids, self.svg = tag, attrs, [], svg


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root", {}, False)
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        parent = self.stack[-1]
        node = _Node(tag.lower(), {k.lower(): (v if v is not None else "") for k, v in attrs}, parent.svg or tag.lower() == "svg")
        parent.kids.append(node)
        if tag.lower() not in VOID and not (node.svg and tag.lower() in SVG_VOID):
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        parent = self.stack[-1]
        parent.kids.append(_Node(tag.lower(), {k.lower(): (v if v is not None else "") for k, v in attrs}, parent.svg or tag.lower() == "svg"))

    def handle_endtag(self, tag):
        tag = tag.lower()
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].kids.append(data)


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def clean_style(value: str) -> str:
    out = []
    for decl in (value or "").split(";"):
        if ":" not in decl:
            continue
        prop, _, val = decl.partition(":")
        prop, val = prop.strip().lower(), val.strip()
        if prop in STYLE_PHYS:
            prop = STYLE_PHYS[prop]
        if prop not in SAFE_STYLE_PROPS or not val or BAD_VALUE.search(val):
            continue
        if prop in ("background", "background-image", "mask-image", "-webkit-mask-image") and "gradient" not in val.lower():
            continue
        out.append("%s:%s" % (prop, val))
    return ";".join(out)


class Slots:
    """متن‌ها، تصویرها و پیوندهای یک قطعه؛ مقدارِ تکراری یک شکاف می‌گیرد (نوارِ متحرکِ دوبل‌شده با یک ویرایش عوض می‌شود)."""

    def __init__(self):
        self.texts: list[str] = []
        self.links: list[str] = []
        self.images: list[dict] = []
        self._t: dict[str, int] = {}
        self._i: dict[str, int] = {}
        self.warnings: list[str] = []

    def text(self, value: str):
        if value in self._t:
            return self._t[value]
        if len(self.texts) >= MAX_TEXTS:
            return None
        self._t[value] = len(self.texts)
        self.texts.append(value)
        return self._t[value]

    def link(self):
        if len(self.links) >= MAX_LINKS:
            return None
        self.links.append("#")
        return len(self.links) - 1

    def image(self, alt: str, key: str):
        if key in self._i:
            return self._i[key]
        if len(self.images) >= MAX_IMAGES:
            return None
        self._i[key] = len(self.images)
        self.images.append({"alt": alt[:200]})
        return self._i[key]


def _attr_ok(node: _Node, name: str) -> bool:
    if name.startswith("data-") and re.fullmatch(r"data-[a-z0-9-]{1,40}", name):
        return True
    if name.startswith("aria-"):
        return name in GLOBAL_ATTRS
    if node.svg:
        return name in SVG_ATTRS or name in {"class", "role", "aria-hidden", "aria-label", "width", "height", "title"}
    return name in GLOBAL_ATTRS


def _emit(node, slots: Slots, scope: str, ids: dict) -> str:
    if isinstance(node, str):
        return esc(node)
    tag = node.tag
    if tag in DROP_WHOLE:
        if tag in ("video", "picture", "canvas", "iframe"):
            slots.warnings.append("dropped <%s>" % tag)
        return ""
    allowed = SVG_TAGS if node.svg else HTML_TAGS
    if tag not in allowed:
        # عنصرِ ناشناخته (مثلاً کامپوننتِ سفارشی): محتوایش می‌ماند، خودش نه
        return "".join(_emit(k, slots, scope, ids) for k in node.kids)
    if tag == "form":
        tag = "div"
    attrs = {}
    for name, val in node.attrs.items():
        if name.startswith("on") or name in ("style",) or name in ("href", "src", "srcset", "id", "xlink:href", "action", "formaction", "name", "autofocus", "for"):
            continue
        if name == "class":                                    # فقط کلاسِ خطرناک (مثلاً bg-[url(...)]) می‌افتد، نه همهٔ کلاس‌های عنصر
            val = " ".join(c for c in val.split() if not BAD_VALUE.search(c))
            if val:
                attrs[name] = val
        elif _attr_ok(node, name) and not BAD_VALUE.search(val):
            attrs[name] = val
    if node.svg:
        if "id" in node.attrs and re.fullmatch(r"[\w:.-]{1,60}", node.attrs["id"]):
            new = "%s-%s" % (scope[len(SCOPE_PREFIX):], node.attrs["id"])
            ids[node.attrs["id"]] = new
            attrs["id"] = new
        for name in ("fill", "stroke", "clip-path", "mask"):
            v = node.attrs.get(name, "")
            m = re.fullmatch(r"url\(#([\w:.-]{1,60})\)", v.strip())
            if m:
                attrs[name] = "url(#%s)" % ids.get(m.group(1), "%s-%s" % (scope[len(SCOPE_PREFIX):], m.group(1)))
    st = clean_style(node.attrs.get("style", ""))
    if st:
        attrs["style"] = st
    if tag == "button":
        attrs["type"] = "button"
    if tag == "input":
        attrs["type"] = attrs.get("type", "text") if attrs.get("type", "text") in ("text", "email", "search", "tel", "number", "checkbox", "radio") else "text"
        attrs["readonly"] = ""
        attrs.pop("value", None)
    out_attrs = ""
    extra = ""
    if tag == "img":
        n = slots.image(node.attrs.get("alt", ""), node.attrs.get("src", "") or str(len(slots.images)))
        if n is None:
            return ""
        attrs.pop("alt", None)
        cls = attrs.pop("class", "")
        extra = ' data-nbi="%d"%s%s' % (n, ' class="%s"' % esc(cls) if cls else "", "".join(' %s="%s"' % (k, esc(v)) for k, v in attrs.items() if k in ("width", "height")))
        return "<img%s>" % extra
    if tag == "a" and not node.svg:
        n = slots.link()
        if n is not None:
            extra = ' data-nbl="%d"' % n
    # متن
    kids = node.kids
    inner = ""
    texts = [k for k in kids if isinstance(k, str) and k.strip()]
    sole = len(kids) == 1 and isinstance(kids[0], str) and kids[0].strip() and tag not in ("svg", "textarea", "select", "option") and not node.svg
    if sole:
        value = re.sub(r"\s+", " ", kids[0]).strip()
        n = slots.text(value)
        if n is not None:
            extra += ' data-nbt="%d"' % n
            inner = "{{T%d}}" % n
        else:
            inner = esc(value)
    else:
        parts = []
        for k in kids:
            if isinstance(k, str):
                if not k.strip() or node.svg:
                    parts.append(" " if k else "")
                    continue
                value = re.sub(r"\s+", " ", k).strip()
                lead, trail = " " if k[:1].isspace() else "", " " if k[-1:].isspace() else ""
                n = slots.text(value)
                if n is None:
                    parts.append(lead + esc(value) + trail)
                else:
                    parts.append('%s<span data-nbt="%d">{{T%d}}</span>%s' % (lead, n, n, trail))
            else:
                parts.append(_emit(k, slots, scope, ids))
        inner = "".join(parts)
    out_attrs = "".join(' %s="%s"' % (k, esc(v)) if v != "" else " %s" % k for k, v in attrs.items())
    if node.svg and tag in SVG_VOID:
        return "<%s%s/>" % (tag, out_attrs)
    if tag in VOID:
        return "<%s%s>" % (tag, out_attrs + extra)
    return "<%s%s%s>%s</%s>" % (tag, out_attrs, extra, inner, tag)


def sanitize(markup: str, scope: str) -> dict:
    """HTMLِ رندرشده ⇒ {template, texts[], links[], images[], warnings[]}. در قالب: {{T3}} = متنِ ۳، data-nbt/data-nbi/data-nbl = جای ویرایش."""
    tree = _Tree()
    tree.feed(markup or "")
    tree.close()
    slots = Slots()
    ids: dict = {}
    body = "".join(_emit(k, slots, scope, ids) for k in tree.root.kids)
    body = re.sub(r"\s{2,}", " ", body).strip()
    # دورِ ریشهٔ «c21-root» که خودِ ابزار گذاشته؛ محتوای داخلش کافی است
    m = re.fullmatch(r"<div>(.*)</div>", body, re.S)
    if m:
        body = m.group(1)
    if len(body) > MAX_HTML:
        raise ConvertError("HTML خیلی بزرگ است (%d نویسه)" % len(body))
    return {"template": body, "texts": slots.texts, "links": slots.links, "images": slots.images, "warnings": slots.warnings}


def check_css(css: str) -> str:
    if len(css) > MAX_CSS:
        raise ConvertError("CSS خیلی بزرگ است (%d نویسه)" % len(css))
    if CSS_BAD.search(css) or css.count("{") != css.count("}"):
        raise ConvertError("CSS ناامن یا ناقص")
    if re.search(r"url\(\s*['\"]?(?!#|data:image/svg)", css):
        raise ConvertError("CSS آدرسِ بیرونی دارد")
    return css


# ───────────────────────────── ذخیره

def converted_dir() -> Path:
    d = c21st.root() / "converted"
    d.mkdir(parents=True, exist_ok=True)
    return d


def record_path(key: str) -> Path:
    return converted_dir() / (key + ".json")


def load_record(key: str) -> dict | None:
    if not re.fullmatch(r"x[0-9a-f]{9}", key or ""):
        return None
    try:
        return json.loads(record_path(key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_index() -> dict:
    try:
        return json.loads((converted_dir() / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_record(rec: dict) -> None:
    c21st._atomic(record_path(rec["key"]), json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
    idx = load_index()
    idx[rec["id"]] = {"key": rec["key"], "title": rec.get("title", ""), "cats": rec.get("cats", []), "license": rec.get("license", ""), "author": rec.get("author", ""),
                      "library": rec.get("library", ""), "texts": len(rec.get("texts", [])), "images": len(rec.get("images", [])), "rtl": (rec.get("rtl") or {}).get("status", ""),
                      "bytes": len(rec.get("css", "")) + len(rec.get("template", "")), "converted_at": rec.get("converted_at", "")}
    c21st._atomic(converted_dir() / "index.json", json.dumps(idx, ensure_ascii=False, separators=(",", ":")))
    _CACHE.pop(rec["key"], None)


def remove_record(cid: str) -> bool:
    idx = load_index()
    ent = idx.pop(cid, None)
    if not ent:
        return False
    try:
        record_path(ent["key"]).unlink()
    except OSError:
        pass
    c21st._atomic(converted_dir() / "index.json", json.dumps(idx, ensure_ascii=False, separators=(",", ":")))
    _CACHE.pop(ent["key"], None)
    return True


_CACHE: dict = {}


def get_record(key: str) -> dict | None:
    """با حافظهٔ کوچک (سقفِ ۶۰ رکورد)."""
    rec = _CACHE.get(key)
    if rec is None:
        rec = load_record(key)
        if rec is not None:
            if len(_CACHE) > 60:
                _CACHE.clear()
            _CACHE[key] = rec
    return rec


# ───────────────────────────── یک قطعه از اول تا آخر

def convert_bundle(cid: str, bundle: dict, *, meta: dict | None = None, runner=subprocess.run) -> dict:
    """bundle = {entry: {path, code}, files: {specifier: code}, roots: [...], export?, source: {kind, repo, path, commit, license}}
    ⇒ رکوردِ ذخیره‌شده. خطا ⇒ ConvertError (علت در پیام)."""
    meta = meta or {}
    key = key_for(cid)
    scope = scope_for(key)
    job = {"id": cid, "scope": scope, "entry": bundle["entry"], "files": bundle.get("files") or {}, "aliases": bundle.get("aliases") or {}, "roots": bundle.get("roots") or [], "export": bundle.get("export") or "auto"}
    res = run_node(job, runner=runner)
    if not res.get("ok"):
        raise ConvertError(res.get("error") or "تبدیل ناموفق")
    sl = sanitize(res["html"], scope)
    css = check_css(res["css"])
    if not sl["template"].strip():
        raise ConvertError("خروجی خالی است")
    rec = {"id": cid, "key": key, "scope": scope, "title": meta.get("title", ""), "description": meta.get("description", ""), "cats": meta.get("cats", []),
           "license": meta.get("license", ""), "author": meta.get("author", ""), "library": meta.get("library", ""), "url": meta.get("url", ""),
           "source": bundle.get("source") or {}, "template": sl["template"], "css": css, "texts": sl["texts"], "links": sl["links"], "images": sl["images"],
           "warnings": (res.get("warnings") or []) + sl["warnings"], "stats": res.get("stats") or {}, "rtl": {"status": "unchecked"},
           "converted_at": c21st._now() if hasattr(c21st, "_now") else time.strftime("%Y-%m-%dT%H:%M:%S")}
    return rec
