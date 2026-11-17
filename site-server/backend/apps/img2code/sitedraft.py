# -*- coding: utf-8 -*-
"""«ساختِ صفحه در سایت‌ساز»: درختِ اجزای یک تبدیل ⇒ **پیش‌نویسِ** صفحه (Page + Design) در یک پروژهٔ سایت‌ساز که به همین فروشگاه وصل است.

* هرگز منتشر نمی‌شود: ``Design.published`` خالی می‌ماند، ``SiteTheme.active=False`` و ``Page.body_html`` خالی است؛ فقط در ویرایشگرِ دیداری دیده می‌شود.
* اگر فروشگاه پروژه‌ای ندارد (یا کاربر «پروژهٔ تازه» بخواهد) یک پروژهٔ تازه با صفحهٔ اصلی، سربرگ، پابرگ و پوسته (رنگ‌ها از تصویر) ساخته و به فروشگاه وصل می‌شود
  (همان ``SiteBinding`` ِ شخصیتِ برند)؛ اگر پروژهٔ موجودی انتخاب شود فقط یک صفحهٔ تازه به آن اضافه می‌شود و سربرگ/پابرگ/پوسته‌اش دست نمی‌خورد
  (سربرگ و پابرگِ تصویر در خودِ صفحه می‌آیند).
* تصویرها و لوگو تکه‌هایی از همان اسکرین‌شات‌اند که به کتابخانهٔ رسانهٔ پروژه می‌روند (``m:<شناسه>``)؛ هیچ تصویرِ ساختگی گذاشته نمی‌شود.
"""
from __future__ import annotations

import io
import json
import logging
from typing import Optional

from django.db import transaction
from django.utils import timezone

from . import mapping
from .models import Conversion
from .services import Img2CodeError

log = logging.getLogger(__name__)


def targets(store) -> list[dict]:
    """پروژه‌های سایت‌ساز که به این فروشگاه وصل‌اند."""
    from apps.brandchar.models import SiteBinding
    from apps.projects.models import Project

    slugs = list(SiteBinding.objects.filter(store=store).values_list("project_slug", flat=True))
    out = []
    for p in Project.objects.filter(slug__in=slugs).order_by("-updated_at")[:30]:
        out.append({"slug": p.slug, "name": p.name, "pages": p.pages.count()})
    return out


def _walk(blocks, fn) -> None:
    for b in blocks or []:
        fn(b)
        _walk(b.get("children"), fn)


def _load_image(conv: Conversion):
    import numpy as np
    from PIL import Image
    p = conv.out_dir / "original.png"
    if not p.is_file():
        raise Img2CodeError("تصویرِ اصلیِ این تبدیل پیدا نشد.", "no_original", 409)
    im = Image.open(p).convert("RGB")
    return im, np.array(im)


def _upload_crops(project, im, crops: list, warnings: list) -> dict:
    """تکه‌های تصویر ⇒ رسانهٔ پروژه؛ ⇒ {'crop:c1': 'm:12'}."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from apps.projects.builder import media
    refs: dict = {}
    for c in crops:
        x, y, w, h = c["box"]
        x1, y1 = min(im.width, x + w), min(im.height, y + h)
        if x1 - x < 4 or y1 - y < 4:
            continue
        buf = io.BytesIO()
        im.crop((x, y, x1, y1)).save(buf, "PNG", optimize=True)
        try:
            asset = media.save_upload(project, SimpleUploadedFile("img2code-%s.png" % c["key"], buf.getvalue(), content_type="image/png"), alt=c.get("alt") or "")
            refs["crop:" + c["key"]] = "m:%d" % asset.pk
        except media.MediaError as exc:
            warnings.append("یک تصویر به کتابخانهٔ رسانه نرفت: %s" % exc)
    return refs


def _apply_refs(doc: Optional[dict], refs: dict) -> None:
    if not doc:
        return

    def fix(b):
        for k, v in list(b.get("props", {}).items()):
            if isinstance(v, str) and v.startswith("crop:"):
                b["props"][k] = refs.get(v, "")
    _walk(doc.get("blocks"), fix)


def create_draft(conv: Conversion, user, project_slug: str = "", page_title: str = "") -> dict:
    """⇒ {project_slug, page_id, url, created_project, warnings, stats}. هیچ‌چیز منتشر نمی‌شود."""
    from apps.brandchar.models import SiteBinding
    from apps.projects.builder import publish as P
    from apps.projects.builder.clean import DocError
    from apps.projects.models import Design, Page, Project, SiteTheme

    if conv.state != Conversion.State.READY:
        raise Img2CodeError("هنوز تبدیل تمام نشده است.", "not_ready", 409)
    tree_path = conv.out_dir / "tree.json"
    if not tree_path.is_file():
        raise Img2CodeError("درختِ اجزای این تبدیل پیدا نشد.", "no_tree", 409)
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    im, arr = _load_image(conv)

    project = None
    if project_slug:
        project = Project.objects.filter(slug=project_slug).first()
        if project is None or not SiteBinding.objects.filter(project_slug=project_slug, store=conv.store).exists():
            raise Img2CodeError("این پروژهٔ سایت‌ساز به این فروشگاه وصل نیست.", "bad_project", 404)
    new_project = project is None

    result = mapping.map_tree(tree, arr, chrome=new_project)
    warnings = list(result["warnings"]) + list(conv.warnings or [])
    warnings = [w for w in warnings if "OCR" not in w or conv.source_kind != "url"]

    # سایت‌ساز پایگاهِ جدا دارد (alias ِ studio)؛ هر دو یک‌جا تأیید یا برگردانده شوند
    with transaction.atomic(using="studio"), transaction.atomic():
        if new_project:
            brand = result.get("site_title") or conv.store.name
            project = Project.objects.create(
                name=("%s — از تصویر #%d" % (conv.store.name, conv.pk))[:120], brand_color=result["theme"]["colors"]["primary"], site_title=str(brand)[:120],
                description="پیش‌نویسِ ساخته‌شده از یک تصویر با «تصویر به کد» (فقط پیش‌نویس؛ چیزی منتشر نشده).")
            SiteBinding.objects.update_or_create(project_slug=project.slug, defaults={"store": conv.store})
        refs = _upload_crops(project, im, result["crops"], warnings)
        for key in ("page", "header", "footer"):
            _apply_refs(result.get(key), refs)
        try:
            docs = mapping.clean_docs(result)
        except DocError as exc:
            raise Img2CodeError("ساختارِ ساخته‌شده را سایت‌ساز نپذیرفت: %s" % exc, "bad_doc", 422) from None
        title = (page_title or conv.title or "صفحه از تصویر")[:120]
        if new_project:
            page = Page.objects.create(project=project, title="صفحهٔ اصلی", slug="", kind="home", body_html="", in_menu=False, order=10)
        else:
            slug = "from-image-%d" % conv.pk
            n = 2
            while Page.objects.filter(project=project, slug=slug).exists():
                slug = "from-image-%d-%d" % (conv.pk, n)
                n += 1
            page = Page.objects.create(project=project, title=title, slug=slug, kind="static", body_html="", in_menu=False, order=900 + conv.pk % 90)
        Design.objects.create(project=project, target="page", page=page, draft=docs["page"], synced_hash=P.fingerprint(project, "page", page))
        if new_project:
            for target in ("header", "footer"):
                Design.objects.create(project=project, target=target, draft=docs.get(target) or {"v": 1, "blocks": []}, synced_hash=P.fingerprint(project, target, None))
            theme, _ = SiteTheme.objects.get_or_create(project=project)
            theme.draft = result["theme"]
            theme.menu = result["menu"]
            theme.active = False
            theme.save()
        conv.draft_project_slug = project.slug
        conv.draft_page_id = page.pk
        conv.draft_at = timezone.now()
        conv.save(update_fields=["draft_project_slug", "draft_page_id", "draft_at", "updated_at"])
    blocks = 0

    def count(_b):
        nonlocal blocks
        blocks += 1
    _walk(docs["page"]["blocks"], count)
    return {"project_slug": project.slug, "page_id": page.pk, "url": "/tools/studio/p/%s/builder/page/%d" % (project.slug, page.pk), "created_project": new_project,
            "warnings": warnings, "stats": {**result["stats"], "blocks": blocks, "images": len(refs)}}
