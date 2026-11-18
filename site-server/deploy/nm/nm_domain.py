#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""nm-domain - NMarketing را روی دامنهٔ خودِ مالک با HTTPS بنشان؛ همه‌چیز (ویجت، وب‌هوک، لینک‌ها) خودش دنبالش بیاید.

    nm-domain.sh example.ir --www          # دامنه + www، گواهی Let's Encrypt، تنظیمِ NM، سنجشِ نهایی
    nm-domain.sh example.ir --dry-run      # فقط برنامه را نشان بده؛ هیچ چیز عوض نمی‌شود
    nm-domain.sh --status                  # وضعیتِ فعلی (فقط IP / دامنه + تاریخِ انقضای گواهی)
    nm-domain.sh --check-dns example.ir    # فقط DNS را بسنج
    nm-domain.sh --rollback                # همه‌چیز را به حالتِ پیش از دامنه برگردان (گواهی می‌ماند؛ --purge-cert پاکش می‌کند)
    nm-domain.sh --watch                   # نگهبانِ روزانه (cron /etc/cron.d/nm-ops): گواهیِ کم‌مانده را تمدید می‌کند و یک خط می‌نویسد

چه می‌کند (به ترتیب؛ هر مرحله ایده‌مپوتنت است و اگر چیزی خراب شود، همان لحظه همهٔ کارهای این اجرا برمی‌گردد):
  ۱ سنجشِ پیش‌نیازها و DNS (رکوردِ A باید به IP این سرور برسد؛ AAAA نباید باشد)
  ۲ یک vhost برای دامنه روی پورت‌های 80/443 (مثلِ port_8040.conf، همان مسیرها)؛ پورت 8040 (IP) دست نمی‌خورد
  ۳ گواهی: certbot با webroot (همان سازوکارِ سایتِ چغر؛ Let's Encrypt) - از ایران ZeroSSL بسته است، پس فقط LE (یا --self-signed پشتِ CDN)
  ۴ تنظیمِ NM: backend/.env (PUBLIC_BASE_URL، PANEL_URL، CSRF_TRUSTED_ORIGINS، ALLOWED_HOSTS، پروکسیِ SSL)، «نشانیِ عمومیِ سایت» ِ صندوق،
    سایتِ عمومی (NEXT_PUBLIC_*)، ثبتِ دوبارهٔ وب‌هوک‌های ثبت‌شده
  ۵ بازنشانیِ بی‌وقفهٔ سرویس‌ها (nm-reload)، تمدیدِ خودکارِ گواهی (certbot.timer + هوکِ بازخوانیِ nginx) و سنجشِ نهایی

گره‌های پردازش (GPU) با نشانیِ IP ِ خودشان کار می‌کنند و تا به‌روزرسانیِ دستیِ site.json دست نمی‌خورند.

متغیرهای محیطی (برای آزمون، پیش‌فرض‌ها روی سرورِ واقعی درست‌اند):
  NM_ROOT (مسیرِ کدِ زنده)، NM_CONF_ROOT (جایی که backend/.env و data/ از آن خوانده/نوشته می‌شود؛ پیش‌فرض = NM_ROOT)،
  NM_VHOST_DIR، NM_NGINX_BIN، NM_WEBROOT، NM_LE_DIR، NM_SERVER_IP، NM_NO_SERVICES=1 (سرویس‌ها را دست نزن)،
  NM_FAIL_AT=<گام> (آزمونِ برگشت: بعد از آن گام شکستِ ساختگی)، NM_LOCK (مسیرِ قفل)
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_HERE = Path(__file__).resolve()
# منطقِ خالص در backend/apps/panel/domain_core.py است (پنل هم از آن می‌خواند)؛ NM_ROOT یا پوشهٔ والدِ deploy/nm
for _cand in (os.environ.get("NM_ROOT"), str(_HERE.parents[2])):
    if _cand and (Path(_cand) / "backend" / "apps" / "panel" / "domain_core.py").exists():
        sys.path.insert(0, str(Path(_cand) / "backend"))
        break
from apps.panel.domain_core import (  # noqa: E402
    BLOCK_BEGIN, BLOCK_END, VERSION, DomainError, cert_info, dns_report, env_apply, env_restore, env_updates, env_values,
    inbox_plan, inbox_set, knowledge_plan, knowledge_set, merge_csv, normalize_domain, render_vhost, run,
)

DEFAULT_SERVER_IP = "87.107.160.17"
class StepError(RuntimeError):
    """یک گام شکست خورد؛ پیامش فارسی است."""


# ───────────────────────────────────────────────────────────── مسیرها و ابزارکِ عمومی
class Paths:
    def __init__(self) -> None:
        env = os.environ.get
        self.root = Path(env("NM_ROOT", "/var/www/NM/upmarket"))
        self.conf = Path(env("NM_CONF_ROOT", str(self.root)))
        self.env_file = self.conf / "backend" / ".env"
        self.data = self.conf / "data"
        self.state_dir = self.data / "domain"
        self.state_file = self.state_dir / "domain.json"
        self.original_dir = self.state_dir / "original"
        self.website_env = self.conf / "website" / ".env.production.local"
        self.vhost_dir = Path(env("NM_VHOST_DIR", "/www/server/panel/vhost/nginx"))
        self.nginx = env("NM_NGINX_BIN", "/www/server/nginx/sbin/nginx")
        self.webroot = Path(env("NM_WEBROOT", "/var/www/html"))
        self.le = Path(env("NM_LE_DIR", "/etc/letsencrypt"))
        self.certbot = env("NM_CERTBOT_BIN", "/usr/bin/certbot")
        self.server_ip = env("NM_SERVER_IP", DEFAULT_SERVER_IP)
        self.logdir = Path(env("NM_LOGDIR", "/www/wwwlogs"))
        self.lock = Path(env("NM_LOCK", "/root/nm-domain.lock"))
        self.python = env("NM_PYTHON", str(self.root / "venv" / "bin" / "python"))
        self.no_services = env("NM_NO_SERVICES") == "1"
        self.heavy_lock = env("NM_HEAVY_LOCK", "/root/nm-heavy.lock")
        self.build_base = Path(env("NM_BUILD_BASE", "/root"))  # همان دیسکِ NM (hardlink) ولی بیرون از پوشهٔ زنده

    def vhost_file(self, domain: str) -> Path:
        # «zz-» تا tamouz.studio پیش‌فرضِ 443 بماند (مثلِ zz-chagher.conf)
        return self.vhost_dir / f"zz-nm-{domain}.conf"

    def selfsigned_dir(self, domain: str) -> Path:
        return self.state_dir / "selfsigned" / domain


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_text(text: str | bytes | None) -> str:
    if text is None:
        return ""
    data = text.encode("utf-8") if isinstance(text, str) else text
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, text: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    if mode is not None:
        os.chmod(tmp, mode)
    elif path.exists():
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


# ───────────────────────────────────────────────────────────── گزارش‌دهی
class Reporter:
    def __init__(self, log: Path | None = None) -> None:
        self.log_path = log
        self.n = 0

    def _emit(self, text: str) -> None:
        print(text, flush=True)
        if self.log_path:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a", encoding="utf-8") as fh:
                    fh.write(f"{now_iso()} {text}\n")
            except OSError:
                pass

    def step(self, title: str) -> None:
        self.n += 1
        self._emit(f"\n[{self.n}] {title}")

    def say(self, text: str) -> None:
        self._emit(f"    {text}")

    def ok(self, text: str) -> None:
        self._emit(f"    ✓ {text}")

    def warn(self, text: str) -> None:
        self._emit(f"    ⚠ {text}")

    def bad(self, text: str) -> None:
        self._emit(f"    ✗ {text}")


class Run:
    """یک اجرا: فهرستِ «برگردان» (undo)، گزارش‌گر و پرچم‌ها."""

    def __init__(self, P: Paths, a: argparse.Namespace, rep: Reporter) -> None:
        self.P, self.a, self.rep = P, a, rep
        self.dry = bool(getattr(a, "dry_run", False))
        self.undo: list[tuple[str, callable]] = []
        self.changed: set[str] = set()
        self.warnings: list[str] = []

    def on_undo(self, label: str, fn) -> None:
        self.undo.append((label, fn))

    def unwind(self) -> None:
        for label, fn in reversed(self.undo):
            try:
                fn()
                self.rep.say(f"↩ برگشت: {label}")
            except Exception as exc:  # noqa: BLE001 - برگرداندن نباید وسطِ راه بایستد
                self.rep.bad(f"برگرداندنِ «{label}» نشد: {exc}")
        self.undo.clear()

    def checkpoint(self, name: str) -> None:
        if os.environ.get("NM_FAIL_AT") == name:
            raise StepError(f"شکستِ آزمایشی پس از گامِ «{name}» (NM_FAIL_AT)")


# ───────────────────────────────────────────────────────────── nginx
def nginx_test(P: Paths) -> tuple[bool, str]:
    rc, out = run([P.nginx, "-t"], timeout=60)
    return rc == 0, out.strip()


def nginx_reload(P: Paths) -> tuple[bool, str]:
    ok, out = nginx_test(P)
    if not ok:
        return False, out
    rc, out2 = run([P.nginx, "-s", "reload"], timeout=60)
    return rc == 0, out2.strip()


def vhost_clash(P: Paths, names: list[str], own: Path) -> str | None:
    """اگر یکی از نام‌ها در vhostِ دیگری (مثلاً چغر) هست، نامِ آن فایل."""
    if not P.vhost_dir.is_dir():
        return None
    for f in sorted(P.vhost_dir.glob("*.conf")):
        if f == own:
            continue
        txt = re.sub(r"#[^\n]*", "", read_text(f) or "")  # توضیح‌ها نه؛ server_name وسطِ خط هم می‌تواند باشد (`server { listen 80; server_name x; }`)
        for m in re.finditer(r"\bserver_name\s+([^;]+);", txt):
            if set(m.group(1).split()) & set(names):
                return f.name
    return None


def nginx_syntax_check(P: Paths, vhost_text_template: str, rep: Reporter) -> bool:
    """متنِ vhost را در یک nginx.confِ موقتِ جدا می‌آزماید (به nginxِ زنده دست نمی‌زند)."""
    with tempfile.TemporaryDirectory(prefix="nm-domain-") as tmp:
        t = Path(tmp)
        key, crt = t / "privkey.pem", t / "fullchain.pem"
        rc, out = run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(crt),
                       "-days", "1", "-subj", "/CN=nm-domain-syntax"], timeout=60)
        if rc != 0:
            rep.warn("آزمونِ نحوِ nginx انجام نشد (openssl): " + out.strip()[-200:])
            return True
        text = vhost_text_template.replace("{CERT}", str(t))
        (t / "nginx.conf").write_text(
            f"pid {t}/nginx.pid;\nerror_log {t}/err.log;\nevents {{}}\nhttp {{\n  access_log off;\n  client_body_temp_path {t}/b;\n"
            f"  proxy_temp_path {t}/p;\n  fastcgi_temp_path {t}/f;\n  uwsgi_temp_path {t}/u;\n  scgi_temp_path {t}/s;\n"
            f"  map $http_upgrade $connection_upgrade {{ default upgrade; '' close; }}\n{text}\n}}\n", encoding="utf-8")
        rc, out = run([P.nginx, "-t", "-c", str(t / "nginx.conf"), "-p", str(t)], timeout=60)
        if rc != 0:
            rep.bad("نحوِ vhost درست نیست:\n" + out.strip())
        return rc == 0


# ───────────────────────────────────────────────────────────── وضعیت (state)
def load_state(P: Paths) -> dict | None:
    try:
        return json.loads(P.state_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


def save_state(P: Paths, state: dict) -> None:
    atomic_write(P.state_file, json.dumps(state, ensure_ascii=False, indent=2) + "\n", 0o600)


# ───────────────────────────────────────────────────────────── گواهی: صدور
def _le_account_args(P: Paths, staging: bool, email: str | None) -> list[str]:
    server_dir = P.le / "accounts" / ("acme-staging-v02.api.letsencrypt.org" if staging else "acme-v02.api.letsencrypt.org") / "directory"
    accounts = sorted([d for d in server_dir.glob("*") if d.is_dir()], key=lambda d: d.stat().st_mtime, reverse=True) if server_dir.is_dir() else []
    args: list[str] = []
    if email:
        args += ["-m", email]
    elif not accounts:
        args += ["--register-unsafely-without-email"]
    if len(accounts) > 1:
        args += ["--account", accounts[0].name]
    return args


def explain_certbot_failure(out: str, names: list[str]) -> str:
    low = out.lower()
    if "too many" in low or "rate limit" in low or "ratelimited" in low:
        m = re.search(r"retry after ([0-9: \-UTC]+)", out)
        return ("Let's Encrypt سقفِ تعدادِ گواهی را برای این دامنه پر دانسته است (محدودیتِ هفتگی/ساعتی)"
                + (f"؛ می‌گوید بعد از {m.group(1).strip()} دوباره تلاش کنید." if m else "؛ چند ساعت (گاهی تا یک هفته) صبر کنید.")
                + " تا آن موقع می‌توانید با --staging همه‌چیز را آزمایش کنید.")
    if "connection refused" in low or "timeout" in low or "could not connect" in low or ("fetching" in low and "404" not in low):
        return ("Let's Encrypt نتوانست به سرور وصل شود. مطمئن شوید رکوردِ A درست و پخش‌شده است و پورتِ 80 از بیرون باز است "
                "(فایروال/ابرِ CDN). اگر DNS تازه عوض شده، ۳۰ دقیقه صبر کنید.")
    if "unauthorized" in low or "404" in low or "invalid response" in low:
        return ("چالشِ http-01 درست جواب داده نشد: یا رکوردِ A هنوز به این سرور نمی‌رسد، یا یک CDN/پروکسی (ابرِ نارنجی) وسط است. "
                "DNS را بررسی کنید (nm-domain.sh --check-dns <دامنه>) و دوباره اجرا کنید.")
    if "dns problem" in low or "nxdomain" in low or "no valid ip" in low:
        return "Let's Encrypt رکوردِ DNS دامنه را پیدا نکرد (NXDOMAIN)؛ رکوردِ A را بسازید و منتظرِ پخش‌شدن بمانید."
    if "network is unreachable" in low or "name or service not known" in low or ("acme-v02" in low and "failed to" in low):
        return ("از این سرور به Let's Encrypt دسترسی نیست (تحریم/قطعیِ شبکه). ZeroSSL هم از ایران بسته است. "
                "راه‌ها: ۱) چند دقیقه بعد دوباره اجرا کنید؛ ۲) دامنه را پشتِ CDNِ آروان‌کلاود ببرید (گواهی را خودِ آروان می‌دهد) و با --self-signed اجرا کنید.")
    return "صدورِ گواهی شکست خورد؛ متنِ کاملِ خطا بالاست (و در /var/log/letsencrypt/letsencrypt.log)."


LE_FA = "Let's Encrypt"
LE_STAGING_FA = "Let's Encrypt آزمایشی (staging)"


def kind_of(info: dict) -> str:
    return "آزمایشی" if info["staging"] else ("خودامضا" if info["self_signed"] else LE_FA)


def ensure_cert(run_: Run, domain: str, names: list[str], ca: str) -> tuple[str, dict | None]:
    """مسیرِ پوشهٔ گواهی (fullchain.pem/privkey.pem) و اطلاعاتش؛ در dry-run فقط می‌گوید چه می‌کند."""
    P, rep, a = run_.P, run_.rep, run_.a
    if ca == "selfsigned":
        d = P.selfsigned_dir(domain)
        info = cert_info(d / "fullchain.pem")
        if info and set(names) <= set(info["names"]) and info["days_left"] > 30:
            rep.ok(f"گواهیِ خودامضا از قبل هست ({info['days_left']} روز مانده)")
            return str(d), info
        if run_.dry:
            rep.say("گواهیِ خودامضا (۳۶۵۰ روز) می‌سازم - فقط برای پشتِ CDN یا آزمون؛ مرورگرِ بازدیدکننده هشدار می‌دهد")
            return str(d), None
        d.mkdir(parents=True, exist_ok=True)
        san = ",".join(f"DNS:{n}" for n in names)
        rc, out = run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(d / "privkey.pem"), "-out", str(d / "fullchain.pem"),
                       "-days", "3650", "-subj", f"/CN={domain}", "-addext", f"subjectAltName={san}"], timeout=60)
        if rc != 0:
            raise StepError("ساختنِ گواهیِ خودامضا نشد: " + out.strip()[-300:])
        os.chmod(d / "privkey.pem", 0o600)
        rep.ok("گواهیِ خودامضا ساخته شد (۱۰ سال)")
        return str(d), cert_info(d / "fullchain.pem")

    staging = ca == "letsencrypt-staging"
    lineage = P.le / "live" / domain
    info = cert_info(lineage / "cert.pem")
    stale = info is not None and (info["staging"] != staging or info["self_signed"])
    if info and not stale and set(names) <= set(info["names"]) and info["days_left"] >= 30 and not a.force_renew:
        rep.ok(f"گواهیِ معتبر از قبل هست ({info['days_left']} روز مانده، {kind_of(info)}) - صدورِ تازه لازم نیست")
        return str(lineage), info
    why = ("نوعِ گواهی عوض شده (آزمایشی ⇄ واقعی)" if stale else "نام‌ها را پوشش نمی‌دهد/کم‌مانده" if info else "گواهی‌ای نیست")
    if run_.dry:
        rep.say(f"گواهی می‌گیرم ({LE_STAGING_FA if staging else LE_FA}؛ {why}) برای: {' '.join(names)}")
        return str(lineage), info
    if not Path(P.certbot).exists():
        raise StepError("certbot نصب نیست (apt install certbot).")
    P.webroot.mkdir(parents=True, exist_ok=True)
    if stale:
        rc, out = run([P.certbot, "delete", "--cert-name", domain, "--non-interactive"], timeout=120)
        rep.say("گواهیِ نوعِ دیگر پاک شد تا گواهیِ تازه جایش بیاید" if rc == 0 else "حذفِ گواهیِ قبلی نشد: " + out.strip()[-200:])
    cmd = [P.certbot, "certonly", "--webroot", "-w", str(P.webroot), "--cert-name", domain, "--non-interactive", "--agree-tos",
           "--keep-until-expiring", "--expand", "--no-eff-email"]
    for n in names:
        cmd += ["-d", n]
    if staging:
        cmd += ["--staging"]
    if a.force_renew:
        cmd += ["--force-renewal"]
    cmd += _le_account_args(P, staging, a.email)
    rep.say("certbot اجرا می‌شود (چند ثانیه تا یک دقیقه) ...")
    rc, out = run(cmd, timeout=420)
    if rc != 0:
        rep.bad("certbot:\n" + "\n".join("      " + ln for ln in out.strip().splitlines()[-14:]))
        raise StepError(explain_certbot_failure(out, names))
    info = cert_info(lineage / "cert.pem")
    if not info:
        raise StepError("certbot گفت موفق بود ولی فایلِ گواهی پیدا نشد: " + str(lineage))
    rep.ok(f"گواهی صادر شد ({kind_of(info)}؛ {info['days_left']} روز اعتبار؛ نام‌ها: {' '.join(info['names'])})")
    return str(lineage), info


def ensure_renewal(run_: Run, domain: str, ca: str) -> None:
    P, rep = run_.P, run_.rep
    if ca == "selfsigned":
        rep.say("گواهیِ خودامضا تمدید نمی‌خواهد (۱۰ سال).")
        return
    hooks = P.le / "renewal-hooks" / "deploy"
    has_hook = hooks.is_dir() and any(os.access(f, os.X_OK) and "nginx" in (read_text(f) or "") for f in hooks.iterdir() if f.is_file())
    if not has_hook:
        if run_.dry:
            rep.say("هوکِ بازخوانیِ nginx بعد از تمدید را می‌سازم")
        else:
            atomic_write(hooks / "nm-reload-nginx.sh",
                         f"#!/bin/sh\n# NM: بعد از تمدیدِ گواهی nginx را بازخوانی کن (اول آزمون؛ به سایت‌های دیگر آسیب نزند)\n{P.nginx} -t >/dev/null 2>&1 && {P.nginx} -s reload\n", 0o755)
            rep.ok("هوکِ بازخوانیِ nginx بعد از تمدید ساخته شد")
    else:
        rep.ok("هوکِ بازخوانیِ nginx بعد از تمدید از قبل هست")
    if P.no_services:
        rep.say("(حالتِ آزمون) certbot.timer دست نخورد")
    else:
        rc, out = run(["systemctl", "is-active", "certbot.timer"], timeout=20)
        if out.strip() != "active":
            if run_.dry:
                rep.say("certbot.timer را فعال می‌کنم")
            else:
                run(["systemctl", "enable", "--now", "certbot.timer"], timeout=30)
                rep.ok("certbot.timer فعال شد (تمدیدِ خودکار، روزی دو بار بررسی)")
        else:
            rep.ok("تمدیدِ خودکار فعال است (certbot.timer؛ ۳۰ روز مانده به انقضا تمدید می‌کند)")
    if run_.dry:
        rep.say("تمدید را «آزمایشی» می‌آزمایم (certbot renew --dry-run)")
        return
    rc, out = run([P.certbot, "renew", "--cert-name", domain, "--dry-run", "--no-random-sleep-on-renew"], timeout=300)
    if rc == 0:
        rep.ok("آزمونِ تمدید (dry-run) موفق بود")
    else:
        msg = "آزمونِ تمدید (dry-run) موفق نبود؛ تمدیدِ خودکار ممکن است کار نکند: " + out.strip()[-300:]
        rep.warn(msg)
        run_.warnings.append(msg)


# ───────────────────────────────────────────────────────────── سرویس‌ها و سایت
def reload_services(run_: Run, restart_celery: bool = True) -> None:
    P, rep = run_.P, run_.rep
    if P.no_services or run_.a.no_restart:
        rep.say("(سرویس‌ها دست نخوردند" + (" - حالتِ آزمون)" if P.no_services else " - --no-restart؛ بعداً: nm-reload)"))
        return
    if run_.dry:
        rep.say("nm-reload (بازنشانیِ بی‌وقفهٔ وب) و راه‌اندازیِ دوبارهٔ nm-celery و nm-celery-beat")
        return
    rc, out = run(["nm-reload"], timeout=120) if shutil.which("nm-reload") else run(["systemctl", "reload", "nm-web"], timeout=60)
    (rep.ok if rc == 0 else rep.bad)("وب (gunicorn) بی‌وقفه بازنشانی شد" if rc == 0 else "بازنشانیِ وب: " + out.strip()[-200:])
    if rc != 0:
        raise StepError("بازنشانیِ nm-web شکست خورد.")
    if restart_celery:
        rc, out = run(["systemctl", "restart", "nm-celery", "nm-celery-beat"], timeout=180)
        (rep.ok if rc == 0 else rep.warn)("nm-celery و nm-celery-beat دوباره راه افتادند" if rc == 0 else "راه‌اندازیِ celery: " + out.strip()[-200:])
        busy = _running_compute_jobs(P)
        if busy:
            rep.warn(f"{busy} کارِ سرورِ پردازش در حالِ اجراست؛ nm-celery-node را دست نزدم (کارها نیمه نماند). "
                     "نشانی‌های تازه را در اولین راه‌اندازیِ بعدی برمی‌دارد؛ هر وقت کاری در جریان نبود: systemctl restart nm-celery-node")
        else:
            rc, out = run(["systemctl", "restart", "nm-celery-node"], timeout=180)
            (rep.ok if rc == 0 else rep.warn)("nm-celery-node هم دوباره راه افتاد" if rc == 0 else "nm-celery-node: " + out.strip()[-200:])


def _running_compute_jobs(P: Paths) -> int:
    try:
        env = env_values(read_text(P.env_file) or "")
        db = Path(env.get("SQLITE_PATH") or P.data / "db.sqlite3")
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
        try:
            return int(con.execute("SELECT COUNT(*) FROM compute_computejob WHERE state IN ('CLAIMED','RUNNING')").fetchone()[0])
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return 0


def website_set_env(run_: Run, base: str, record: dict) -> bool:
    """NEXT_PUBLIC_* در website/.env.production.local (نه خودِ ساخت). True = فایل عوض شد."""
    P, rep = run_.P, run_.rep
    cur = read_text(P.website_env)
    desired = {"NEXT_PUBLIC_PANEL_URL": base + "/panel", "NEXT_PUBLIC_SITE_URL": base}
    new = env_apply(cur or "", desired)
    if new == (cur or ""):
        rep.ok("env ِ سایتِ عمومی از قبل درست است")
        return False
    vals = env_values(cur or "")
    record.setdefault("website_env", {"existed": cur is not None, "prev": {k: vals.get(k) for k in desired}})
    if run_.dry:
        rep.say("env ِ سایتِ عمومی: NEXT_PUBLIC_SITE_URL / NEXT_PUBLIC_PANEL_URL ⇒ " + base)
        return True
    atomic_write(P.website_env, new, 0o600)
    run_.on_undo("env ِ سایتِ عمومی", lambda: (atomic_write(P.website_env, cur, 0o600) if cur is not None else P.website_env.unlink(missing_ok=True)))
    rep.ok("env ِ سایتِ عمومی عوض شد")
    return True


def website_rebuild(run_: Run, base: str, swap: bool) -> bool:
    """سایتِ عمومی (Next.js) نشانیِ خودش را در زمانِ ساخت داخلِ صفحه‌ها می‌گذارد (canonical، sitemap، OG)؛ پس باید دوباره ساخته شود.
    در پوشهٔ جدا (hardlink از node_modules) ساخته می‌شود و فقط پس از موفقیت جابه‌جا می‌شود؛ سایتِ زنده تا آن لحظه دست‌نخورده است."""
    P, rep = run_.P, run_.rep
    src = P.root / "website"
    if not (src / "package.json").exists() or not (src / "node_modules").is_dir():
        rep.warn("سایتِ عمومی (website/) در این نصب نیست؛ ساخت رد شد.")
        return False
    if run_.dry:
        rep.say("سایتِ عمومی را در پوشهٔ جدا می‌سازم (npm run build؛ چند دقیقه، با قفلِ /root/nm-heavy.lock) و بعد جابه‌جا می‌کنم")
        return True
    ts = time.strftime("%Y%m%d-%H%M%S")
    build = P.build_base / f"nm-site-build-{ts}"
    try:
        build.mkdir()
        rc, out = run(["rsync", "-a", "--exclude", "node_modules", "--exclude", ".next", f"{src}/", f"{build}/"], timeout=300)
        if rc != 0:
            raise StepError("کپیِ سورسِ سایت نشد: " + out[-200:])
        rc, out = run(["cp", "-al", str(src / "node_modules"), str(build / "node_modules")], timeout=600)
        if rc != 0:
            raise StepError("کپیِ (hardlink) node_modules نشد: " + out[-200:])
        env_text = read_text(P.website_env) or ""
        (build / ".env.production.local").write_text(env_text, encoding="utf-8")
        rep.say("npm run build ... (سایتِ زنده دست‌نخورده می‌ماند)")
        script = ("set -e; cd '%s'; export NODE_OPTIONS=--max-old-space-size=2048; npm run build 2>&1 | tail -8; "
                  "test -f .next/standalone/server.js; "
                  "rm -rf .next/standalone/.next/static && cp -r .next/static .next/standalone/.next/static; "
                  "rm -rf .next/standalone/public && cp -r public .next/standalone/public; "
                  "if [ -d assets ]; then rm -rf .next/standalone/assets && cp -r assets .next/standalone/assets; fi") % build
        rc, out = run(["flock", "-w", "3600", P.heavy_lock, "nice", "-n", "10", "bash", "-c", script], timeout=3000)
        if rc != 0:
            raise StepError("ساختِ سایتِ عمومی شکست خورد:\n" + out.strip()[-600:])
        baked = run(["grep", "-rlF", base, str(build / ".next" / "server" / "app")], timeout=60)[1].strip().splitlines()
        if not baked:
            raise StepError(f"نشانیِ تازه ({base}) در صفحه‌های ساخته‌شدهٔ سایتِ عمومی نیست؛ جابه‌جا نکردم.")
        rep.ok(f"سایتِ عمومی ساخته شد؛ نشانیِ تازه در {len(baked)} فایل هست")
        if not swap:
            rep.say("(حالتِ آزمون/staging) جابه‌جایی انجام نشد؛ پوشهٔ ساخت پاک می‌شود")
            return True
        old = src / f".next.old-{ts}"
        os.rename(src / ".next", old)
        os.rename(build / ".next", src / ".next")
        rc, out = run(["systemctl", "restart", "nm-website"], timeout=60)
        time.sleep(4)
        healthy = False
        for _ in range(10):
            try:
                c = http.client.HTTPConnection("127.0.0.1", 3001, timeout=5)
                c.request("GET", "/")
                healthy = c.getresponse().status < 500
                break
            except OSError:
                time.sleep(2)
        if not healthy:
            os.rename(src / ".next", build / ".next-bad")
            os.rename(old, src / ".next")
            run(["systemctl", "restart", "nm-website"], timeout=60)
            raise StepError("سایتِ عمومی بعد از جابه‌جایی جواب نداد؛ ساختِ قبلی برگشت.")
        shutil.rmtree(old, ignore_errors=True)
        rep.ok("سایتِ عمومی با نشانیِ تازه بالا آمد")
        return True
    finally:
        if build.exists() and build.parent == P.build_base and build.name.startswith("nm-site-build-"):
            shutil.rmtree(build, ignore_errors=True)


def website_step(run_: Run, base: str, state: dict) -> None:
    """سایتِ عمومی (Next.js) نشانیِ خودش را موقعِ ساخت در صفحه‌ها می‌گذارد؛ پس env عوض و سایت دوباره ساخته می‌شود.
    آخرین گام است و جزوِ «معامله» نیست: دامنه و https مهم‌ترند، پس شکستِ ساختِ سایت فقط هشدار می‌دهد (بعداً دوباره اجرا کنید)."""
    P, rep, a = run_.P, run_.rep, run_.a
    rep.step("سایتِ عمومی (Next.js) - آخرین گام؛ اگر نشد بقیه برقرار می‌ماند")
    if a.no_website:
        rep.say("رد شد (--no-website)")
        return
    try:
        changed = website_set_env(run_, base, state)
        if changed and not run_.dry:
            save_state(P, state)  # رکوردِ «env ِ پیشین» برای --rollback باید همین‌جا ثبت شود
        if not (changed or state.get("website_built_for") != base or a.force_renew):
            rep.ok("سایتِ عمومی از قبل با همین نشانی ساخته شده")
            return
        if os.environ.get("NM_SKIP_WEBSITE_BUILD") == "1":
            rep.say("(حالتِ آزمون) ساختِ سایتِ عمومی رد شد")
            return
        real = not (a.staging or P.no_services or P.conf != P.root)
        built = website_rebuild(run_, base, swap=real)
        if built and real and not run_.dry:
            state["website_built_for"] = base
            save_state(P, state)
    except Exception as exc:  # noqa: BLE001
        rep.warn(f"سایتِ عمومی با نشانیِ تازه ساخته نشد ({exc}). بقیه‌چیز آماده است؛ بعداً همین دستور را دوباره اجرا کنید تا ساخته شود.")
        run_.warnings.append("website")


# ───────────────────────────────────────────────────────────── سنجشِ نهایی
def http_get(domain: str, path: str, scheme: str, verify: bool, ip: str = "127.0.0.1", port: int | None = None, timeout: int = 20):
    """درخواست به nginxِ همین سرور با نامِ دامنه (بی نیاز به DNS)."""
    port = port or (443 if scheme == "https" else 80)
    raw = socket.create_connection((ip, port), timeout=timeout)
    if scheme == "https":
        ctx = ssl.create_default_context() if verify else ssl._create_unverified_context()  # noqa: S323
        sock = ctx.wrap_socket(raw, server_hostname=domain)
        conn = http.client.HTTPSConnection(domain, port, timeout=timeout, context=ctx)
    else:
        sock = raw
        conn = http.client.HTTPConnection(domain, port, timeout=timeout)
    conn.sock = sock
    conn.request("GET", path, headers={"Host": domain, "User-Agent": "nm-domain-smoke/1.0"})
    r = conn.getresponse()
    body = r.read(2048)
    conn.close()
    return r.status, dict(r.getheaders()), body


def smoke(run_: Run, domain: str, aliases: list[str], ca: str, info: dict | None) -> list[tuple[str, bool, str, bool]]:
    """[(نام، موفق؟، توضیح، حیاتی؟)]"""
    P = run_.P
    verify = ca == "letsencrypt"
    res: list[tuple[str, bool, str, bool]] = []

    def add(name: str, ok: bool, detail: str, critical: bool = True) -> None:
        res.append((name, ok, detail, critical))

    try:
        st, hd, _ = http_get(domain, "/healthz", "http", False, port=80)
        loc = hd.get("Location", "")
        add("ریدایرکتِ http ⇒ https", st in (301, 308) and loc.startswith(f"https://{domain}"), f"{st} → {loc}")
    except OSError as exc:
        add("ریدایرکتِ http ⇒ https", False, str(exc))
    try:
        st, hd, body = http_get(domain, "/healthz", "https", verify)
        add("https /healthz (جنگو)", st == 200, f"{st}")
    except (OSError, ssl.SSLError) as exc:
        add("https /healthz (جنگو)", False, str(exc))
    for path, label, crit in (("/panel/", "https /panel/ (پنل)", True), ("/", "https / (سایتِ عمومی)", False)):
        try:
            st, hd, _ = http_get(domain, path, "https", verify)
            add(label, 200 <= st < 400, f"{st}", crit)
        except (OSError, ssl.SSLError) as exc:
            add(label, False, str(exc), crit)
    for al in aliases:
        try:
            st, hd, _ = http_get(al, "/x", "https", verify)
            add(f"ریدایرکتِ {al} ⇒ {domain}", st == 301 and hd.get("Location", "").startswith(f"https://{domain}"), f"{st} {hd.get('Location', '')}", False)
        except (OSError, ssl.SSLError) as exc:
            add(f"ریدایرکتِ {al}", False, str(exc), False)
    try:
        st, _, _ = http_get(P.server_ip, "/healthz", "http", False, port=8040)
        add("نشانیِ قدیمیِ IP:8040 هنوز کار می‌کند", st == 200, f"{st}")
    except OSError as exc:
        add("نشانیِ قدیمیِ IP:8040 هنوز کار می‌کند", False, str(exc))
    if info:
        add("گواهی همهٔ نام‌ها را پوشش می‌دهد", set([domain, *aliases]) <= set(info["names"]), " ".join(info["names"]))
        add("اعتبارِ گواهی", info["days_left"] > 14, f"{info['days_left']} روز")
    # پیروی از تنظیمات: نشانیِ عمومی، میزبانِ مجاز، CSRF، SSL پشتِ پروکسی - با خودِ جنگو
    rc, out = _django_report(P, domain)
    if rc == 0:
        try:
            rep = json.loads(out.strip().splitlines()[-1])
            add("نشانیِ عمومی (ویجت/وب‌هوک/لینک‌ها) = https://" + domain, rep.get("public_url") == f"https://{domain}" and rep.get("secure"), rep.get("public_url", ""))
            add("میزبانِ مجاز (ALLOWED_HOSTS)", bool(rep.get("host_allowed")), "")
            add("CSRF_TRUSTED_ORIGINS", bool(rep.get("csrf_ok")), "")
            add("جنگو https را از nginx می‌شناسد (X-Forwarded-Proto)", bool(rep.get("proxy_ssl")), "")
            add("نمونهٔ وب‌هوک و ویجت روی دامنه", bool(rep.get("samples_ok")), rep.get("webhook_sample", ""))
        except (ValueError, IndexError):
            add("گزارشِ تنظیماتِ جنگو", False, out.strip()[-200:])
    else:
        add("گزارشِ تنظیماتِ جنگو", False, out.strip()[-300:])
    return res


def _django_report(P: Paths, domain: str) -> tuple[int, str]:
    env = {"PYTHONIOENCODING": "utf-8"}
    p = subprocess.run([P.python, "manage.py", "nm_domain", "report", "--domain", domain], cwd=str(P.conf / "backend"),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=240, env={**os.environ, **env}, check=False)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def hooks_command(P: Paths, *extra: str) -> tuple[int, str]:
    p = subprocess.run([P.python, "manage.py", "nm_domain", "hooks", *extra], cwd=str(P.conf / "backend"),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, check=False)
    return p.returncode, p.stdout.decode("utf-8", "replace")


# ───────────────────────────────────────────────────────────── apply
def preflight(P: Paths, rep: Reporter, ca: str) -> None:
    if os.geteuid() != 0 and os.environ.get("NM_ALLOW_NONROOT") != "1":
        raise StepError("این ابزار باید با root اجرا شود (sudo -i).")
    if not Path(P.nginx).exists():
        raise StepError(f"nginx پیدا نشد: {P.nginx}")
    if ca != "selfsigned" and not Path(P.certbot).exists():
        raise StepError("certbot نصب نیست (apt install certbot).")
    if not P.env_file.exists():
        raise StepError(f"{P.env_file} پیدا نشد؛ این پوشه یک نصبِ NM نیست.")
    free_mb = shutil.disk_usage(str(P.conf)).free // (1024 * 1024)
    if free_mb < 300:
        raise StepError(f"فضای خالیِ دیسک کم است ({free_mb} مگابایت)؛ اول جا باز کنید.")
    ok, out = nginx_test(P)
    if not ok:
        raise StepError("nginx همین الان هم خطای تنظیمات دارد؛ اول آن را درست کنید (nginx -t):\n" + out[-400:])
    rep.ok(f"nginx سالم، دیسک {free_mb} مگابایت خالی، certbot {'(لازم نیست)' if ca == 'selfsigned' else 'هست'}")


def cmd_apply(P: Paths, a: argparse.Namespace) -> int:
    rep = Reporter(None if a.dry_run else P.state_dir / "nm-domain.log")
    try:
        domain, aliases = normalize_domain(a.domain, a.www)
    except DomainError as exc:
        print(f"✗ {exc}")
        return 2
    names = [domain, *aliases]
    ca = "selfsigned" if a.self_signed else ("letsencrypt-staging" if a.staging else "letsencrypt")
    run_ = Run(P, a, rep)
    banner = f"nm-domain {VERSION} - {'پیش‌نمایش (dry-run؛ هیچ چیز عوض نمی‌شود)' if a.dry_run else 'اجرا'} - دامنه: {' '.join(names)} - گواهی: {ca}"
    print(banner)
    state = load_state(P) or {}
    try:
        rep.step("پیش‌نیازها")
        preflight(P, rep, ca)
        own = P.vhost_file(domain)
        clash = vhost_clash(P, names, own)
        if clash:
            raise StepError(f"این نام‌ها از قبل در تنظیماتِ nginx برای سایتِ دیگری هست ({clash}). دامنهٔ دیگری بدهید؛ به آن سایت دست نمی‌زنم. "
                            "(اگر خودتان این دامنه را در aaPanel به‌عنوانِ «سایت» ساخته‌اید، آن را حذف کنید و دوباره اجرا کنید.)")

        rep.step("DNS (رکوردِ A باید به IP این سرور برسد)")
        if a.skip_dns_check:
            rep.warn("سنجشِ DNS رد شد (--skip-dns-check)")
        else:
            for n in names:
                d = dns_report(n, P.server_ip)
                (rep.ok if d["status"] == "ok" else rep.bad)(d["message"])
                if d["status"] != "ok":
                    print("\nبرای ادامه: رکوردهای DNS را درست کنید و دوباره همین دستور را اجرا کنید. (راهنما: docs/deploy/domain-fa.md)")
                    return 3

        final_probe = render_vhost(domain, aliases, phase="final", root=str(P.root), webroot=str(P.webroot), cert_dir="{CERT}",
                                   logdir="{CERT}", hsts=a.hsts)
        if not a.dry_run:
            P.state_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(P.state_dir, 0o700)
            snapshot_original(P, rep, state)

        rep.step("vhostِ nginx برای دامنه")
        if nginx_syntax_check(P, final_probe, rep):
            rep.ok("نحوِ vhostِ نهایی با nginx آزموده شد (در پوشهٔ موقتِ جدا؛ به nginxِ زنده دست نخورد)")
        elif a.dry_run:
            return 1
        else:
            raise StepError("vhostِ ساخته‌شده نحوِ درست ندارد (باگِ ابزار)؛ هیچ چیز عوض نشد.")
        own_state = "هست" if own.exists() else "نیست"
        existing = cert_info((P.le / "live" / domain / "cert.pem") if ca != "selfsigned" else (P.selfsigned_dir(domain) / "fullchain.pem"))
        need_bootstrap = (ca != "selfsigned") and not (
            existing and set(names) <= set(existing["names"]) and existing["staging"] == (ca == "letsencrypt-staging") and not a.force_renew)
        if a.dry_run:
            rep.say(f"فایل: {own} (فعلاً {own_state})؛ پورت 8040 و سایت‌های دیگر دست نمی‌خورند")
            if need_bootstrap:
                rep.say("اول یک vhostِ موقتِ پورت 80 می‌گذارم تا Let's Encrypt مالکیتِ دامنه را بسنجد")
        elif need_bootstrap:
            install_vhost(run_, own, render_vhost(domain, aliases, phase="bootstrap", root=str(P.root), webroot=str(P.webroot), cert_dir=None,
                                                  logdir=str(P.logdir), hsts=False), "vhostِ موقتِ پورت 80 (برای تأییدِ مالکیتِ دامنه)")
            run_.checkpoint("vhost-bootstrap")

        rep.step("گواهیِ https")
        cert_dir, info = ensure_cert(run_, domain, names, ca)
        run_.checkpoint("cert")

        rep.step("vhostِ نهایی (80 ⇒ ریدایرکت، 443 ⇒ NM)")
        if a.dry_run:
            rep.say("می‌نویسم و nginx -t و reload (بی‌وقفه) می‌کنم")
        else:
            install_vhost(run_, own, render_vhost(domain, aliases, phase="final", root=str(P.root), webroot=str(P.webroot), cert_dir=cert_dir,
                                                  logdir=str(P.logdir), hsts=a.hsts), "vhostِ نهایی")
            run_.checkpoint("vhost-final")

        rep.step("تنظیمِ NM (نشانیِ عمومی و میزبان‌های مجاز)")
        env_text = read_text(P.env_file) or ""
        cur = env_values(env_text)
        upd = env_updates(cur, domain, aliases, a.strict_hosts, P.server_ip)
        new_env = env_apply(env_text, upd)
        if "DJANGO_ALLOWED_HOSTS" not in upd and not cur.get("DJANGO_ALLOWED_HOSTS"):
            rep.say("ALLOWED_HOSTS الان «*» است و دامنه را هم می‌پذیرد؛ برای فهرستِ سخت‌گیرانه: --strict-hosts")
        env_changed = new_env != env_text
        base = f"https://{domain}"
        if env_changed:
            prev = {k: cur.get(k) for k in upd}
            for k, v in prev.items():
                state.setdefault("env_prev", {}).setdefault(k, v)
            if a.dry_run:
                for k, v in upd.items():
                    if cur.get(k) != v:
                        rep.say(f"backend/.env: {k} = {v}   (قبلی: {cur.get(k) if cur.get(k) is not None else '—'})")
            else:
                atomic_write(P.env_file, new_env)
                run_.on_undo("backend/.env", lambda: atomic_write(P.env_file, env_text))
                rep.ok("backend/.env به‌روز شد: " + "، ".join(upd))
                run_.changed.add("env")
        else:
            rep.ok("backend/.env از قبل درست است")
        run_.checkpoint("env")

        db = Path(env_values(new_env).get("SQLITE_PATH") or P.data / "db.sqlite3")
        prev_urls = {state["canonical"]} if state.get("canonical") and state.get("canonical") != base else set()
        for label, key, plan, setter, target in (
                ("«نشانیِ عمومیِ سایت» ِ صندوق", "inbox_prev", inbox_plan, inbox_set, base),
                ("نشانیِ سایت در دانشِ «جذب مشتری»", "knowledge_prev", knowledge_plan, knowledge_set, base + "/")):
            old_set = {u + "/" for u in prev_urls} if target.endswith("/") else prev_urls
            todo, why = plan(db, target, old_set)
            if why:
                rep.warn(f"{label}: {why}")
            elif todo:
                if a.dry_run:
                    rep.say(f"{label}: {len(todo)} ردیف ⇒ {target}")
                else:
                    for i, old in todo:
                        state.setdefault(key, {}).setdefault(str(i), old)
                    setter(db, {i: target for i, _ in todo})
                    run_.on_undo(label, lambda t=todo, d=db, f=setter: f(d, {i: old for i, old in t}))
                    rep.ok(f"{label}: {len(todo)} ردیف ⇒ {target}")
                    run_.changed.add("inbox")
            else:
                rep.ok(f"{label}: از قبل درست است (یا نشانیِ دلخواهِ خودتان است و دست نخورد)")
        run_.checkpoint("inbox")

        rep.step("بازنشانیِ سرویس‌ها")
        if a.dry_run or run_.changed & {"env", "inbox"} or a.force_renew:
            reload_services(run_)
        else:
            rep.ok("تغییری نبود؛ سرویس‌ها دست نخوردند")
        run_.checkpoint("services")

        rep.step("وب‌هوک‌های ثبت‌شده (تلگرام/بله/…)")
        if a.dry_run or P.no_services or a.no_webhooks:
            rep.say("(" + ("پیش‌نمایش" if a.dry_run else "حالتِ آزمون/--no-webhooks") + ") فقط شمارش:")
            rc, out = hooks_command(P, "--dry-run")
            rep.say(out.strip().splitlines()[-1] if out.strip() else "-")
        else:
            rc, out = hooks_command(P)
            for ln in out.strip().splitlines()[-6:]:
                rep.say(ln)
            if rc != 0:
                rep.warn("ثبتِ دوبارهٔ وب‌هوک‌ها کامل نشد (کانال‌ها را از پنل ⇐ کانال‌های صندوق دوباره «وب‌هوک» بزنید).")

        rep.step("تمدیدِ خودکارِ گواهی")
        ensure_renewal(run_, domain, ca)

        if a.dry_run:
            website_step(run_, base, state)
            print("\n(dry-run) پایان؛ هیچ چیز عوض نشد. برای اجرای واقعی همین دستور را بدونِ --dry-run بزنید.")
            return 0

        rep.step("سنجشِ نهایی (همه‌چیز با خودِ سرور آزموده می‌شود)")
        results = [] if os.environ.get("NM_SKIP_SMOKE") == "1" else smoke(run_, domain, aliases, ca, info)  # NM_SKIP_SMOKE: فقط آزمونِ واحد
        bad_critical = False
        for name, ok, detail, critical in results:
            if ok:
                rep.ok(f"{name}" + (f"  [{detail}]" if detail else ""))
            elif critical:
                rep.bad(f"{name}  [{detail}]")
                bad_critical = True
            else:
                rep.warn(f"{name}  [{detail}]")
                run_.warnings.append(name)
        run_.checkpoint("smoke")
        if bad_critical:
            raise StepError("سنجشِ نهایی موفق نبود (بالا ببینید).")

        state.update({
            "schema": 1, "version": VERSION, "domain": domain, "aliases": aliases, "www": bool(aliases), "canonical": base,
            "ca": ca, "staging": ca == "letsencrypt-staging", "cert_dir": cert_dir, "cert_not_after": (info or {}).get("not_after", ""),
            "vhost": str(own), "applied_at": now_iso(), "server_ip": P.server_ip, "hsts": bool(a.hsts),
            "strict_hosts": bool(a.strict_hosts), "node_site_url": f"http://{P.server_ip}:8040",
            "node_note": "گره‌های پردازش با نشانیِ IP کار می‌کنند و تا به‌روزرسانیِ دستیِ site.json دست نمی‌خورند.",
        })
        save_state(P, state)
        run_.undo.clear()
        website_step(run_, base, state)  # آخرین گام و بیرون از «معامله»: شکستش دامنه را برنمی‌گرداند
        done_msg(P, domain, aliases, ca, base, run_.warnings)
        return 0
    except StepError as exc:
        rep.bad(str(exc))
        if getattr(a, "keep_on_failure", False):
            rep.warn("(--keep-on-failure) تغییرات برنگشتند.")
        else:
            touched = set(run_.changed)
            if touched:
                rep.say("همهٔ تغییراتِ این اجرا برمی‌گردد ...")
            run_.unwind()
            if touched & {"env", "inbox"} and not P.no_services and not a.no_restart:
                try:
                    reload_services(run_)
                except StepError:
                    pass
            rep.say("همه‌چیز مثلِ پیش از اجرا است." if touched else "چیزی عوض نشده بود.")
        return 1


def snapshot_original(P: Paths, rep: Reporter, state: dict) -> None:
    """پیش از اولین تغییر یک رونوشتِ کامل می‌گیرد (برای بازیابیِ اضطراری با دست)."""
    if state.get("snapshot_done"):
        return
    P.original_dir.mkdir(parents=True, exist_ok=True)
    for src, name in ((P.env_file, "backend.env"), (P.website_env, "website.env.production.local")):
        if src.exists():
            shutil.copy2(src, P.original_dir / name)
            os.chmod(P.original_dir / name, 0o600)
    state["snapshot_done"] = now_iso()
    rep.say(f"رونوشتِ پیش از تغییر: {P.original_dir}")


def install_vhost(run_: Run, target: Path, text: str, label: str) -> None:
    """vhost را می‌نویسد، nginx -t و reload (بی‌وقفه)؛ اگر خطا شد همان‌جا برمی‌گردد. هر فراخوانی نسخهٔ پیشینِ خودش را برای برگشت نگه می‌دارد."""
    P, rep = run_.P, run_.rep
    prev = read_text(target)
    if prev == text:
        rep.ok(f"{label}: از قبل همین است")
        return
    atomic_write(target, text, 0o644)

    def restore() -> None:
        if prev is None:
            target.unlink(missing_ok=True)
        else:
            atomic_write(target, prev, 0o644)
        nginx_reload(P)

    run_.on_undo(f"vhost ({target.name})", restore)
    ok, out = nginx_test(P)
    if not ok:
        raise StepError("nginx -t بعد از نوشتنِ vhost خطا داد:\n" + out[-500:])
    ok, out = nginx_reload(P)
    if not ok:
        raise StepError("reloadِ nginx نشد:\n" + out[-300:])
    run_.changed.add("vhost")
    rep.ok(f"{label} - nginx -t سالم، reload (بی‌وقفه) شد")


def done_msg(P: Paths, domain: str, aliases: list[str], ca: str, base: str, warnings: list[str]) -> None:
    print("\n" + "─" * 60)
    print(f"✓ تمام شد. NM الان روی {base} هم کار می‌کند" + (f" (و {aliases[0]} به آن می‌رسد)" if aliases else "") + ".")
    print(f"  • پنل: {base}/panel/       • سایتِ عمومی: {base}/")
    print(f"  • نشانیِ قدیمی (IP) هم کار می‌کند: http://{P.server_ip}:8040  (گره‌های پردازش همان را دارند)")
    if ca == "letsencrypt-staging":
        print("  • این گواهیِ آزمایشی است (مرورگر هشدار می‌دهد). برای گواهیِ واقعی همین دستور را بدونِ --staging بزنید.")
    if ca == "selfsigned":
        print("  • گواهیِ خودامضاست: فقط پشتِ CDN (حالتِ «بدونِ اعتبارسنجی») یا آزمون.")
    print("  • تمدیدِ گواهی خودکار است (certbot.timer)؛ وضعیت: nm-domain.sh --status")
    print("  • برگرداندن به حالتِ قبل: nm-domain.sh --rollback")
    if warnings:
        print(f"  ⚠ {len(warnings)} هشدارِ غیرحیاتی بالا ثبت شد.")


# ───────────────────────────────────────────────────────────── rollback
def cmd_rollback(P: Paths, a: argparse.Namespace) -> int:
    rep = Reporter(P.state_dir / "nm-domain.log")
    state = load_state(P)
    if not state:
        print("دامنه‌ای از طریقِ این ابزار تنظیم نشده؛ چیزی برای برگرداندن نیست.")
        return 0
    run_ = Run(P, a, rep)
    domain = state["domain"]
    print(f"nm-domain {VERSION} - برگرداندن: {domain}")
    try:
        rep.step("backend/.env")
        env_text = read_text(P.env_file) or ""
        prev = state.get("env_prev") or {}
        restored = env_restore(env_text, prev)
        if restored != env_text:
            atomic_write(P.env_file, restored)
            rep.ok("کلیدهای دامنه به مقدارِ پیشین برگشتند: " + "، ".join(prev))
        else:
            rep.ok("backend/.env از قبل مثلِ پیش از دامنه است")
        orig_env = read_text(P.original_dir / "backend.env")
        if orig_env is not None:
            rep.ok("فایل با رونوشتِ اصلی " + ("یکی است" if restored == orig_env else "فرق دارد (ویرایش‌های دیگرِ شما حفظ شد)"))

        rep.step("نشانی‌های ذخیره‌شده در دیتابیس (صندوق و دانشِ جذب مشتری)")
        db = Path(env_values(restored).get("SQLITE_PATH") or P.data / "db.sqlite3")
        for label, key, setter in (("صندوق", "inbox_prev", inbox_set), ("دانشِ جذب مشتری", "knowledge_prev", knowledge_set)):
            values = {int(i): old for i, old in (state.get(key) or {}).items()}
            if values and db.exists():
                setter(db, values)
                rep.ok(f"{label}: {len(values)} ردیف به مقدارِ پیشین برگشت")
            else:
                rep.ok(f"{label}: چیزی برای برگرداندن نبود")

        rep.step("env ِ سایتِ عمومی")
        web = state.get("website_env")
        if web:
            cur = read_text(P.website_env)
            if cur is not None:
                if web.get("existed"):
                    atomic_write(P.website_env, env_restore(cur, web.get("prev") or {}), 0o600)
                else:
                    P.website_env.unlink(missing_ok=True)
                rep.ok("برگشت")
        else:
            rep.ok("چیزی برای برگرداندن نبود")

        rep.step("vhostِ nginx")
        vh = Path(state.get("vhost") or P.vhost_file(domain))
        if vh.exists():
            keep = P.state_dir / "removed" / f"{vh.name}.{time.strftime('%Y%m%d-%H%M%S')}"
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(vh, keep)
            vh.unlink()
            ok, out = nginx_reload(P)
            (rep.ok if ok else rep.bad)(f"{vh.name} برداشته شد (نسخه: {keep}) و nginx بازخوانی شد" if ok else "nginx: " + out[-300:])
            if not ok:
                atomic_write(vh, read_text(keep) or "")
                raise StepError("با برداشتنِ vhost، nginx خطا داد؛ vhost را برگرداندم.")
        else:
            rep.ok("vhost از قبل نبود")

        rep.step("سرویس‌ها و سایتِ عمومی")
        reload_services(run_)
        if state.get("website_built_for") and not a.no_website and os.environ.get("NM_SKIP_WEBSITE_BUILD") != "1":
            ip_base = f"http://{state.get('server_ip', P.server_ip)}:8040"
            website_rebuild(run_, ip_base, swap=not P.no_services and P.conf == P.root)
        if not P.no_services:
            rc, out = hooks_command(P, "--rollback")
            rep.say(out.strip().splitlines()[-1] if out.strip() else "-")

        if a.purge_cert and state.get("ca") != "selfsigned":
            rc, out = run([P.certbot, "delete", "--cert-name", domain, "--non-interactive"], timeout=120)
            (rep.ok if rc == 0 else rep.warn)("گواهی هم پاک شد" if rc == 0 else out.strip()[-200:])
        stamp = time.strftime("%Y%m%d-%H%M%S")
        P.state_file.rename(P.state_dir / f"rolled-back-{stamp}.json")
        print("\n✓ برگشت. NM فقط روی نشانیِ IP است (http://%s:8040)." % state.get("server_ip", P.server_ip)
              + ("" if a.purge_cert else f" گواهیِ {domain} مانده تا هر وقت دوباره بخواهید (پاک‌کردن: --rollback --purge-cert)."))
        return 0
    except StepError as exc:
        rep.bad(str(exc))
        return 1


# ───────────────────────────────────────────────────────────── status / check-dns
def cmd_status(P: Paths, a: argparse.Namespace) -> int:
    state = load_state(P)
    out: dict = {"configured": bool(state), "server_ip": P.server_ip}
    if state:
        domain = state["domain"]
        cert_pem = Path(state["cert_dir"]) / ("fullchain.pem" if state["ca"] == "selfsigned" else "cert.pem")
        info = cert_info(cert_pem)
        out.update({"domain": domain, "canonical": state["canonical"], "ca": state["ca"], "applied_at": state["applied_at"],
                    "vhost": state["vhost"], "vhost_exists": Path(state["vhost"]).exists(), "cert": info,
                    "dns": dns_report(domain, P.server_ip)["status"]})
    if getattr(a, "json", False):
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    if not state:
        print(f"فقط با نشانیِ IP: http://{P.server_ip}:8040 - دامنه‌ای تنظیم نشده.")
        print("برای دامنه: docs/deploy/domain-fa.md  ·  دستور: nm-domain.sh <دامنه> --www")
        return 0
    print(f"دامنه: {out['domain']}  ({out['canonical']})   تنظیم‌شده: {out['applied_at']}")
    print(f"vhost: {out['vhost']} ({'هست' if out['vhost_exists'] else 'نیست!'})   DNS: {out['dns']}")
    c = out["cert"]
    if c:
        print(f"گواهی: {c['issuer']}  ·  انقضا {c['not_after']}  ·  {c['days_left']} روز مانده" + ("  ·  آزمایشی!" if c["staging"] else ""))
    else:
        print("گواهی: خوانده نشد")
    return 0


def cmd_check_dns(P: Paths, a: argparse.Namespace) -> int:
    try:
        domain, aliases = normalize_domain(a.check_dns, a.www)
    except DomainError as exc:
        print(f"✗ {exc}")
        return 2
    rc = 0
    for n in [domain, *aliases]:
        d = dns_report(n, P.server_ip)
        print(("✓ " if d["status"] == "ok" else "✗ ") + d["message"])
        for src, ips in d["a"].items():
            print(f"    {src:14s} {' '.join(ips) or '—'}")
        rc = rc or (0 if d["status"] == "ok" else 3)
    return rc


def cmd_watch(P: Paths, a: argparse.Namespace) -> int:
    """نگهبانِ روزانه (cron): گواهی کم‌مانده را دوباره تمدید می‌کند، نبودنِ vhost/گواهی و عوض‌شدنِ DNS را گزارش می‌دهد. یک خط خروجی؛ بی دامنه = بی‌صدا."""
    state = load_state(P)
    if not state:
        return 0
    domain = state["domain"]
    problems: list[str] = []
    vh = Path(state.get("vhost") or P.vhost_file(domain))
    if not vh.exists():
        problems.append(f"vhost ({vh.name}) نیست")
    pem = Path(state.get("cert_dir", "")) / ("fullchain.pem" if state.get("ca") == "selfsigned" else "cert.pem")
    cert = cert_info(pem)
    if cert is None:
        problems.append("گواهی خوانده نشد")
    elif state.get("ca") != "selfsigned" and cert["days_left"] <= 21 and Path(P.certbot).exists():
        # certbot.timer باید از ۳۰ روز مانده تمدید می‌کرد؛ اگر نشده، یک بار دستی (و بازخوانیِ nginx از هوکِ deploy)
        rc, out = run([P.certbot, "renew", "--cert-name", domain, "--no-random-sleep-on-renew"], timeout=420)
        nginx_reload(P)
        cert = cert_info(pem)
        if rc != 0 or cert is None or cert["days_left"] <= 21:
            problems.append("تمدیدِ گواهی شکست خورد: " + " ".join(out.strip()[-200:].split()))
    if cert and cert["days_left"] <= 14:
        problems.append(f"گواهی {cert['days_left']} روز دیگر منقضی می‌شود")
    d = dns_report(domain, P.server_ip)
    if d["status"] != "ok":
        problems.append("DNS: " + d["message"])
    days = cert["days_left"] if cert else "؟"
    print(f"{now_iso()} {domain}: گواهی {days} روز؛ DNS {d['status']}" + (" - ⚠ " + " | ".join(problems) if problems else " - سالم"), flush=True)
    return 1 if problems else 0


# ───────────────────────────────────────────────────────────── main
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="nm-domain.sh", description="NM را روی دامنه با HTTPS بنشان (ایده‌مپوتنت، با --dry-run و --rollback).")
    ap.add_argument("domain", nargs="?", help="مثل example.ir")
    ap.add_argument("--www", action="store_true", help="www.<دامنه> هم کار کند (به نشانیِ اصلی ریدایرکت می‌شود)")
    ap.add_argument("--dry-run", action="store_true", help="فقط برنامه را نشان بده")
    ap.add_argument("--status", action="store_true", help="وضعیتِ فعلی")
    ap.add_argument("--json", action="store_true", help="خروجیِ --status به‌صورتِ JSON")
    ap.add_argument("--check-dns", metavar="DOMAIN", help="فقط DNS را بسنج")
    ap.add_argument("--watch", action="store_true", help="نگهبانِ روزانه (cron): تمدیدِ گواهیِ کم‌مانده + گزارشِ یک‌خطی")
    ap.add_argument("--rollback", action="store_true", help="برگرداندن به حالتِ پیش از دامنه")
    ap.add_argument("--purge-cert", action="store_true", help="(با --rollback) گواهی را هم پاک کن")
    ap.add_argument("--staging", action="store_true", help="گواهیِ آزمایشیِ Let's Encrypt (مرورگر نمی‌پذیرد؛ برای آزمون)")
    ap.add_argument("--self-signed", action="store_true", help="گواهیِ خودامضا (پشتِ CDN یا آزمون؛ بی Let's Encrypt)")
    ap.add_argument("--email", help="ایمیلِ اعلانِ انقضا (اختیاری)")
    ap.add_argument("--skip-dns-check", action="store_true", help="سنجشِ DNS را رد کن (فقط آزمون/CDN)")
    ap.add_argument("--strict-hosts", action="store_true", help="ALLOWED_HOSTS را فهرستِ مشخص کن (به‌جای «*»)")
    ap.add_argument("--hsts", action="store_true", help="هدرِ HSTS (۶ ماه) - فقط وقتی مطمئنید دامنه همیشه https می‌ماند")
    ap.add_argument("--no-website", action="store_true", help="سایتِ عمومی (Next.js) را دست نزن/دوباره نساز")
    ap.add_argument("--no-restart", action="store_true", help="سرویس‌ها را بازنشانی نکن (بعداً: nm-reload)")
    ap.add_argument("--no-webhooks", action="store_true", help="وب‌هوک‌های ثبت‌شده را دوباره ثبت نکن")
    ap.add_argument("--force-renew", action="store_true", help="گواهی را حتی اگر معتبر است دوباره بگیر")
    ap.add_argument("--keep-on-failure", action="store_true", help="اگر خطا شد تغییرات را برنگردان (عیب‌یابی)")
    return ap


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    a = build_parser().parse_args(argv)
    P = Paths()
    if a.check_dns:
        return cmd_check_dns(P, a)
    if a.status:
        return cmd_status(P, a)
    if a.watch:
        return cmd_watch(P, a)
    if not a.rollback and not a.domain:
        build_parser().print_help()
        return 2
    P.lock.parent.mkdir(parents=True, exist_ok=True)
    with open(P.lock, "w") as lock_fh:
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("✗ یک اجرای دیگرِ nm-domain هم‌اکنون در جریان است؛ صبر کنید.")
            return 1
        return cmd_rollback(P, a) if a.rollback else cmd_apply(P, a)


if __name__ == "__main__":
    sys.exit(main())
