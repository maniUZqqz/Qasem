# -*- coding: utf-8 -*-
"""جدول‌های استودیو همیشه از دیتابیسِ خودِ استودیو خوانده/نوشته شوند.

⚠ بدونِ این، استودیوی داخلِ پروژهٔ اصلی با db.sqlite3ِ پروژهٔ اصلی کار می‌کرد
   و پروژه‌هایی که در استودیوی مستقل (پورت ۸۰۲۰) ساخته شده بودند را نمی‌دید —
   دو فهرستِ جدا با یک پوشهٔ مشترک. حالا هر دو یک منبعِ حقیقت دارند.
"""
STUDIO_APPS = {'projects', 'code_generation', 'template_editor', 'ai_engine', 'project_importer'}


class StudioRouter:
    def db_for_read(self, model, **hints):
        return 'studio' if model._meta.app_label in STUDIO_APPS else None

    def db_for_write(self, model, **hints):
        return 'studio' if model._meta.app_label in STUDIO_APPS else None

    def allow_relation(self, a, b, **hints):
        sa = a._meta.app_label in STUDIO_APPS
        sb = b._meta.app_label in STUDIO_APPS
        return True if sa == sb else None

    def allow_migrate(self, db, app_label, **hints):
        if app_label in STUDIO_APPS:
            return db == 'studio'
        return db == 'default'
