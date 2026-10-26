# -*- coding: utf-8 -*-
"""صفحه‌های عمومیِ تیم: فهرستِ تیم، رزومه (+PDF)، نمونه‌کارها و جزئیاتِ پروژه.

قاعده‌ها:
* فقط «منتشر شود»ها دیده می‌شوند؛ مدیر (is_staff) پیش‌نمایشِ پیش‌نویس را می‌بیند.
* بخشِ خالی اصلاً چاپ نمی‌شود (قالب‌ها با {% if %}).
* هر صفحه تعدادِ ثابتی کوئری می‌زند (prefetch) — نه یکی به ازای هر ردیف.
"""
import base64
import glob
import hashlib
import json
import logging
import os
import re
from collections import OrderedDict
from urllib.parse import quote

from django.conf import settings
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.text import Truncator

from app.models import TeamMember

from .jalali import iso_ym
from .models import (Award, Certification, Education, Experience, LanguageSkill, PortfolioCategory,
                     PortfolioProject, ProjectMember, Skill, SocialLink)
from .thumbs import thumbnail

logger = logging.getLogger(__name__)
SECTION_MODELS = (SocialLink, Experience, Education, Certification, Skill, LanguageSkill, Award)
ORG = {'@type': 'Organization', 'name': 'چغر', 'url': 'https://chagher.ir/'}


# ─────────────────────────── ابزارها ───────────────────────────
def _can_preview(request):
    user = getattr(request, 'user', None)
    return bool(user and user.is_authenticated and user.is_staff)


def _canonical(request, path):
    host = getattr(request, 'b2b_host', '') or request.get_host()
    return 'https://%s%s' % (host, path)


def _abs(request, url):
    return request.build_absolute_uri(url) if url else ''


def _jsonld(*items):
    out = []
    for data in items:
        text = json.dumps(data, ensure_ascii=False)
        # «</script>» داخلِ متن نباید تگ را ببندد
        text = text.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
        out.append('<script type="application/ld+json">%s</script>' % text)
    return mark_safe('\n'.join(out))


def _breadcrumb(request, items):
    return {'@context': 'https://schema.org', '@type': 'BreadcrumbList',
            'itemListElement': [dict({'@type': 'ListItem', 'position': i, 'name': name},
                                     **({'item': _canonical(request, url)} if url else {}))
                                for i, (name, url) in enumerate(items, 1)]}


def _published_credits():
    return Prefetch('credits', queryset=ProjectMember.objects.filter(member__is_published=True)
                    .select_related('member'))


def _project_qs():
    return (PortfolioProject.objects.filter(is_published=True)
            .select_related('category').prefetch_related(_published_credits()))


def _member_qs(request):
    qs = TeamMember.objects.prefetch_related(*[
        Prefetch('%s_set' % M._meta.model_name, queryset=M.objects.filter(is_published=True))
        for M in SECTION_MODELS])
    return qs if _can_preview(request) else qs.filter(is_published=True)


def _socials(member):
    links, seen = [], set()
    if member.linkedin:
        links.append({'url': member.linkedin, 'icon': 'linkedin', 'title': 'لینکدین',
                      'short': _short(member.linkedin)})
        seen.add(member.linkedin.rstrip('/').lower())
    for s in member.sociallink_set.all():
        key = s.url.rstrip('/').lower()
        if key and key not in seen:
            seen.add(key)
            links.append({'url': s.url, 'icon': s.icon, 'title': s.title, 'short': _short(s.url)})
    return links


def _short(url):
    """«https://www.linkedin.com/in/x/?utm=…» ⇒ «linkedin.com/in/x» برای چاپ و PDF."""
    url = re.sub(r'^(https?://)?(www\.)?', '', url or '', flags=re.I)
    return url.split('?')[0].split('#')[0].rstrip('/')


def _contact(member):
    rows = []
    if member.show_email and member.email:
        rows.append({'icon': 'envelope', 'label': 'ایمیل', 'value': member.email,
                     'href': 'mailto:' + member.email, 'ltr': True})
    if member.show_phone and member.phone:
        digits = ''.join(ch for ch in member.phone if ch.isdigit() or ch == '+')
        rows.append({'icon': 'telephone', 'label': 'تلفن', 'value': member.phone,
                     'href': 'tel:' + digits, 'ltr': True})
    if member.show_city and member.city:
        rows.append({'icon': 'geo-alt', 'label': 'شهر', 'value': member.city, 'href': '', 'ltr': False})
    return rows


def _skill_groups(member):
    groups = OrderedDict()
    for s in member.skill_set.all():
        groups.setdefault((s.group or '').strip(), []).append(s)
    if '' in groups and len(groups) > 1:        # بی‌دسته‌ها آخر
        groups.move_to_end('')
    return list(groups.items())


def _credits_of(member):
    return list(ProjectMember.objects.filter(member=member, project__is_published=True)
                .select_related('project', 'project__category')
                .order_by('-project__is_featured', 'project__order', '-project__year',
                          '-project__month', '-project__id'))


def _resume_context(request, member):
    credits = _credits_of(member)
    featured = [c for c in credits if c.project.is_featured][:6] or credits[:3]
    ctx = {
        'member': member,
        'socials': _socials(member),
        'contact': _contact(member),
        'experiences': list(member.experience_set.all()),
        'educations': list(member.education_set.all()),
        'certifications': list(member.certification_set.all()),
        'skill_groups': _skill_groups(member),
        'languages': list(member.languageskill_set.all()),
        'awards': list(member.award_set.all()),
        'featured': featured,
        'project_count': len(credits),
    }
    ctx['has_main'] = bool(member.summary or ctx['experiences'] or ctx['educations']
                           or ctx['certifications'] or featured)
    ctx['has_side'] = bool(ctx['skill_groups'] or ctx['languages'] or ctx['awards'])
    return ctx


def _person_ld(request, member, ctx, url):
    data = {'@context': 'https://schema.org', '@type': 'Person', 'name': member.name,
            'jobTitle': member.display_headline, 'url': url, 'memberOf': ORG}
    desc = (member.bio or member.summary or '').strip()
    if desc:
        data['description'] = desc[:300]
    if member.photo:
        data['image'] = _abs(request, thumbnail(member.photo, 600, 600, True))
    if member.show_email and member.email:
        data['email'] = member.email
    if member.show_phone and member.phone:
        data['telephone'] = member.phone
    if member.show_city and member.city:
        data['address'] = {'@type': 'PostalAddress', 'addressLocality': member.city, 'addressCountry': 'IR'}
    if ctx['socials']:
        data['sameAs'] = [s['url'] for s in ctx['socials']]
    current = [e.organisation for e in ctx['experiences'] if e.is_current]
    if current:
        data['worksFor'] = [{'@type': 'Organization', 'name': n} for n in current]
    if ctx['educations']:
        data['alumniOf'] = [{'@type': 'EducationalOrganization', 'name': e.institution}
                            for e in ctx['educations']]
    skills = [s.name for _, group in ctx['skill_groups'] for s in group]
    if skills:
        data['knowsAbout'] = skills
    if ctx['languages']:
        data['knowsLanguage'] = [lang.language for lang in ctx['languages']]
    if ctx['awards']:
        data['award'] = [a.title for a in ctx['awards']]
    if ctx['certifications']:
        data['hasCredential'] = [dict({'@type': 'EducationalOccupationalCredential', 'name': c.title},
                                      **({'recognizedBy': {'@type': 'Organization', 'name': c.issuer}}
                                         if c.issuer else {}))
                                 for c in ctx['certifications']]
    return data


# ─────────────────────────── صفحه‌ها ───────────────────────────
def team_list(request):
    members = list(TeamMember.objects.filter(is_published=True).annotate(
        project_count=Count('project_credits', filter=Q(project_credits__project__is_published=True),
                            distinct=True)))
    url = _canonical(request, reverse('team-list'))
    ld = {'@context': 'https://schema.org', '@type': 'ItemList', 'name': 'تیمِ چغر',
          'itemListElement': [{'@type': 'ListItem', 'position': i,
                               'url': _canonical(request, m.get_absolute_url()), 'name': m.name}
                              for i, m in enumerate(members, 1)]}
    has_projects = PortfolioProject.objects.filter(is_published=True).exists()
    return render(request, 'portfolio/team_list.html', {
        'members': members, 'canonical': url, 'has_projects': has_projects,
        'jsonld': _jsonld(ld, _breadcrumb(request, [('خانه', '/'), ('تیم', None)])),
    })


def member_detail(request, slug):
    member = get_object_or_404(_member_qs(request), slug=slug)
    ctx = _resume_context(request, member)
    url = _canonical(request, member.get_absolute_url())
    ctx.update({
        'canonical': url,
        'is_preview': not member.is_published,
        'meta_desc': Truncator((member.bio or member.summary or '').strip() or
                               'رزومهٔ %s، %s — تیمِ چغر' % (member.name, member.display_headline)
                               ).chars(155),
        'print_now': request.GET.get('print') == '1',
        'og_image': _abs(request, thumbnail(member.photo, 1200, 1200, True)) if member.photo else '',
        'jsonld': _jsonld(_person_ld(request, member, ctx, url),
                          _breadcrumb(request, [('خانه', '/'), ('تیم', reverse('team-list')),
                                                (member.name, None)])),
    })
    return render(request, 'portfolio/member_detail.html', ctx)


def _data_uri(path):
    if not path:
        return ''
    try:
        with open(path, 'rb') as fh:
            raw = fh.read()
    except OSError:
        return ''
    mime = 'image/webp' if path.endswith('.webp') else 'image/jpeg'
    return 'data:%s;base64,%s' % (mime, base64.b64encode(raw).decode('ascii'))


def _render_pdf(member, html):
    """PDF با WeasyPrint؛ نتیجه با هشِ همان HTML روی دیسک نگه داشته می‌شود.

    نگه‌داشت در دیسک (نه کشِ جنگو) چون کشِ این پروژه جدولی در همان SQLite ِ
    زنده است و یک PDF ِ چندصدکیلوبایتی جایش آن‌جا نیست.
    """
    key = hashlib.sha1(html.encode('utf-8')).hexdigest()[:16]
    cache_dir = os.path.join(settings.PRIVATE_MEDIA_ROOT, 'resume_pdf')
    path = os.path.join(cache_dir, '%d-%s.pdf' % (member.pk, key))
    if os.path.exists(path):
        with open(path, 'rb') as fh:
            return fh.read()
    try:
        from weasyprint import HTML
    except (ImportError, OSError):
        return None
    try:
        # همهٔ تصویرها data: اند ⇒ هیچ نشانیِ بیرونی fetch نمی‌شود
        pdf = HTML(string=html, base_url=settings.MEDIA_ROOT).write_pdf()
    except Exception:
        logger.exception('resume pdf failed for member %s', member.pk)
        return None
    try:
        os.makedirs(cache_dir, exist_ok=True)
        for old in glob.glob(os.path.join(cache_dir, '%d-*.pdf' % member.pk)):
            os.remove(old)
        tmp = '%s.%d.tmp' % (path, os.getpid())
        with open(tmp, 'wb') as fh:
            fh.write(pdf)
        os.replace(tmp, path)
    except OSError:
        logger.warning('could not cache resume pdf for member %s', member.pk)
    return pdf


def member_pdf(request, slug):
    member = get_object_or_404(_member_qs(request), slug=slug)
    if member.cv_file:
        return redirect(member.cv_file.url)
    ctx = _resume_context(request, member)
    ctx['photo_data'] = _data_uri(thumbnail(member.photo, 360, 360, True, as_path=True))
    ctx['page_url'] = _canonical(request, member.get_absolute_url())
    html = render_to_string('portfolio/member_pdf.html', ctx)
    pdf = _render_pdf(member, html)
    if pdf is None:     # موتورِ PDF در دسترس نیست ⇒ همان صفحه با پنجرهٔ چاپ
        return redirect(member.get_absolute_url() + '?print=1')
    name = 'resume-%s.pdf' % member.slug
    ascii_name = name if name.isascii() else 'resume-%d.pdf' % member.pk
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (
        ascii_name, quote(name))
    return resp


def _categories_for(qs_filter):
    return list(PortfolioCategory.objects.filter(**qs_filter)
                .annotate(n=Count('projects', distinct=True)).filter(n__gt=0).order_by('order', 'name'))


def portfolio_list(request, slug=None):
    member = None
    projects = _project_qs()
    cat_filter = {'projects__is_published': True}
    if slug:
        member = get_object_or_404(TeamMember.objects.all() if _can_preview(request)
                                   else TeamMember.objects.filter(is_published=True), slug=slug)
        projects = projects.filter(credits__member=member)
        cat_filter['projects__credits__member'] = member
    categories = _categories_for(cat_filter)
    active = (request.GET.get('category') or '').strip()
    active_cat = next((c for c in categories if c.slug == active), None)
    if active:
        projects = projects.filter(category__slug=active)
    projects = list(projects)
    if member:
        for p in projects:
            p.member_role = next((c.role for c in p.credits.all() if c.member_id == member.pk), '')
        path = reverse('team-portfolio', kwargs={'slug': member.slug})
        crumbs = [('خانه', '/'), ('تیم', reverse('team-list')),
                  (member.name, member.get_absolute_url()), ('نمونه‌کارها', None)]
    else:
        path = reverse('portfolio-list')
        crumbs = [('خانه', '/'), ('نمونه‌کارها', None)]
    url = _canonical(request, path + ('?category=%s' % quote(active) if active_cat else ''))
    ld = {'@context': 'https://schema.org', '@type': 'ItemList',
          'itemListElement': [{'@type': 'ListItem', 'position': i, 'name': p.title,
                               'url': _canonical(request, p.get_absolute_url())}
                              for i, p in enumerate(projects, 1)]}
    return render(request, 'portfolio/portfolio_list.html', {
        'member': member, 'projects': projects, 'categories': categories, 'active': active,
        'active_cat': active_cat, 'canonical': url, 'base_path': path,
        'jsonld': _jsonld(ld, _breadcrumb(request, crumbs)),
    })


def project_detail(request, slug):
    qs = (PortfolioProject.objects.select_related('category')
          .prefetch_related('images', _published_credits()))
    if not _can_preview(request):
        qs = qs.filter(is_published=True)
    project = get_object_or_404(qs, slug=slug)
    related = _project_qs().exclude(pk=project.pk)
    if project.category_id:
        related = related.filter(category_id=project.category_id)
    related = list(related[:3])
    gallery = [{'thumb': thumbnail(img.image, 640, 480, True), 'large': thumbnail(img.image, 1600),
                'caption': img.caption} for img in project.images.all()]
    url = _canonical(request, project.get_absolute_url())
    image = _abs(request, thumbnail(project.cover, 1200)) if project.cover else ''
    data = {'@context': 'https://schema.org', '@type': 'CreativeWork', 'name': project.title,
            'url': url, 'inLanguage': 'fa-IR', 'publisher': ORG}
    if project.short_description or project.description:
        data['description'] = (project.short_description or project.description)[:300]
    if image:
        data['image'] = image
    if project.year:
        data['dateCreated'] = iso_ym(project.year, project.month)
    if project.category:
        data['genre'] = project.category.name
    if project.tag_list:
        data['keywords'] = '، '.join(project.tag_list)
    credits = list(project.credits.all())
    if credits:
        data['creator'] = [{'@type': 'Person', 'name': c.member.name,
                            'url': _canonical(request, c.member.get_absolute_url())} for c in credits]
    if project.external_url:
        data['sameAs'] = project.external_url
    return render(request, 'portfolio/project_detail.html', {
        'meta_desc': Truncator((project.short_description or project.description or project.title).strip()
                               ).chars(155),
        'project': project, 'credits': credits, 'gallery': gallery, 'related': related,
        'canonical': url, 'og_image': image, 'is_preview': not project.is_published,
        'jsonld': _jsonld(data, _breadcrumb(request, [('خانه', '/'), ('نمونه‌کارها', reverse('portfolio-list')),
                                                      (project.title, None)])),
    })
