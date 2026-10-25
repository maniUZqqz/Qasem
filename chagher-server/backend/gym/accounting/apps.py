# -*- coding: utf-8 -*-
from django.apps import AppConfig
from django.db.models.signals import post_migrate

GROUP_NAME = 'حسابداری'


def ensure_group(sender, using='default', **kwargs):
    """گروهِ «حسابداری» با همهٔ مجوزهای این اپ + تریگرهای قفلِ سند (هر migrate دوباره هم‌گام می‌شود)."""
    from django.contrib.auth.models import Group, Permission
    from django.db import connections
    from .db import ensure_triggers
    ensure_triggers(connections[using])
    group, _ = Group.objects.using(using).get_or_create(name=GROUP_NAME)
    perms = Permission.objects.using(using).filter(content_type__app_label='accounting')
    group.permissions.add(*perms)


class AccountingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounting'
    verbose_name = '📒 حسابداری'

    def ready(self):
        post_migrate.connect(ensure_group, sender=self, dispatch_uid='accounting_ensure_group')
