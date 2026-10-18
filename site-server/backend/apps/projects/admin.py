# -*- coding: utf-8 -*-
from django.contrib import admin

from .models import App, BuildLog, Field, Model, Page, Project, Route, SharedPart, View


class AppInline(admin.TabularInline):
    model = App
    extra = 0
    fields = ['name', 'verbose_name_fa', 'url_prefix', 'managed', 'is_core']


class FieldInline(admin.TabularInline):
    model = Field
    fk_name = 'model'
    extra = 0
    fields = ['name', 'verbose_name_fa', 'field_type', 'max_length', 'null', 'blank', 'related_model', 'order']


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    name_en = 'Studio projects'
    description = 'هر پروژهٔ سایت‌ساز یک سایتِ جنگوی واقعی است (کارگاهِ جدا، venv، گیت). از پنل ⇐ ابزارها ⇐ سایت‌ساز ساخته و ویرایش می‌شود.'
    list_display = ['name', 'slug', 'source', 'status', 'updated_at']
    list_filter = ['status', 'source']
    search_fields = ['name', 'slug']
    inlines = [AppInline]


@admin.register(App)
class AppAdmin(admin.ModelAdmin):
    name_en = 'Studio apps'
    description = 'اپ‌های جنگوی داخلِ هر پروژهٔ سایت‌ساز (مدیریت‌شده یا واردشده).'
    list_display = ['name', 'project', 'url_prefix', 'managed', 'is_core']
    list_filter = ['project', 'managed', 'is_core']


@admin.register(Model)
class ModelAdmin_(admin.ModelAdmin):
    name_en = 'Studio models'
    description = 'مدل‌های دادهٔ هر اپ؛ از روی این‌ها models.py و ادمینِ سایتِ تولیدشده ساخته می‌شود.'
    list_display = ['name', 'app', 'managed', 'in_admin']
    list_filter = ['app__project', 'managed']
    inlines = [FieldInline]


@admin.register(Field)
class FieldAdmin(admin.ModelAdmin):
    name_en = 'Studio fields'
    description = 'فیلدهای هر مدل (نوع، طول، اجباری/اختیاری، رابطه).'
    list_display = ['name', 'model', 'field_type']
    list_filter = ['field_type']
    search_fields = ['name']


@admin.register(View)
class ViewAdmin(admin.ModelAdmin):
    name_en = 'Studio views'
    description = 'ویوهای هر اپ (فهرست، جزئیات، فرم، سفارشی) و کدِ تولیدشده‌شان.'
    list_display = ['name', 'app', 'kind', 'model', 'managed']
    list_filter = ['kind', 'app__project', 'managed']


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    name_en = 'Studio routes'
    description = 'نشانی‌های (URL) هر پروژه و ویویی که به آن وصل است.'
    list_display = ['__str__', 'name', 'project', 'app', 'view', 'managed']
    list_filter = ['project', 'managed']


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    name_en = 'Studio pages'
    description = 'صفحه‌های فرانتِ هر پروژه (قالب‌های HTML) که از پنل یا با هوشِ مصنوعی ویرایش می‌شوند.'
    list_display = ['title', 'project', 'slug', 'kind']
    list_filter = ['project', 'kind']


@admin.register(SharedPart)
class SharedPartAdmin(admin.ModelAdmin):
    name_en = 'Studio shared parts'
    description = 'سربرگ، پابرگ و CSS ِ مشترکِ همهٔ صفحه‌های یک پروژه.'
    list_display = ['project', 'kind']


@admin.register(BuildLog)
class BuildLogAdmin(admin.ModelAdmin):
    name_en = 'Studio build logs'
    description = 'هر بار «تولیدِ کد»: چند فایل نوشته شد، موفق بود یا نه، و خلاصهٔ خطاها.'
    list_display = ['project', 'ok', 'summary', 'files_written', 'created_at']
    list_filter = ['ok']
