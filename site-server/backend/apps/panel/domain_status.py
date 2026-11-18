"""وضعیتِ «دامنه و SSL» برای کارتِ ادمین (فقط خواندنی).

تنظیم‌کنندهٔ اصلی ابزارِ خطِ فرمانِ `deploy/nm/nm-domain.sh` است؛ آن در `data/domain/domain.json` می‌نویسد که چه چیزی را کی و چطور
تنظیم کرده. این‌جا همان فایل + حالِ زندهٔ گواهی (از خودِ nginx) + DNS خوانده می‌شود، تا کارت «فقط IP» یا «دامنه + تاریخِ انقضا» را نشان دهد.
هیچ دستورِ تغییردهنده‌ای از پنل اجرا نمی‌شود (نصبِ دامنه با root روی سرور انجام می‌شود).
"""
from __future__ import annotations

import json
import os
import socket
import ssl
import tempfile
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings

from . import domain_core as core

#: دستوری که کارت نشان می‌دهد؛ مسیرِ نصبِ اسکریپت روی سرورِ سایت
SCRIPT = "/root/nm-domain.sh"
DEFAULT_IP = "87.107.160.17"
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="nm-domain")


def state_path() -> Path:
    return Path(settings.NM_DATA_DIR) / "domain" / "domain.json"


def load_state() -> dict | None:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _within(fn, seconds: float, default=None):
    """fn() با سقفِ زمان؛ DNS/شبکهٔ کند نباید کلِ صفحه را بخواباند."""
    fut = _POOL.submit(fn)
    try:
        return fut.result(timeout=seconds)
    except (FutureTimeout, Exception):  # noqa: BLE001
        return default


def server_ip(state: dict | None = None) -> str:
    """IP این سرور: از وضعیتِ ابزار، NM_SERVER_IP، یا میزبانِ IP ِ PUBLIC_BASE_URL؛ وگرنه IPِ شناخته‌شدهٔ سایت."""
    if state and state.get("server_ip"):
        return str(state["server_ip"])
    if os.getenv("NM_SERVER_IP"):
        return os.environ["NM_SERVER_IP"]
    host = urlsplit(public_base_url()).hostname or ""
    if core._IPV4.match(host):  # noqa: SLF001
        return host
    return DEFAULT_IP


def public_base_url() -> str:
    return str((getattr(settings, "UPMARKET_PUBLISHING", {}) or {}).get("PUBLIC_BASE_URL", "")).rstrip("/")


def tls_probe(domain: str, port: int = 443) -> dict | None:
    """گواهیی که nginxِ همین سرور برای این نام می‌دهد (SNI)؛ None = TLS جواب نداد."""
    try:
        ctx = ssl._create_unverified_context()  # noqa: S323 - فقط خواندنِ گواهی، نه اعتماد
        with socket.create_connection(("127.0.0.1", port), timeout=3) as raw:
            with ctx.wrap_socket(raw, server_hostname=domain) as tls:
                der = tls.getpeercert(True)
        pem = ssl.DER_cert_to_PEM_cert(der)
        with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as fh:
            fh.write(pem)
        try:
            return core.cert_info(Path(fh.name))
        finally:
            os.unlink(fh.name)
    except (OSError, ssl.SSLError, ValueError, TypeError):
        return None


def _cert_file(state: dict) -> Path:
    d = Path(state.get("cert_dir", ""))
    return d / ("fullchain.pem" if state.get("ca") == "selfsigned" else "cert.pem")


def records_to_add(ip: str, www: bool = True) -> list[dict]:
    rows = [{"type": "A", "name": "@", "value": ip, "ttl": "3600"}]
    if www:
        rows.append({"type": "A", "name": "www", "value": ip, "ttl": "3600"})
    return rows


def check_dns(raw: str, www: bool = True) -> dict:
    """DNS یک دامنه را (فقط resolve) می‌سنجد. DomainError (فارسی) برای نامِ نادرست."""
    domain, aliases = core.normalize_domain(raw, www)
    ip = server_ip(load_state())
    names = [domain, *aliases]
    reports = [_within(lambda n=n: core.dns_report(n, ip), 40, None) or
               {"name": n, "status": "timeout", "a": {}, "aaaa": [], "found": [], "server_ip": ip,
                "message": f"بررسیِ DNS برای «{n}» به‌موقع تمام نشد؛ دوباره امتحان کنید."} for n in names]
    ok = all(r["status"] == "ok" for r in reports)
    return {
        "domain": domain, "names": names, "server_ip": ip, "ok": ok, "reports": reports,
        "records": records_to_add(ip, www=bool(aliases)),
        "command": f"{SCRIPT} {domain}" + (" --www" if aliases else ""),
        "dry_command": f"{SCRIPT} {domain}" + (" --www" if aliases else "") + " --dry-run",
    }


def status() -> dict:
    state = load_state()
    ip = server_ip(state)
    out: dict = {
        "configured": bool(state),
        "server_ip": ip,
        "public_base_url": public_base_url(),
        "ip_url": f"http://{ip}:8040",
        "script": SCRIPT,
        "warnings": [],
    }
    if not state:
        out.update(mode="ip_only", domain=None, cert=None)
        return out
    domain = state.get("domain", "")
    cert_from_file = core.cert_info(_cert_file(state)) if state.get("cert_dir") else None
    served = _within(lambda: tls_probe(domain), 8, None)
    dns = _within(lambda: core.dns_report(domain, ip), 40, None)
    cert = served or cert_from_file
    warnings: list[str] = []
    if served is None:
        warnings.append("nginx برای این دامنه پاسخِ TLS نداد (vhost یا nginx را بررسی کنید: nm-domain.sh --status).")
    if cert and cert.get("days_left", 99) <= 14:
        warnings.append(f"گواهی {cert['days_left']} روز دیگر منقضی می‌شود؛ تمدیدِ خودکار باید زودتر انجام می‌شد (journalctl -u certbot).")
    if cert and cert.get("staging"):
        warnings.append("گواهی آزمایشی است و مرورگرها نمی‌پذیرند؛ همان دستور را بدونِ --staging دوباره اجرا کنید.")
    if cert and cert.get("self_signed"):
        warnings.append("گواهیِ خودامضاست؛ فقط پشتِ CDN (حالتِ «بدونِ اعتبارسنجی») درست است.")
    if dns and dns["status"] != "ok":
        warnings.append("DNS دامنه دیگر به این سرور اشاره نمی‌کند: " + dns["message"])
    if state.get("canonical") and public_base_url() != state["canonical"]:
        warnings.append(f"نشانیِ عمومیِ فعلیِ NM ({public_base_url() or '—'}) با دامنه ({state['canonical']}) یکی نیست؛ PUBLIC_BASE_URL را بررسی کنید.")
    out.update({
        "mode": "attention" if warnings else "domain",
        "domain": {k: state.get(k) for k in ("domain", "aliases", "canonical", "ca", "staging", "applied_at", "vhost", "version", "hsts", "strict_hosts")},
        "cert": cert,
        "cert_served": served is not None,
        "dns": {"status": dns["status"], "found": dns.get("found", []), "message": dns["message"]} if dns else None,
        "node_note": state.get("node_note", ""),
        "warnings": warnings,
        "rollback_command": f"{SCRIPT} --rollback",
        "status_command": f"{SCRIPT} --status",
    })
    return out
