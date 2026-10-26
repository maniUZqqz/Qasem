# -*- coding: utf-8 -*-
"""ادمینِ رزومه و نمونه‌کار.

«اعضای تیم و رزومه» همان TeamMember است با همهٔ بخش‌های رزومه به‌صورتِ ردیف‌های
زیرِ همان صفحه (inline)؛ «نمونه‌کارها» جدا با گالری و اعضای پروژه.
"""
from django import forms
from django.contrib import admin
from django.db import models
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from app.models import TeamMember

from .models import (Award, Certification, Education, Experience, LanguageSkill, PortfolioCategory,
                     PortfolioProject, ProjectImage, ProjectMember, Skill, SocialLink)
from .thumbs import thumbnail

GUIDE_BOX = ('<div style="background:#EDF3FF;border:1px solid #C9D8F2;border-radius:8px;'
             'padding:10px 14px;line-height:2;max-width:760px">{}</div>')

MEMBER_GUIDE = (
    '<b>رزومهٔ هر عضو همین‌جا پر می‌شود.</b> بالای صفحه مشخصات، عکس، معرفی و راه‌های تماس است '
    '(کنارِ هر کدام تیکِ «دیده شود»)؛ پایینِ صفحه بخش‌های رزومه: شبکه‌های اجتماعی، سوابقِ کاری، '
    'تحصیلات، مدارک، مهارت‌ها، زبان‌ها، افتخارات و پروژه‌های این عضو — با «افزودن» ردیف اضافه کنید. '
    'هر ردیف تیکِ «منتشر شود» دارد؛ بخشِ بی‌ردیف در سایت اصلاً نمی‌آید. '
    'تاریخ‌ها شمسی‌اند (مثلاً 1402). نمونه‌کارها (پروژه‌ها با عکس و ویدئو) در '
    '«سایت و محتوا ← نمونه‌کارها (پروژه‌ها)» ساخته می‌شوند. '
    'دکمهٔ «مشاهده در سایت» بالای صفحه، رزومه را نشان می‌دهد.')

PROJECT_GUIDE = (
    '<b>هر نمونه‌کار:</b> عنوان، دسته، کاور، خلاصه و شرح، کارفرما و سال (شمسی)، برچسب‌ها، لینک و ویدئو '
    '(لینکِ آپارات/یوتیوب داخلِ صفحه پخش می‌شود). پایینِ صفحه «اعضای پروژه» (هر عضو با نقشش) و '
    '«گالریِ تصاویر» را اضافه کنید. تیکِ «ویژه» پروژه را اولِ فهرست و در رزومهٔ اعضا می‌آورد؛ '
    '«منتشر شود» خاموش ⇒ در سایت دیده نمی‌شود.')


def _img(url, size=48, round_=False):
    if not url:
        return '—'
    return format_html('<img src="{}" style="width:{}px;height:{}px;object-fit:cover;border-radius:{}"'
                       ' alt="">', url, size, size, '50%' if round_ else '6px')


def _site_link(url, published=True):
    label = 'مشاهده در سایت' if published else 'پیش‌نمایش (منتشر نشده)'
    return format_html('<a href="{}" target="_blank" rel="noopener">{} ↗</a>', url, label)


SMALL_TEXT = {models.TextField: {'widget': forms.Textarea(attrs={'rows': 3, 'cols': 60})}}


class _Inline:
    extra = 0
    formfield_overrides = SMALL_TEXT


class SocialLinkInline(_Inline, admin.TabularInline):
    model = SocialLink
    fields = ['kind', 'url', 'label', 'order', 'is_published']


class ExperienceInline(_Inline, admin.StackedInline):
    model = Experience
    fields = [('role', 'organisation'), ('city', 'employment_type'),
              ('start_year', 'start_month', 'end_year', 'end_month', 'is_current'),
              'description', ('order', 'is_published')]


class EducationInline(_Inline, admin.StackedInline):
    model = Education
    fields = [('degree', 'field', 'institution'), ('city', 'start_year', 'end_year', 'is_current'),
              'description', ('order', 'is_published')]


class CertificationInline(_Inline, admin.StackedInline):
    model = Certification
    fields = [('title', 'issuer'), ('year', 'month', 'credential_id'), ('url', 'file'), ('order', 'is_published')]


class SkillInline(_Inline, admin.TabularInline):
    model = Skill
    fields = ['name', 'group', 'level', 'order', 'is_published']


class LanguageInline(_Inline, admin.TabularInline):
    model = LanguageSkill
    fields = ['language', 'level', 'order', 'is_published']


class AwardInline(_Inline, admin.StackedInline):
    model = Award
    fields = [('title', 'issuer', 'year'), 'description', 'url', ('order', 'is_published')]


class MemberProjectInline(_Inline, admin.TabularInline):
    model = ProjectMember
    fk_name = 'member'
    fields = ['project', 'role', 'order']
    autocomplete_fields = ['project']
    verbose_name = 'پروژهٔ این عضو'
    verbose_name_plural = 'پروژه‌های این عضو (نمونه‌کار)'


if admin.site.is_registered(TeamMember):      # ثبتِ قدیمیِ app/admin.py جایش را به این می‌دهد
    admin.site.unregister(TeamMember)


@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    list_display = ['photo_thumb', 'name', 'role', 'is_published', 'order', 'resume_status', 'site_link']
    list_display_links = ['photo_thumb', 'name']
    list_editable = ['is_published', 'order']
    list_filter = ['is_published']
    search_fields = ['name', 'role', 'headline']
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ['guide', 'photo_preview', 'site_link_big']
    save_on_top = True
    formfield_overrides = {models.TextField: {'widget': forms.Textarea(attrs={'rows': 4, 'cols': 80})}}
    fieldsets = [
        ('راهنما', {'fields': ['guide']}),
        ('مشخصات و انتشار', {'fields': ['name', 'role', 'headline', 'slug', ('is_published', 'order'),
                                         'site_link_big']}),
        ('عکس', {'fields': ['photo', 'photo_preview', 'icon']}),
        ('معرفی', {'fields': ['bio', 'summary']}),
        ('راه‌های تماس', {
            'fields': [('email', 'show_email'), ('phone', 'show_phone'), ('city', 'show_city'), 'linkedin'],
            'description': 'هر کدام فقط وقتی در سایت و PDF می‌آید که تیکِ «دیده شود» کنارش روشن باشد. '
                           'لینکدین روی کارتِ «درباره ما» هم هست؛ بقیهٔ شبکه‌ها را پایینِ صفحه اضافه کنید.'}),
        ('فایلِ رزومهٔ آماده (اختیاری)', {'fields': ['cv_file']}),
    ]
    inlines = [SocialLinkInline, ExperienceInline, EducationInline, CertificationInline,
               SkillInline, LanguageInline, AwardInline, MemberProjectInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            n_exp=models.Count('experience_set', distinct=True),
            n_skill=models.Count('skill_set', distinct=True),
            n_proj=models.Count('project_credits', distinct=True))

    @admin.display(description='راهنما')
    def guide(self, obj):
        return format_html(GUIDE_BOX, mark_safe(MEMBER_GUIDE))

    @admin.display(description='')
    def photo_thumb(self, obj):
        return _img(thumbnail(obj.photo, 96, 96, True), 40, True)

    @admin.display(description='پیش‌نمایشِ عکس')
    def photo_preview(self, obj):
        return _img(thumbnail(obj.photo, 240, 240, True), 120, True) if obj and obj.photo else '—'

    @admin.display(description='رزومه')
    def resume_status(self, obj):
        return format_html('{} سابقه · {} مهارت · {} پروژه', obj.n_exp, obj.n_skill, obj.n_proj)

    @admin.display(description='سایت')
    def site_link(self, obj):
        return _site_link(obj.get_absolute_url(), obj.is_published) if obj.slug else '—'

    @admin.display(description='صفحهٔ رزومه')
    def site_link_big(self, obj):
        if not obj or not obj.pk or not obj.slug:
            return 'بعد از ذخیره، نشانیِ صفحه این‌جا می‌آید.'
        return format_html('{} &nbsp; | &nbsp; <a href="{}" target="_blank">PDF</a> &nbsp; | &nbsp; '
                           '<a href="{}" target="_blank">نمونه‌کارها</a>',
                           _site_link(obj.get_absolute_url(), obj.is_published),
                           obj.get_absolute_url() + 'pdf/', obj.get_absolute_url() + 'portfolio/')


class ProjectMemberInline(_Inline, admin.TabularInline):
    model = ProjectMember
    fk_name = 'project'
    fields = ['member', 'role', 'order']
    autocomplete_fields = ['member']


class ProjectImageInline(_Inline, admin.TabularInline):
    model = ProjectImage
    fields = ['preview', 'image', 'caption', 'order']
    readonly_fields = ['preview']

    @admin.display(description='')
    def preview(self, obj):
        return _img(thumbnail(obj.image, 160, 120, True), 64) if obj and obj.image else ''


@admin.register(PortfolioProject)
class PortfolioProjectAdmin(admin.ModelAdmin):
    list_display = ['cover_thumb', 'title', 'category', 'members_list', 'year', 'is_featured',
                    'is_published', 'order', 'site_link']
    list_display_links = ['cover_thumb', 'title']
    list_editable = ['is_featured', 'is_published', 'order']
    list_filter = ['is_published', 'is_featured', 'category']
    search_fields = ['title', 'short_description', 'client', 'tags']
    list_select_related = ['category']
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = ['guide', 'cover_preview']
    save_on_top = True
    formfield_overrides = {models.TextField: {'widget': forms.Textarea(attrs={'rows': 8, 'cols': 80})}}
    fieldsets = [
        ('راهنما', {'fields': ['guide']}),
        ('اصلی', {'fields': ['title', 'slug', 'category', ('is_published', 'is_featured', 'order')]}),
        ('معرفی', {'fields': ['short_description', 'description', 'client', ('year', 'month'), 'tags',
                              'external_url']}),
        ('تصویر و ویدئو', {'fields': ['cover', 'cover_preview', 'video_url', 'video_file']}),
    ]
    inlines = [ProjectMemberInline, ProjectImageInline]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('credits__member')

    @admin.display(description='راهنما')
    def guide(self, obj):
        return format_html(GUIDE_BOX, mark_safe(PROJECT_GUIDE))

    @admin.display(description='')
    def cover_thumb(self, obj):
        return _img(thumbnail(obj.cover, 120, 90, True), 56)

    @admin.display(description='پیش‌نمایشِ کاور')
    def cover_preview(self, obj):
        return _img(thumbnail(obj.cover, 480, 300, True), 240) if obj and obj.cover else '—'

    @admin.display(description='اعضا')
    def members_list(self, obj):
        return format_html_join('، ', '{}', ((c.member.name,) for c in obj.credits.all())) or '—'

    @admin.display(description='سایت')
    def site_link(self, obj):
        return _site_link(obj.get_absolute_url(), obj.is_published)


@admin.register(PortfolioCategory)
class PortfolioCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'order', 'project_count']
    list_editable = ['order']
    search_fields = ['name']
    prepopulated_fields = {'slug': ('name',)}

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n=models.Count('projects'))

    @admin.display(description='تعدادِ پروژه', ordering='n')
    def project_count(self, obj):
        return obj.n
