# -*- coding: utf-8 -*-
"""تعیین نوع حساب برای کاربران موجود.

تا پیش از این نقش کاربر ضمنی بود (از روی وجود client_profile یا gym_brand).
این مایگریشن همان استنتاج را یک‌بار انجام می‌دهد و در فیلد صریح ذخیره می‌کند.
"""
from django.db import migrations


def set_account_types(apps, schema_editor):
    CustomUser = apps.get_model('app', 'CustomUser')
    GymClient = apps.get_model('app', 'GymClient')

    # ورزشکارانی که از طریق کد دسترسی باشگاه ساخته شده‌اند
    client_user_ids = GymClient.objects.filter(
        client_user__isnull=False
    ).values_list('client_user_id', flat=True)

    CustomUser.objects.filter(id__in=list(client_user_ids)).update(account_type='gym_client')

    # بقیه (به‌جز ورزشکاران) مربی/باشگاه‌دار هستند — همان پیش‌فرض فیلد
    CustomUser.objects.exclude(id__in=list(client_user_ids)).update(account_type='coach')


def reverse(apps, schema_editor):
    # فیلد در مایگریشن قبلی حذف می‌شود؛ کاری لازم نیست
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0010_clientprogram_training_place_customuser_account_type_and_more'),
    ]

    operations = [
        migrations.RunPython(set_account_types, reverse),
    ]
