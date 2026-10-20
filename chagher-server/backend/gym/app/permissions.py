# -*- coding: utf-8 -*-
"""مرزبندی دسترسی بین دنیای باشگاه (B2B) و کاربر شخصی (B2C).

قانون: هر کاربر دقیقاً یک نقش دارد (account_type) و فقط به مسیر خودش دسترسی دارد.
برنامه‌گرفتن و خرید توکن مشترک است؛ مدیریت باشگاه فقط برای مربی.
"""
from rest_framework.permissions import BasePermission

from .models import CustomUser


class IsCoach(BasePermission):
    """فقط مربی/باشگاه‌دار — مدیریت مشتریان، برند، تجهیزات و غذاهای باشگاه."""
    message = 'این بخش مخصوص حساب مربی/باشگاه است.'

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated
            and user.account_type == CustomUser.ACCOUNT_TYPE_COACH
        )


class IsGymClient(BasePermission):
    """فقط ورزشکار متصل به باشگاه — پروفایل مشتری و درخواست توکن از مربی."""
    message = 'این بخش مخصوص ورزشکاران متصل به باشگاه است.'

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated
            and user.account_type == CustomUser.ACCOUNT_TYPE_GYM_CLIENT
        )


class IsCoachOrPersonal(BasePermission):
    """مربی یا کاربرِ شخصی — برای چیزهایی که «مالِ خودِ کاربر» است.

    دستگاه‌ها از این دسته‌اند: مربی دستگاه‌های باشگاهش را ثبت می‌کند و ورزشکارِ
    شخصی (B2C) دستگاه‌های باشگاهی که می‌رود — که با اسکنِ دوربین پر می‌شود و
    باید بتواند اصلاحش کند. فیلترِ queryset همیشه روی خودِ کاربر است، پس کسی
    دستگاهِ دیگری را نمی‌بیند.
    """
    message = 'این بخش مخصوص حسابِ مربی یا کاربرِ شخصی است.'

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated
            and user.account_type in (CustomUser.ACCOUNT_TYPE_COACH,
                                      CustomUser.ACCOUNT_TYPE_PERSONAL)
        )
