# -*- coding: utf-8 -*-
"""منطقِ خالصِ «دامنه + SSL» (فقط کتابخانهٔ استاندارد؛ بی جنگو) - هم ابزارِ خطِ فرمان (deploy/nm/nm_domain.py) و هم صفحهٔ «دامنه و SSL» ِ پنل از این می‌خوانند.

نامِ دامنه، DNS (dig)، خواندنِ گواهی (openssl)، ساختنِ vhostِ nginx، ویرایشِ .env و «نشانیِ عمومیِ سایتِ» صندوق.
"""
from __future__ import annotations

import datetime as dt
import re
import socket
import sqlite3
import subprocess
import os
from pathlib import Path

VERSION = "1.0"
#: نشانی‌هایی که خودمان گذاشته‌ایم (IP/لوکال)؛ فقط همین‌ها و خالی در «نشانیِ عمومی» ِ صندوق جایگزین می‌شوند، نه نشانیِ دلخواهِ مالک.
OLD_ADDRESS_RE = re.compile(r"^https?://(?:87\.107\.160\.17|127\.0\.0\.1|localhost)(?::\d+)?/?$", re.I)
BLOCK_BEGIN = "# >>> nm-domain.sh (خودکار؛ برگرداندن: nm-domain.sh --rollback) >>>"
BLOCK_END = "# <<< nm-domain.sh <<<"

_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_IPV4 = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


class DomainError(ValueError):
    """پیامش فارسی است و همان‌طور نمایش داده می‌شود."""


# ───────────────────────────────────────────────────────────── نامِ دامنه
def normalize_domain(raw: str, www: bool = False) -> tuple[str, list[str]]:
    """«https://Example.IR/» ⇒ ("example.ir", ["www.example.ir"]). نامِ نادرست ⇒ DomainError (فارسی)."""
    text = (raw or "").strip().lower()
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text)
    text = re.split(r"[/?#]", text, maxsplit=1)[0]
    if "@" in text:
        raise DomainError("فقط نامِ دامنه را بنویسید (بدونِ نامِ کاربری)، مثل example.ir")
    if ":" in text:
        raise DomainError("نامِ دامنه نباید پورت داشته باشد؛ دامنه روی پورت‌های استانداردِ 80 و 443 می‌آید. مثل example.ir")
    text = text.rstrip(".")
    if not text:
        raise DomainError("نامِ دامنه را بنویسید، مثل: nm-domain.sh example.ir --www")
    if "*" in text:
        raise DomainError("دامنهٔ ستاره‌دار (wildcard) پشتیبانی نمی‌شود؛ نامِ مشخص بنویسید.")
    try:
        text = text.encode("idna").decode("ascii")  # «دامنه.ir» ⇒ punycode
    except UnicodeError:
        raise DomainError("نامِ دامنه نامعتبر است؛ مثل example.ir بنویسید.") from None
    labels = text.split(".")
    if len(text) > 253 or len(labels) < 2:
        raise DomainError("نامِ دامنه باید پسوند داشته باشد، مثل example.ir")
    if _IPV4.match(text) or all(lb.isdigit() for lb in labels):
        raise DomainError("این یک نشانیِ IP است، نه دامنه. گواهیِ https برای IP صادر نمی‌شود؛ نامِ دامنه را بنویسید.")
    if any(not _LABEL.match(lb) for lb in labels):
        raise DomainError("نامِ دامنه نامعتبر است؛ فقط حرفِ انگلیسی، رقم و خط‌تیره (مثل example.ir).")
    if labels[-1] in ("local", "localhost", "invalid", "test", "example", "lan", "internal"):
        raise DomainError("این پسوند دامنهٔ عمومی نیست؛ دامنهٔ واقعی (مثل example.ir) لازم است.")
    aliases = [f"www.{text}"] if www and not text.startswith("www.") else []
    return text, aliases


def run(cmd: list[str], timeout: int = 60, env: dict | None = None) -> tuple[int, str]:
    """(کد، خروجیِ stdout+stderr). نبودنِ برنامه یا زمان‌گذشتن شکستِ عادی است، نه استثنا."""
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
                           env={**os.environ, **(env or {})}, check=False)
        return p.returncode, p.stdout.decode("utf-8", "replace")
    except FileNotFoundError:
        return 127, f"{cmd[0]}: پیدا نشد"
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.stdout or b"").decode("utf-8", "replace") + f"\n(بعد از {timeout} ثانیه قطع شد)"


# ───────────────────────────────────────────────────────────── DNS
def _ips(lines: list[str], v6: bool = False) -> list[str]:
    out = []
    for line in lines:
        line = line.strip()
        if (":" in line) if v6 else bool(_IPV4.match(line)):
            out.append(line)
    return sorted(set(out))


def dig(name: str, rtype: str, server: str | None = None) -> list[str]:
    cmd = ["dig", "+short", "+time=3", "+tries=1", rtype, name] + ([f"@{server}"] if server else [])
    rc, out = run(cmd, timeout=15)
    return [ln.strip() for ln in out.splitlines() if ln.strip()] if rc == 0 else []


def authoritative_servers(name: str) -> list[str]:
    labels = name.split(".")
    for i in range(len(labels) - 1):
        ns = dig(".".join(labels[i:]), "NS")
        if ns:
            return [n.rstrip(".") for n in ns if not n.startswith(";")]
    return []


def _fmt_sources(sources: dict[str, list[str]]) -> str:
    return "؛ ".join(f"{src}: {'، '.join(ips) if ips else '-'}" for src, ips in sources.items())


def dns_report(name: str, ip: str) -> dict:
    """{"name","status","a":{منبع: [..]},"aaaa":[..],"message"} - status: ok|missing|wrong|partial|aaaa."""
    sources: dict[str, list[str]] = {}
    try:
        sources["system"] = sorted({ai[4][0] for ai in socket.getaddrinfo(name, 80, socket.AF_INET)})
    except OSError:
        sources["system"] = []
    for resolver in ("1.1.1.1", "8.8.8.8"):
        sources[resolver] = _ips(dig(name, "A", resolver))
    ns = authoritative_servers(name)
    if ns:
        sources["authoritative"] = _ips(dig(name, "A", ns[0]))
    aaaa = sorted(set(_ips(dig(name, "AAAA"), v6=True) + _ips(dig(name, "AAAA", "1.1.1.1"), v6=True)))
    seen = sorted({a for ips in sources.values() for a in ips})
    answered = [s for s, ips in sources.items() if ips]
    rep = {"name": name, "a": sources, "aaaa": aaaa, "server_ip": ip, "found": seen}
    if aaaa:
        rep.update(status="aaaa", message=(
            f"«{name}» یک رکوردِ AAAA (آی‌پی نسخهٔ ۶: {'، '.join(aaaa)}) هم دارد. این سرور IPv6 ندارد و Let's Encrypt اول IPv6 را امتحان می‌کند؛ "
            "پس باید رکوردِ AAAA را از پنلِ DNS پاک کنید (فقط رکوردِ A بماند)."))
    elif not seen:
        rep.update(status="missing", message=(
            f"برای «{name}» هنوز رکوردِ A دیده نمی‌شود. در پنلِ DNS (ثبت‌کنندهٔ دامنه) یک رکوردِ A با مقدارِ {ip} بسازید "
            "و ۵ تا ۶۰ دقیقه (گاهی تا ۲۴ ساعت) صبر کنید؛ بعد دوباره اجرا کنید."))
    elif any(a != ip for a in seen) and ip not in seen:
        rep.update(status="wrong", message=(
            f"«{name}» به {'، '.join(seen)} اشاره می‌کند، نه به {ip}. رکوردِ A را به {ip} تغییر دهید "
            "(اگر CDN مثل کلودفلر/آروان با ابرِ نارنجی روشن است، تا صدورِ گواهی خاموشش کنید)."))
    elif any(a != ip for a in seen):
        rep.update(status="partial", message=(
            f"جواب‌های DNS برای «{name}» هنوز یکی نیست ({_fmt_sources(sources)}). "
            "احتمالاً DNS هنوز پخش می‌شود؛ ۱۰ تا ۶۰ دقیقه بعد دوباره امتحان کنید."))
    elif len(answered) < len(sources) and "authoritative" in sources and not sources["authoritative"]:
        rep.update(status="partial", message=(
            f"«{name}» از بعضی DNSها به {ip} می‌رسد، اما سرورِ اصلیِ DNS دامنه هنوز جواب نمی‌دهد؛ کمی صبر کنید و دوباره اجرا کنید."))
    else:
        rep.update(status="ok", message=f"«{name}» به {ip} اشاره می‌کند.")
    return rep


# ───────────────────────────────────────────────────────────── گواهی
def cert_info(pem: Path) -> dict | None:
    """{"not_after","days_left","issuer","names","staging","self_signed"} یا None."""
    if not pem.exists():
        return None
    rc, out = run(["openssl", "x509", "-noout", "-enddate", "-issuer", "-subject", "-ext", "subjectAltName", "-in", str(pem)], timeout=15)
    if rc != 0:
        rc, out = run(["openssl", "x509", "-noout", "-enddate", "-issuer", "-subject", "-text", "-in", str(pem)], timeout=15)
        if rc != 0:
            return None
    m = re.search(r"notAfter=(.+)", out)
    if not m:
        return None
    try:
        end = dt.datetime.strptime(m.group(1).strip().replace(" GMT", ""), "%b %d %H:%M:%S %Y").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    issuer = (re.search(r"issuer=(.+)", out) or [None, ""])[1].strip()
    subject = (re.search(r"subject=(.+)", out) or [None, ""])[1].strip()
    names = sorted(set(re.findall(r"DNS:([^,\s]+)", out)))
    days = (end - dt.datetime.now(dt.timezone.utc)).total_seconds() / 86400
    return {"not_after": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "days_left": int(days // 1), "issuer": issuer, "names": names,
            "staging": bool(re.search(r"STAGING|Fake LE", issuer, re.I)), "self_signed": bool(issuer and issuer == subject)}


# ───────────────────────────────────────────────────────────── vhost
#: همان بخش‌های port_8040.conf (پوشه‌ها با {root}). آزمونِ هم‌خوانی (tests_domain) یکی‌بودنِ این‌ها با آن فایل را می‌سنجد.
LOCATIONS = """\
    # ---- فایل‌های ایستا و رسانه
    location ^~ /static/ { alias {root}/backend/staticfiles/; expires 7d; access_log off; }
    location ^~ /media/  { alias {root}/backend/media/; expires 1d; }
    location ^~ /3d/files/ { alias {root}/data/up3d/; expires 1d; }

    # ---- پنلِ React زیرِ /panel/
    location = /panel { return 301 /panel/; }
    location /panel/ {
        alias {root}/frontend/dist/;
        try_files $uri $uri/ /panel/index.html;
        expires 1h;
    }
    location = /panel/index.html { alias {root}/frontend/dist/index.html; add_header Cache-Control "no-store"; }

    # ---- پیشرفتِ زندهٔ کار (SSE): بی‌بافر
    location ~ ^/api/v1/jobs/[0-9]+/stream/$ {
        proxy_pass http://127.0.0.1:8041;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 360s;
    }

    # ---- جنگو
    location ~ ^/(api|admin|studio|3d|compute|healthz|readyz|metrics)(/|$) {
        proxy_pass http://127.0.0.1:8041;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        proxy_request_buffering off;
    }

    # ---- سایتِ عمومی
    location / {
        proxy_pass http://127.0.0.1:3001;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
"""

SERVER_COMMON = """\
    server_tokens off;
    client_max_body_size 200m;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options SAMEORIGIN always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;
{hsts}
    gzip on;
    gzip_types text/plain text/css application/json application/javascript application/xml image/svg+xml;
    gzip_min_length 1024;
"""


def render_vhost(domain: str, aliases: list[str], *, phase: str, root: str, webroot: str, cert_dir: str | None,
                 logdir: str, hsts: bool = False) -> str:
    """phase "bootstrap": فقط 80 (چالشِ certbot + خودِ برنامه)؛ "final": 80 (چالش + ریدایرکت) و 443."""
    names = " ".join([domain, *aliases])
    hsts_line = '    add_header Strict-Transport-Security "max-age=15552000" always;\n' if hsts else ""
    common = SERVER_COMMON.replace("{hsts}\n", hsts_line)
    loc = LOCATIONS.replace("{root}", root)
    acme = f'    location ^~ /.well-known/acme-challenge/ {{ root {webroot}; default_type "text/plain"; allow all; }}\n'
    # پیشوندِ «nmdom-» تا logrotate با یک الگو (/www/wwwlogs/nmdom-*.log) بچرخاندشان و با nm-8040.log یکی نشود
    logs = f"    access_log {logdir}/nmdom-{domain}.log;\n    error_log  {logdir}/nmdom-{domain}.error.log;\n"
    head = (f"# NMarketing - دامنهٔ {domain}  (ساخته‌شده با nm-domain.sh {VERSION}؛ دستی ویرایش نکنید - دوباره اجرا کنید یا nm-domain.sh --rollback)\n"
            "# پورت 8040 (نشانیِ IP) جدا و دست‌نخورده می‌ماند: port_8040.conf\n"
            "# نامِ فایل با zz- شروع می‌شود تا tamouz.studio پیش‌فرضِ 443 بماند (مثلِ zz-chagher.conf).\n"
            "# گواهی: certbot webroot (تمدیدِ خودکار با certbot.timer + هوکِ بازخوانیِ nginx).\n\n")
    if phase == "bootstrap":
        return head + f"server {{\n    listen 80;\n    server_name {names};\n{common}{logs}{acme}\n{loc}}}\n"
    assert cert_dir, "cert_dir"
    out = head + (f"server {{\n    listen 80;\n    server_name {names};\n    server_tokens off;\n{logs}{acme}"
                  f"    location / {{ return 301 https://{domain}$request_uri; }}\n}}\n\n")
    out += (f"server {{\n    listen 443 ssl;\n    http2 on;\n    server_name {domain};\n"
            f"    ssl_certificate {cert_dir}/fullchain.pem;\n    ssl_certificate_key {cert_dir}/privkey.pem;\n"
            f"    ssl_protocols TLSv1.2 TLSv1.3;\n{common}{logs}\n{acme}\n{loc}}}\n")
    if aliases:
        out += (f"\nserver {{\n    listen 443 ssl;\n    http2 on;\n    server_name {' '.join(aliases)};\n"
                f"    ssl_certificate {cert_dir}/fullchain.pem;\n    ssl_certificate_key {cert_dir}/privkey.pem;\n"
                f"    ssl_protocols TLSv1.2 TLSv1.3;\n    server_tokens off;\n"
                f"    location / {{ return 301 https://{domain}$request_uri; }}\n}}\n")
    return out


# ───────────────────────────────────────────────────────────── .env
_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def env_values(text: str) -> dict[str, str]:
    """آخرین مقدارِ هر کلید (همان‌طور که python-dotenv می‌خواند)."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = _ENV_LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def merge_csv(current: str, add: list[str]) -> str:
    items = [x.strip() for x in (current or "").split(",") if x.strip()]
    for a in add:
        if a not in items:
            items.append(a)
    return ",".join(items)


def env_apply(text: str, updates: dict[str, str]) -> str:
    """کلیدهای موجود سرِ جای خودشان عوض می‌شوند؛ کلیدهای تازه در یک بلوکِ علامت‌دار می‌آیند. اجرای دوباره = همان متن."""
    lines = text.splitlines(keepends=True)
    seen: set[str] = set()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        m = _ENV_LINE.match(line)
        if m and m.group(1) in updates:
            key = m.group(1)
            lines[i] = f"{key}={updates[key]}\n"
            seen.add(key)
    missing = [k for k in updates if k not in seen]
    if missing:
        end = next((i for i, ln in enumerate(lines) if ln.strip() == BLOCK_END), None)
        new = [f"{k}={updates[k]}\n" for k in missing]
        if end is not None:
            lines[end:end] = new
        else:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            lines += ["\n", BLOCK_BEGIN + "\n", *new, BLOCK_END + "\n"]
    return "".join(lines)


def env_restore(text: str, prev: dict[str, str | None]) -> str:
    """برعکسِ env_apply: مقدارِ پیشین برمی‌گردد؛ کلیدی که پیش‌تر نبود حذف می‌شود (و بلوکِ خالی هم می‌رود)."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    for line in lines:
        m = None if line.lstrip().startswith("#") else _ENV_LINE.match(line)
        if m and m.group(1) in prev:
            old = prev[m.group(1)]
            if old is None:
                continue
            out.append(f"{m.group(1)}={old}\n")
        else:
            out.append(line)
    # بلوکِ خالی (فقط علامت‌ها) و یک خطِ خالیِ پیش از آن
    try:
        b = next(i for i, ln in enumerate(out) if ln.strip() == BLOCK_BEGIN)
        e = next(i for i, ln in enumerate(out) if ln.strip() == BLOCK_END)
        if e == b + 1:
            del out[b:e + 1]
            if b > 0 and out[b - 1].strip() == "":
                del out[b - 1]
    except StopIteration:
        pass
    return "".join(out)


def env_updates(cur: dict[str, str], domain: str, aliases: list[str], strict_hosts: bool, server_ip: str) -> dict[str, str]:
    base = f"https://{domain}"
    origins = [base] + [f"https://{a}" for a in aliases]
    hosts = [domain, *aliases]
    up = {
        "PUBLIC_BASE_URL": base,
        "PANEL_URL": base + "/panel",
        "PAYMENT_CALLBACK_BASE": base,
        "CSRF_TRUSTED_ORIGINS": merge_csv(cur.get("CSRF_TRUSTED_ORIGINS", ""), origins),
        # پشتِ nginx با TLS: بی این، جنگو خیال می‌کند http است و لینک‌ها/ویجت را http می‌سازد
        "USE_PROXY_SSL_HEADER": "true",
    }
    dj = cur.get("DJANGO_ALLOWED_HOSTS", "").strip()
    if dj and dj != "*":
        up["DJANGO_ALLOWED_HOSTS"] = merge_csv(dj, hosts)
    elif strict_hosts:
        legacy = cur.get("ALLOWED_HOSTS") or f"{server_ip},127.0.0.1,localhost"
        up["DJANGO_ALLOWED_HOSTS"] = merge_csv(legacy, hosts)
    if cur.get("ALLOWED_HOSTS") and "DJANGO_ALLOWED_HOSTS" not in up:
        up["ALLOWED_HOSTS"] = merge_csv(cur["ALLOWED_HOSTS"], hosts)
    return up


# ───────────────────────────────────────────────────────────── صندوق (نشانیِ عمومیِ سایت)
def url_plan(db: Path, table: str, col: str, new_url: str, previous: set[str], *, where: str = "", fill_empty: bool = True) -> tuple[list[tuple[int, str]], str]:
    """[(id, مقدارِ فعلی)] ردیف‌هایی که باید به new_url عوض شوند: نشانیِ IP/لوکال، دامنهٔ قبلیِ همین ابزار، و (اگر fill_empty) خالی.
    نشانیِ دلخواهِ مالک دست نمی‌خورد. (جدول/ستون ثابت‌های داخلی‌اند، نه ورودیِ کاربر.)"""
    if not db.exists():
        return [], "دیتابیس پیدا نشد"
    con = sqlite3.connect(str(db), timeout=30)
    try:
        try:
            rows = con.execute(f"SELECT id, {col} FROM {table}" + (f" WHERE {where}" if where else "")).fetchall()
        except sqlite3.OperationalError:
            return [], f"جدولِ {table} هنوز ساخته نشده"
    finally:
        con.close()
    todo = []
    for i, v in rows:
        v = v or ""
        if v == new_url:
            continue
        if (v == "" and fill_empty) or (v and OLD_ADDRESS_RE.match(v)) or v in previous:
            todo.append((i, v))
    return todo, ""


def url_set(db: Path, table: str, col: str, values: dict[int, str]) -> None:
    if not values:
        return
    con = sqlite3.connect(str(db), timeout=30)
    try:
        with con:
            for i, v in values.items():
                con.execute(f"UPDATE {table} SET {col} = ? WHERE id = ?", (v, i))
    finally:
        con.close()


def inbox_plan(db: Path, new_url: str, previous_urls: set[str]) -> tuple[list[tuple[int, str]], str]:
    """«نشانیِ عمومیِ سایت» ِ صندوق (InboxSettings.public_base_url، یک ردیف برای هر فروشگاه)."""
    return url_plan(db, "inbox_inboxsettings", "public_base_url", new_url, previous_urls)


def inbox_set(db: Path, values: dict[int, str]) -> None:
    url_set(db, "inbox_inboxsettings", "public_base_url", values)


def knowledge_plan(db: Path, new_url: str, previous_urls: set[str]) -> tuple[list[tuple[int, str]], str]:
    """دانشِ «جذب مشتری»: ردیفِ «سایتِ NMarketing» (seed_key='site') که در پیام‌های فروش به‌عنوانِ آدرسِ سایت می‌آید."""
    return url_plan(db, "growth_knowledge_knowledgeitem", "url", new_url, previous_urls, where="seed_key = 'site'", fill_empty=False)


def knowledge_set(db: Path, values: dict[int, str]) -> None:
    url_set(db, "growth_knowledge_knowledgeitem", "url", values)
