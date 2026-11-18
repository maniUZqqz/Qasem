"""Proxy / VPN settings: the proxies and the per-service routing table (see ``services.egress``).

Secrets are stored the way the project stores its other secrets (a bot token, an API key): a plain column that the API never returns
- only ``has_password``. Nothing here is ever logged with the password in it.
"""
from __future__ import annotations

from django.db import models


class EgressProxy(models.Model):
    class Scheme(models.TextChoices):
        HTTP = "http", "http"
        HTTPS = "https", "https"
        SOCKS5 = "socks5", "socks5"
        SOCKS5H = "socks5h", "socks5h (نامِ سایت را خودِ پراکسی پیدا می‌کند)"

    name = models.CharField("نام", max_length=80, unique=True)
    scheme = models.CharField("نوع", max_length=10, choices=Scheme.choices, default=Scheme.HTTP)
    host = models.CharField("نشانی", max_length=255)
    port = models.PositiveIntegerField("پورت")
    username = models.CharField("نامِ کاربری", max_length=200, blank=True)
    #: SECRET. Never returned by the API (only ``has_password``), never logged.
    password = models.CharField("رمز", max_length=300, blank=True)
    enabled = models.BooleanField("روشن", default=True)
    note = models.CharField("یادداشت", max_length=200, blank=True)
    #: the last «test» of this proxy: {ok, ip, country, latency_ms, targets: [...], checked_at} - holds no secret
    last_test = models.JSONField(default=dict, blank=True)
    last_test_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "پراکسی"
        verbose_name_plural = "پراکسی‌ها"

    def __str__(self) -> str:  # the admin / shell never shows the password
        return f"{self.name} ({self.scheme}://{self.host}:{self.port})"

    @property
    def is_local(self) -> bool:
        """Does it point at THIS server (127.0.0.1, localhost, a private address)? Such a proxy means nothing to another machine."""
        from services.egress import util

        return util.is_local_host(self.host)


class EgressSwitch(models.Model):
    """The master switch (one row, pk=1): off = EVERY service goes direct, whatever the table says. The table is kept, so switching it on
    again brings the routes back - the one button to press when a VPN misbehaves."""

    enabled = models.BooleanField("پراکسی کلاً روشن", default=True)
    updated_by = models.CharField(max_length=150, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "کلیدِ کلیِ پراکسی"
        verbose_name_plural = "کلیدِ کلیِ پراکسی"

    def __str__(self) -> str:
        return "روشن" if self.enabled else "خاموش (همه مستقیم)"

    @classmethod
    def get(cls) -> "EgressSwitch":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class EgressRoute(models.Model):
    """One row per catalogue service: through which proxy does it leave? No proxy = direct (the default)."""

    service = models.CharField("سرویس", max_length=40, unique=True)
    proxy = models.ForeignKey(EgressProxy, null=True, blank=True, on_delete=models.SET_NULL, related_name="routes", verbose_name="پراکسی")
    #: the last health check of the service through the route it uses: {state, detail, checked_at, via, proxy, latency_ms, targets}
    health = models.JSONField(default=dict, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.CharField(max_length=150, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("service",)
        verbose_name = "مسیرِ سرویس"
        verbose_name_plural = "مسیرِ سرویس‌ها"

    def __str__(self) -> str:
        return f"{self.service} → {self.proxy.name if self.proxy_id else 'مستقیم'}"
