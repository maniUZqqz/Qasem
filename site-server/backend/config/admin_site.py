# -*- coding: utf-8 -*-
"""پنل ادمین NMarketing — نام‌ها، توضیح‌ها، و چیدمان فهرست اصلی.

چرا این فایل هست
================

ادمینِ پیش‌فرض جنگو فهرستی از نام مدل‌ها نشان می‌دهد و بس. برای کسی که
هر روز با آن کار می‌کند کافی است، ولی این ادمین دستِ کسی می‌افتد که
نمی‌داند «کار انتشار» با «کمپین» چه فرقی دارد یا «مصرف سهمیه» را چه
چیزی پر می‌کند — و نامِ تنها، جواب هیچ‌کدام را نمی‌دهد.

پس هر جدول دو چیز اضافه می‌گیرد که در `admin.py` خودش تعریف می‌شوند:

    name_en     — نام انگلیسی، چون نام جدول‌ها و مستندات فنی انگلیسی‌اند
                  و کسی که دنبال «Orders» می‌گردد باید پیدایش کند.
    description — یک جمله: این چیست و چه کاری می‌کند.

`get_app_list` آن‌ها را به همان دیکشنری‌ای می‌چسباند که قالب‌های ادمین
می‌خوانند، پس هم فهرست اصلی و هم بالای خود جدول می‌توانند نشانشان دهند
بدون اینکه هیچ ModelAdmin ای لازم باشد کار خاصی بکند.
"""
from django.contrib import admin
from django.contrib.admin.apps import AdminConfig


class UpMarketAdminSite(admin.AdminSite):
    site_header = "NMarketing — پنل مدیریت"
    site_title = "NMarketing"
    index_title = "همه‌ی جدول‌ها"

    def get_app_list(self, request, app_label=None):
        """فهرست اپ‌ها، به‌علاوه‌ی نام انگلیسی و توضیح هر جدول."""
        app_list = super().get_app_list(request, app_label)
        for app in app_list:
            for entry in app["models"]:
                model_admin = self._registry.get(entry.get("model"))
                entry["name_en"] = getattr(model_admin, "name_en", "") if model_admin else ""
                entry["description"] = getattr(model_admin, "description", "") if model_admin else ""
        return app_list

    def each_context(self, request):
        """توضیح جدولِ باز‌شده را به قالب می‌رساند.

        قالب `change_list.html` به `cl.opts` دسترسی دارد ولی به خودِ
        ModelAdmin نه، و توضیح روی ModelAdmin نشسته است.

        آدرس‌های ادمین نامِ `admin:<app>_<model>_changelist` دارند، پس
        همان اسمِ مسیر کافی است تا بفهمیم کدام جدول باز است — بدون اینکه
        لازم باشد هیچ ModelAdmin ای چیزی به request بچسباند.
        """
        context = super().each_context(request)
        match = getattr(request, "resolver_match", None)
        url_name = getattr(match, "url_name", "") or ""
        # فقط صفحه‌ی فهرست. در فرم ویرایش، کاربر می‌داند کجاست و یادداشت
        # آنجا فقط فاصله‌ی بین او و فیلدها را زیاد می‌کند.
        if not url_name.endswith("_changelist"):
            return context
        for model, model_admin in self._registry.items():
            opts = model._meta
            if url_name == f"{opts.app_label}_{opts.model_name}_changelist":
                context["table_name_en"] = getattr(model_admin, "name_en", "")
                context["table_description"] = getattr(model_admin, "description", "")
                break
        return context


class UpMarketAdminConfig(AdminConfig):
    """جایگزینِ `django.contrib.admin` در INSTALLED_APPS.

    راه رسمیِ جنگو برای عوض کردن AdminSite پیش‌فرض بدون اینکه لازم باشد
    هر `@admin.register` جای دیگری ثبت شود.
    """

    default_site = "config.admin_site.UpMarketAdminSite"

    def ready(self):
        """واژه‌نامه‌ی فارسیِ فیلدها و گزینه‌ها را می‌نشاند.

        بعد از `super().ready()` اجرا می‌شود، چون تا آن لحظه همه‌ی
        `admin.py` ها خوانده شده‌اند و رجیستری کامل است.
        """
        super().ready()
        from . import admin_labels

        admin_labels.apply()
