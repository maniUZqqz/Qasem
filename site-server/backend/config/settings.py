"""
UpMarket — Django settings.

All infrastructure values are environment-driven (see ../.env.example) so the
same codebase runs on the dev machine (no AI services) and on the main system
(Ollama + ComfyUI + Redis installed) without code changes.
"""
from datetime import timedelta
from pathlib import Path
import os
import sys

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
# `.env` is committed and travels between the two machines, so it cannot hold
# anything that differs BETWEEN them — the address of Ollama and of ComfyUI
# most of all. `.env.local` is per machine and never committed; it is read
# last and wins. Without it, one machine's addresses kept overwriting the
# other's on every pull.
load_dotenv(BASE_DIR / ".env.local", override=True)


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def prefer_ipv4_localhost(url: str) -> str:
    """Rewrite a `localhost` URL to 127.0.0.1.

    On Windows `localhost` resolves to ::1 first. Ollama, ComfyUI and Redis all
    bind IPv4 only, so every single call first waits ~2 seconds for the IPv6
    attempt to be refused — measured here: 3 requests to http://localhost:11434
    took 6.16s, the same 3 to http://127.0.0.1:11434 took 0.05s. A job makes
    several such calls, so this is seconds of pure waiting per action.

    Only the literal host `localhost` is rewritten; an explicit ::1 or a remote
    host is left exactly as configured.
    """
    from urllib.parse import urlsplit, urlunsplit

    try:
        parts = urlsplit(url)
        if (parts.hostname or "").lower() != "localhost":
            return url
        netloc = "127.0.0.1" if parts.port is None else f"127.0.0.1:{parts.port}"
        if parts.username:
            credentials = parts.username + (f":{parts.password}" if parts.password else "")
            netloc = f"{credentials}@{netloc}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except ValueError:
        return url


# ---------------------------------------------------------------- core
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-insecure-key-change-on-main-system")
DEBUG = env_bool("DJANGO_DEBUG", True)
if not DEBUG and SECRET_KEY == "dev-insecure-key-change-on-main-system":
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set to a long random value when DJANGO_DEBUG=false "
        "(JWTs are signed with it)."
    )
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "*")
if not DEBUG and ALLOWED_HOSTS == ["*"]:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS نمی‌تواند در production برابر * باشد — "
        "دامنه‌های واقعی را بنویسید."
    )

INSTALLED_APPS = [
    # پنل ادمینِ خودمان: همان ادمین جنگو، با نام و توضیح فارسی.
    # config/admin_site.py می‌گوید چرا.
    "config.admin_site.UpMarketAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "drf_spectacular",
    # UpMarket domains
    "apps.accounts",
    "apps.stores",
    "apps.products",
    "apps.jobs",
    "apps.ai",
    "apps.customers",
    "apps.content",
    "apps.campaigns",
    "apps.analytics",
    "apps.cms",
    "apps.billing",
    "apps.marketing",
    "apps.api_platform",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------- database
# SQLite for development, PostgreSQL for production.
#
# SQLite takes a single writer at a time. That is fine for one developer and
# fatal for the target architecture: hundreds of shops, Celery workers, and
# long-running jobs all writing at once. The capacity model sells 283
# concurrent customers, so the database has to survive them.
#
# Set DATABASE_URL and Postgres is used; leave it empty and SQLite is, with no
# other change anywhere. Migrations stay engine-agnostic either way.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if DATABASE_URL:
    from urllib.parse import unquote, urlparse

    _db = urlparse(DATABASE_URL)
    if _db.scheme not in ("postgres", "postgresql"):
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(
            f"DATABASE_URL scheme «{_db.scheme}» پشتیبانی نمی‌شود — postgres:// لازم است."
        )
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": (_db.path or "/upmarket").lstrip("/"),
            "USER": unquote(_db.username or ""),
            "PASSWORD": unquote(_db.password or ""),
            "HOST": _db.hostname or "127.0.0.1",
            "PORT": str(_db.port or 5432),
            # Reuse connections instead of opening one per request. Under
            # Celery + web workers this is the difference between a handful of
            # connections and hundreds.
            "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60")),
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": {
                "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "10")),
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": Path(os.getenv("SQLITE_PATH", BASE_DIR / "db.sqlite3")),
            "OPTIONS": {
                # WAL lets readers work while one writer holds the lock, and a
                # busy timeout turns "database is locked" into a short wait
                # rather than an instant error. Both only matter in dev, but
                # they make dev behave a little more like production.
                "init_command": "PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;",
            },
        }
    }

# Refuse to run production on SQLite. Getting this wrong is silent until the
# first concurrent write, and by then there are real customers on it.
if not DEBUG and not DATABASE_URL:
    import warnings

    warnings.warn(
        "DJANGO_DEBUG=false ولی DATABASE_URL تنظیم نشده — production روی SQLite "
        "اجرا می‌شود. برای PostgreSQL مقدار DATABASE_URL را بگذارید.",
        RuntimeWarning,
        stacklevel=2,
    )

# به خواستِ مالک (۱۴۰۵/۰۷/۲۳) هیچ قاعده‌ای برای سادگیِ رمز نیست: رمزِ کوتاه/عددی هم پذیرفته می‌شود
# (ثبت‌نام، بازیابیِ رمز و فرم‌های کاربر در جنگو ادمین همه از همین فهرست می‌خوانند).
AUTH_PASSWORD_VALIDATORS = []

# ---------------------------------------------------------------- i18n / static / media
# فارسی، چون کاربرِ این سیستم فارسی‌زبان است.
#
# این یک خط از هر تغییر دیگری در ادمین بیشتر اثر دارد: جنگو ترجمه‌ی کامل
# فارسیِ پنل ادمین را همراه خودش دارد، و «fa» یک زبان راست‌به‌چپ است، پس
# کل چیدمان هم خودبه‌خود برمی‌گردد. بدون این، نامِ فارسیِ مدل‌ها وسط
# دکمه‌های Add/Change و فیلترهای انگلیسی می‌نشست — همان «قاطی بودن»ی که
# در عمل آزاردهنده است.
LANGUAGE_CODE = "fa"
TIME_ZONE = os.getenv("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STATIC_ROOT = Path(os.getenv("STATIC_ROOT", BASE_DIR / "staticfiles"))
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", BASE_DIR / "media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Upload limits (uploads are untrusted input)
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_MB * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_MB * 1024 * 1024

# ---------------------------------------------------------------- production security
# Activated automatically when DJANGO_DEBUG=false on the deployment machine.
if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", False)
    CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", False)
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
    X_FRAME_OPTIONS = "DENY"

# ---------------------------------------------------------------- logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} [{name}] {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.request": {"level": "WARNING"},
        "services": {"level": "INFO"},
        "apps": {"level": "INFO"},
    },
}

# ---------------------------------------------------------------- DRF / auth
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # `Response(None)` must serialise to the JSON literal `null`; DRF's stock
    # renderer emits zero bytes, which is not parseable JSON (apps.common.renderers)
    "DEFAULT_RENDERER_CLASSES": [
        "apps.common.renderers.NullableJSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.getenv("THROTTLE_ANON", "30/minute"),
        "user": os.getenv("THROTTLE_USER", "240/minute"),
        # The public contact form is the only anonymous write endpoint we have.
        # A person sends one message; anything near this ceiling is a script.
        "lead": os.getenv("THROTTLE_LEAD", "5/hour"),
        # Analytics is batched, so a real visit is a handful of requests.
        "event": os.getenv("THROTTLE_EVENT", "120/hour"),
        # Password reset. Tight on purpose: each request sends a real email to
        # someone who did not necessarily ask for it, so an unthrottled
        # endpoint is a way to harass a shop owner's inbox from the outside.
        "password_reset": os.getenv("THROTTLE_PASSWORD_RESET", "5/hour"),
        # The public API. Separate from the monthly allowance: that stops a
        # shop spending more GPU than they paid for, this stops a loop in
        # their code spending all of it in ten seconds.
        "public_api": os.getenv("THROTTLE_PUBLIC_API", "60/minute"),
        # A public endpoint that says whether a string is a real code is
        # an oracle; this is what stops it being enumerated at speed.
        "code_check": os.getenv("THROTTLE_CODE_CHECK", "20/minute"),
    },
}

# Throttling off during automated tests (rate limits would make them flaky)
IS_TEST = "test" in sys.argv
if IS_TEST:
    REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=12),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "UpMarket API",
    "DESCRIPTION": "AI Sales & Marketing Employee for online stores",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # schema/docs are public in dev, authenticated-only in production
    "SERVE_PERMISSIONS": (
        ["rest_framework.permissions.AllowAny"]
        if DEBUG
        else ["rest_framework.permissions.IsAuthenticated"]
    ),
}

# ---------------------------------------------------------------- CORS
# Note: the vite dev server proxies /api same-origin, so CORS is only relevant
# when the frontend is served from a different origin.
_cors_origins = env_list("CORS_ALLOWED_ORIGINS")
if _cors_origins:
    CORS_ALLOWED_ORIGINS = _cors_origins
    CORS_ALLOW_CREDENTIALS = True
else:
    # dev convenience only; credentials stay off with a wildcard origin
    CORS_ALLOW_ALL_ORIGINS = DEBUG

# Behind a TLS-terminating proxy Django sees plain HTTP, so it rejects admin
# POSTs whose Origin says https unless the origin is listed here. Symptom is a
# 403 on login that looks like a wrong password.
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# Trust the proxy's protocol header so `request.is_secure()` is right; without
# it secure cookies are never set and an SSL redirect loops.
if env_bool("USE_PROXY_SSL_HEADER", not DEBUG):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ---------------------------------------------------------------- Celery / Redis
# CELERY_BROKER_URL is what compose sets and what Celery's own docs use;
# REDIS_URL is kept because start.bat and the dev machine already use it.
# Reading only one of the two meant the deployed workers silently fell back to
# localhost and found no broker.
CELERY_BROKER_URL = prefer_ipv4_localhost(
    os.getenv("CELERY_BROKER_URL")
    or os.getenv("REDIS_URL")
    or "redis://127.0.0.1:6379/0"
)
CELERY_RESULT_BACKEND = prefer_ipv4_localhost(
    os.getenv("CELERY_RESULT_BACKEND") or CELERY_BROKER_URL
)

# ---- scheduled work ------------------------------------------------------
# One beat, asking "what is due?" every minute.
#
# Celery can schedule a task for a future moment and it is the wrong tool here:
# a worker restart loses every pending eta, and these workers restart routinely
# because they share one GPU. A scan over rows survives anything that can be
# restarted.
CELERY_BEAT_SCHEDULE = {
    "publish-scheduled-posts": {
        "task": "apps.campaigns.tasks.run_scheduled_publishes",
        "schedule": float(os.getenv("SCHEDULE_TICK_SECONDS", "60")),
        # Do not pile up: if the beat was down for an hour, one run catches up.
        "options": {"expires": 120},
    },
    "release-expired-reservations": {
        "task": "apps.customers.tasks.release_expired_reservations",
        "schedule": float(os.getenv("RESERVATION_TICK_SECONDS", "900")),
        "options": {"expires": 600},
    },
    "collect-post-performance": {
        "task": "apps.campaigns.tasks.collect_performance",
        "schedule": float(os.getenv("PERFORMANCE_TICK_SECONDS", "3600")),
        "options": {"expires": 1800},
    },
}


def _redis_is_up(url: str, timeout: float = 0.6) -> bool:
    """One TCP connect to the broker. Never raises."""
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url or "")
    try:
        with socket.create_connection(
            (parsed.hostname or "localhost", parsed.port or 6379), timeout=timeout
        ):
            return True
    except OSError:
        return False


# CELERY_TASK_ALWAYS_EAGER=auto (the default) picks the mode by looking at the
# machine instead of making the user edit .env: Redis up → real queue (video
# generation works); Redis down → run AI jobs inside the request so everything
# else still works. `true`/`false` still force a mode. (beter.md v2 #5)
_EAGER_RAW = os.getenv("CELERY_TASK_ALWAYS_EAGER", "auto").strip().lower()
if _EAGER_RAW in {"", "auto"}:
    CELERY_TASK_ALWAYS_EAGER = not _redis_is_up(CELERY_BROKER_URL)
    CELERY_MODE_SOURCE = "auto"
else:
    CELERY_TASK_ALWAYS_EAGER = _EAGER_RAW in {"1", "true", "yes", "on"}
    CELERY_MODE_SOURCE = "env"

if IS_TEST:  # tests must never depend on a Redis being up on the dev machine
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_MODE_SOURCE = "test"
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
# AI (Ollama) work and GPU (ComfyUI) work run on dedicated queues so heavy
# generation can be capped independently (GPU_CONCURRENCY_LIMIT).
CELERY_TASK_ROUTES = {
    "apps.content.tasks.generate_video_task": {"queue": "gpu"},
    "apps.content.tasks.generate_image_task": {"queue": "gpu"},
    "apps.ai.tasks.*": {"queue": "ai"},
    "apps.content.tasks.*": {"queue": "ai"},
    "apps.campaigns.tasks.*": {"queue": "ai"},
}

# ---------------------------------------------------------------- payments
# Gateway credentials. With none of these set the product still runs: the only
# offered method is a bank transfer a human confirms, which is what the
# business does today.
UPMARKET_PAYMENT = {
    "ZARINPAL_MERCHANT_ID": os.getenv("ZARINPAL_MERCHANT_ID", ""),
    "ZARINPAL_SANDBOX": env_bool("ZARINPAL_SANDBOX", False),
    "MANUAL_ACCOUNT_INFO": os.getenv("MANUAL_ACCOUNT_INFO", ""),
    "DEFAULT_PROVIDER": os.getenv("PAYMENT_DEFAULT_PROVIDER", ""),
    "PERIOD_DAYS": int(os.getenv("BILLING_PERIOD_DAYS", "30")),
    # Days a lapsed subscription keeps working. Cutting someone off the moment
    # a renewal fails loses customers whose card simply expired.
    "GRACE_DAYS": int(os.getenv("BILLING_GRACE_DAYS", "3")),
    # Where the gateway sends the browser back to.
    "CALLBACK_BASE": os.getenv("PAYMENT_CALLBACK_BASE", "http://127.0.0.1:8000"),
    "PANEL_URL": os.getenv("PANEL_URL", "http://127.0.0.1:5173"),
}

# ---------------------------------------------------------------- UpMarket AI stack
UPMARKET_AI = {
    # --- API mode ------------------------------------------------------
    # Setting AI_API_BASE_URL flips text+vision from the local Ollama box to
    # any OpenAI-compatible API (Metis, AvalAI, Liara, OpenAI itself). This is
    # the .env shortcut for what ModelProvider rows already do in the admin —
    # so a machine with no GPU can run the whole product. Admin rows still win
    # when they exist; this only replaces the built-in default.
    "AI_API_BASE_URL": os.getenv("AI_API_BASE_URL", "").rstrip("/"),
    "AI_API_KEY": os.getenv("AI_API_KEY", ""),
    "AI_API_MODEL_TEXT": os.getenv("AI_API_MODEL_TEXT", "gpt-4o-mini"),
    "AI_API_MODEL_VISION": os.getenv("AI_API_MODEL_VISION", "gpt-4o-mini"),
    "AI_API_TIMEOUT": int(os.getenv("AI_API_TIMEOUT", "180")),
    # Per-capability choice: local hardware, or an API. The launcher asks once
    # and writes these, so choosing an API for video alone does not stop Ollama
    # and choosing one for text alone does not stop ComfyUI.
    "AI_MODE_TEXT": os.getenv("AI_MODE_TEXT", ""),
    "AI_MODE_IMAGE": os.getenv("AI_MODE_IMAGE", ""),
    "AI_MODE_VIDEO": os.getenv("AI_MODE_VIDEO", ""),
    # Image/video over an API (Replicate-style). Without a token, "api" for
    # these falls back to local rather than leaving the product unable to
    # render with no error until the first job.
    "MEDIA_API_BASE_URL": os.getenv("MEDIA_API_BASE_URL", "https://api.replicate.com/v1/predictions"),
    "MEDIA_API_TOKEN": os.getenv("MEDIA_API_TOKEN", ""),
    "MEDIA_API_MODEL_IMAGE": os.getenv("MEDIA_API_MODEL_IMAGE", ""),
    "MEDIA_API_MODEL_VIDEO": os.getenv("MEDIA_API_MODEL_VIDEO", ""),
    "MEDIA_API_TIMEOUT": int(os.getenv("MEDIA_API_TIMEOUT", "900")),
    # Data policy for stores that have not chosen one (apps.ai.StoreAIPolicy).
    # HYBRID = any active provider may answer, which is how every install
    # behaved before the policy layer existed. An operator who promises local
    # processing to every customer sets LOCAL_ONLY here and means it.
    "AI_DEFAULT_POLICY": os.getenv("AI_DEFAULT_POLICY", "HYBRID").upper(),
    # Quality guarantee: how many goes at one output before it stops being
    # charged for (apps.billing.credits). One miss is luck, two a coincidence,
    # three means the model cannot do this job today.
    "QUALITY_MAX_ATTEMPTS": int(os.getenv("QUALITY_MAX_ATTEMPTS", "3")),
    # Auto mode pauses on the QC VERDICT (REVIEW or REGENERATE, i.e. below
    # QC_REVIEW). This older fraction is kept only as an extra floor for
    # deployments that set it explicitly; the verdict is what decides.
    "QUALITY_PAUSE_THRESHOLD": float(os.getenv("QUALITY_PAUSE_THRESHOLD", "0.7")),
    # How many renders one segment may take inside a single Auto run before
    # the best of them is kept and a person is asked. Each extra attempt is a
    # full Wan render; the quality guarantee (QUALITY_MAX_ATTEMPTS) caps the
    # chain across runs and makes the last one free.
    "SEGMENT_AUTO_ATTEMPTS": int(os.getenv("SEGMENT_AUTO_ATTEMPTS", "2")),
    # Vision QC verdict boundaries (services.video.qc). ROADMAP §9.2 calls these
    # "نمونه" — they are placeholders until phase 0.5 runs real renders and the
    # thresholds are calibrated against output someone actually judged.
    "QC_EXCELLENT": float(os.getenv("QC_EXCELLENT", "90")),
    "QC_GOOD": float(os.getenv("QC_GOOD", "80")),
    "QC_REVIEW": float(os.getenv("QC_REVIEW", "70")),
    # Live-progress streams held open per gunicorn process. Each one occupies a
    # worker thread for its whole life, so this must stay well under the thread
    # count or watching a render would starve every other request.
    "MAX_SSE_STREAMS": int(os.getenv("MAX_SSE_STREAMS", "4")),
    # ---- channel credentials (services.publishing.channels) ---------------
    # Each channel names what it needs; a missing value means that channel is
    # off and the inbox says which key is missing, rather than showing a
    # generic "unavailable" the shop cannot act on.
    "TELEGRAM_BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN", ""),
    "WHATSAPP_TOKEN": os.getenv("WHATSAPP_TOKEN", ""),
    "WHATSAPP_PHONE_ID": os.getenv("WHATSAPP_PHONE_ID", ""),
    # --- receiving from Meta (Instagram DMs, WhatsApp) -------------------
    # Separate from the sending tokens above on purpose: a shop can publish to
    # Instagram through NovinHub long before the app is approved to *read*
    # DMs, and collapsing the two would switch off a working publisher.
    #
    # APP_SECRET signs every delivery — without it an unsigned payload is
    # refused rather than trusted. VERIFY_TOKEN is the one Meta echoes back
    # during the subscription handshake.
    "META_APP_SECRET": os.getenv("META_APP_SECRET", ""),
    "META_VERIFY_TOKEN": os.getenv("META_VERIFY_TOKEN", ""),
    "SMS_API_KEY": os.getenv("SMS_API_KEY", ""),
    # --- the public marketing site ---------------------------------------
    # Where the Next.js site is, so a change in the Django admin can tell it
    # to drop the page it has cached (apps/cms/revalidate.py). Without the
    # secret the site refuses the request, and an edit then takes up to two
    # minutes to show — which reads to the person who made it as "the site
    # is not connected to the admin at all".
    "WEBSITE_URL": os.getenv("WEBSITE_URL", "http://127.0.0.1:3001"),
    "WEBSITE_REVALIDATE_SECRET": os.getenv("WEBSITE_REVALIDATE_SECRET", ""),
    "OLLAMA_BASE_URL": prefer_ipv4_localhost(
        os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    ),
    # cold call on the main system = model load from disk (1-3 min) + long
    # generation; 180 timed out intermittently (beter.md #2)
    "OLLAMA_TIMEOUT": int(os.getenv("OLLAMA_TIMEOUT", "600")),
    "OLLAMA_RETRIES": int(os.getenv("OLLAMA_RETRIES", "2")),
    "MODEL_REASONING": os.getenv("OLLAMA_MODEL_REASONING", "qwq:32b"),
    "MODEL_VISION": os.getenv("OLLAMA_MODEL_VISION", "qwen3-vl:30b"),
    "MODEL_CODER": os.getenv("OLLAMA_MODEL_CODER", "qwen3-coder:30b"),
    # tried in order when the preferred model is not installed or fails; any
    # name not actually pulled on the machine is skipped automatically
    "MODEL_FALLBACKS": env_list(
        "OLLAMA_MODEL_FALLBACKS",
        ",".join(
            [
                os.getenv("OLLAMA_MODEL_VISION", "qwen3-vl:30b"),
                os.getenv("OLLAMA_MODEL_CODER", "qwen3-coder:30b"),
            ]
        ),
    ),
    # false = fail on the first model instead of trying the next one
    "MODEL_FALLBACK_ENABLED": env_bool("OLLAMA_MODEL_FALLBACK", True),
    # how many models one call may try in total. 2 keeps the worst case at
    # roughly twice a timeout — a live sales chat must not spend half an hour
    # walking down the model list.
    "MODEL_MAX_ATTEMPTS": max(1, int(os.getenv("OLLAMA_MODEL_MAX_ATTEMPTS", "2"))),
    # How long Ollama keeps a model in VRAM after a call. VRAM safety comes
    # from explicitly evicting the OTHER models before heavy work (services.gpu),
    # so this can stay at Ollama's own 5m default: a shorter value would force
    # an 18 GB reload from disk (1-3 min) between two steps of the same demo.
    "OLLAMA_KEEP_ALIVE": os.getenv("OLLAMA_KEEP_ALIVE", "5m"),
    # context window per request; smaller = less KV cache = more room for
    # weights on the GPU. 0 = let Ollama decide.
    "OLLAMA_NUM_CTX": int(os.getenv("OLLAMA_NUM_CTX", "8192")),
    # Generation cap for JSON answers. A market analysis with competitors is a
    # genuinely long object: cutting this too low truncates the JSON and the
    # answer fails validation, which is far worse than the extra seconds.
    "OLLAMA_NUM_PREDICT_JSON": int(os.getenv("OLLAMA_NUM_PREDICT_JSON", "4096")),
    "COMFYUI_BASE_URL": prefer_ipv4_localhost(
        os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
    ),
    "COMFYUI_TIMEOUT": int(os.getenv("COMFYUI_TIMEOUT", "900")),
    "COMFYUI_POLL_INTERVAL": float(os.getenv("COMFYUI_POLL_INTERVAL", "2.0")),
    # Lip-sync for scenes where the person speaks the narration to camera
    # (services/video/lipsync.py, LatentSync 1.6 on ComfyUI). Only scenes the
    # shop marks «گوینده در تصویر» are touched.
    "LIPSYNC_ENABLED": os.getenv("LIPSYNC_ENABLED", "1") not in ("0", "false", "False"),
    # Move each scene's narration so the product's name is said when the
    # product appears on screen (services/audio/timing.py).
    "NARRATION_FOLLOWS_PRODUCT": os.getenv("NARRATION_FOLLOWS_PRODUCT", "1") not in ("0", "false", "False"),
    "LIPSYNC_STEPS": int(os.getenv("LIPSYNC_STEPS", "20")),
    "LIPSYNC_LIPS_EXPRESSION": float(os.getenv("LIPSYNC_LIPS_EXPRESSION", "1.5")),
    "VIDEO_SEGMENT_DURATION": int(os.getenv("VIDEO_SEGMENT_DURATION", "5")),
    # --- finishing pass on every generated video (services/video/enhance.py)
    # Runs on THIS server with ffmpeg, so it works with the GPU node offline:
    # 16→32 fps motion interpolation, 480p→720p lanczos, light denoise and
    # deband, contrast-adaptive sharpening, x264 CRF 18. Off in tests (the
    # suite renders fake files); VIDEO_ENHANCE=0 turns it off here too.
    "VIDEO_ENHANCE": env_bool("VIDEO_ENHANCE", not IS_TEST),
    "VIDEO_ENHANCE_FPS": int(os.getenv("VIDEO_ENHANCE_FPS", "32")),
    # mci (motion-compensated, ~22 s per 5 s segment on 2 free cores) | blend | off
    "VIDEO_ENHANCE_INTERPOLATION": os.getenv("VIDEO_ENHANCE_INTERPOLATION", "mci"),
    "VIDEO_ENHANCE_SHORT_SIDE": int(os.getenv("VIDEO_ENHANCE_SHORT_SIDE", "720")),
    "VIDEO_ENHANCE_LONG_SIDE": int(os.getenv("VIDEO_ENHANCE_LONG_SIDE", "1280")),
    "VIDEO_ENHANCE_SHARPEN": float(os.getenv("VIDEO_ENHANCE_SHARPEN", "0.45")),
    "VIDEO_ENHANCE_DENOISE": os.getenv("VIDEO_ENHANCE_DENOISE", "1.5:1.5:4:4"),
    "VIDEO_ENHANCE_DEBAND": env_bool("VIDEO_ENHANCE_DEBAND", True),
    "VIDEO_ENHANCE_CRF": int(os.getenv("VIDEO_ENHANCE_CRF", "18")),
    # medium, not slow: on these 2 shared cores slow saved ~2% size at CRF 18
    "VIDEO_ENHANCE_PRESET": os.getenv("VIDEO_ENHANCE_PRESET", "medium"),
    "VIDEO_ENHANCE_NICE": int(os.getenv("VIDEO_ENHANCE_NICE", "10")),
    # After the video is stitched, voice it automatically (narration +
    # ambience/effects + the shop's music if set) — the shop should not have
    # to find a second button to get sound. Off in tests (no TTS there).
    "VIDEO_AUTO_VOICE": env_bool("VIDEO_AUTO_VOICE", not IS_TEST),
    "GPU_CONCURRENCY_LIMIT": int(os.getenv("GPU_CONCURRENCY_LIMIT", "1")),
    # single-GPU VRAM coordination: unload Ollama models before ComfyUI work
    # and free ComfyUI VRAM before/after heavy Ollama work (best-effort)
    "GPU_AUTO_UNLOAD": env_bool("GPU_AUTO_UNLOAD", True),
    # Which voice / ambience / noise-removal engine is used is chosen in the
    # admin («موتورهای صدا», apps.ai.AudioEngine). TTS_PROVIDER only decides the
    # order on an install whose engine table is still empty.
    "TTS_PROVIDER": os.getenv("TTS_PROVIDER", "edge"),
    # Where downloaded offline engines live (Piper voices, DeepFilterNet).
    # Empty = Code/UpMarket/models. `manage.py audio_setup` fills it.
    "AUDIO_MODELS_DIR": os.getenv("AUDIO_MODELS_DIR", ""),
    "DEEPFILTER_BIN": os.getenv("DEEPFILTER_BIN", ""),
    # --- speech to text ------------------------------------------------
    # Whisper runs on our own box, unlike the voice engine. That asymmetry is
    # worth knowing: a `Local Only` shop cannot generate narration (edge-tts is
    # Microsoft's) but *can* subtitle the video they filmed themselves.
    "WHISPER_MODEL": os.getenv("WHISPER_MODEL", "small"),
    "WHISPER_DEVICE": os.getenv("WHISPER_DEVICE", "auto"),
    "TTS_VOICE": os.getenv("TTS_VOICE", "fa-IR-FaridNeural"),
    "TTS_LANGUAGE": os.getenv("TTS_LANGUAGE", "fa"),
    # per-narration-language voices (edge-tts voice names)
    "TTS_VOICE_FA": os.getenv("TTS_VOICE_FA", os.getenv("TTS_VOICE", "fa-IR-FaridNeural")),
    "TTS_VOICE_EN": os.getenv("TTS_VOICE_EN", "en-US-ChristopherNeural"),
    # semantic product search — OFF until an embedding model is installed on
    # the main system; everything falls back to keyword retrieval when off
    "EMBEDDINGS_ENABLED": env_bool("EMBEDDINGS_ENABLED", False),
    "MODEL_EMBEDDING": os.getenv("OLLAMA_MODEL_EMBEDDING", "nomic-embed-text"),
}

# ---------------------------------------------------------------- web research
# General web search for competitor sites — proper, non-blocking providers only:
#   searxng = self-hosted metasearch (recommended; your own instance, never blocked)
#   brave   = official Brave Search API (free-tier key)
#   none    = marketplace sources only (Digikala/Torob)
UPMARKET_RESEARCH = {
    "WEB_SEARCH_PROVIDER": os.getenv("WEB_SEARCH_PROVIDER", "none").lower(),
    "SEARXNG_BASE_URL": prefer_ipv4_localhost(
        os.getenv("SEARXNG_BASE_URL", "http://127.0.0.1:8888")
    ).rstrip("/"),
    "BRAVE_API_KEY": os.getenv("BRAVE_API_KEY", ""),
}

# ---------------------------------------------------------------- publishing (n8n)
UPMARKET_PUBLISHING = {
    # NovinHub — managed Instagram publishing (https://novinhub.com/developers).
    # A per-store token on StoreProfile overrides this shared one.
    "NOVINHUB_BASE_URL": os.getenv("NOVINHUB_BASE_URL", "https://api.novinhub.com/token/v2"),
    "NOVINHUB_TOKEN": os.getenv("NOVINHUB_TOKEN", ""),
    "N8N_WEBHOOK_URL": os.getenv("N8N_WEBHOOK_URL", ""),
    "N8N_WEBHOOK_TOKEN": os.getenv("N8N_WEBHOOK_TOKEN", ""),
    # used to build absolute media URLs inside webhook payloads
    "PUBLIC_BASE_URL": os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
}


# ---------------------------------------------------------------- email
#
# There is exactly one thing email is used for: letting someone who forgot
# their password back in. That makes it load-bearing rather than optional —
# without it, every lost password becomes a support message to the founders.
#
# The default backend prints the message to the console instead of sending it.
# That is right for development and **wrong for production**, so the guard
# below refuses to start if nothing is configured and DEBUG is off: a silently
# discarded reset email is worse than a server that will not boot, because the
# customer sees "we sent you a link" and waits.

EMAIL_HOST = os.getenv("EMAIL_HOST", "").strip()
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "true").lower() in ("1", "true", "yes")
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "false").lower() in ("1", "true", "yes")
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "20"))
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "no-reply@nmarketing.ir")

if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

#: How long a reset link stays usable. Three days is Django's default and is
#: too generous for a link that can take over an account; one day still covers
#: "I asked at midnight and read my email after work".
PASSWORD_RESET_TIMEOUT = int(os.getenv("PASSWORD_RESET_TIMEOUT", str(60 * 60 * 24)))

if not DEBUG and not EMAIL_HOST and not IS_TEST:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "EMAIL_HOST تنظیم نشده است. بدون آن، ایمیل بازیابی رمز فقط در لاگ سرور "
        "چاپ می‌شود و هیچ‌وقت به دست کاربر نمی‌رسد — یعنی هر کسی رمزش را گم کند "
        "باید دستی با شما تماس بگیرد. مقادیر EMAIL_* را در .env پر کنید."
    )


# ---------------------------------------------------------------- media storage
#
# Files live on a local volume by default and that is right for development.
# It stops being right the moment there is more than one machine, or a deploy
# that replaces a container: a volume is not shared, and a rendered video the
# shop is about to publish is on exactly one box.
#
# Phase 23 (the editing engine) is what made this urgent — uploaded source
# video is now first-class data, not a by-product we can regenerate.
#
# S3-compatible rather than AWS-specific, because the realistic providers here
# are Iranian (ArvanCloud, Liara) and MinIO for a self-hosted box. All three
# speak the same protocol.
MEDIA_STORAGE = os.getenv("MEDIA_STORAGE", "local").lower()

if MEDIA_STORAGE == "s3":
    try:
        import storages  # noqa: F401
    except ImportError as exc:  # pragma: no cover - deployment guard
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(
            "MEDIA_STORAGE=s3 است ولی django-storages نصب نیست. "
            "یا `pip install django-storages[s3]` را بزنید یا MEDIA_STORAGE را "
            "به local برگردانید. اگر بی‌صدا رد می‌شدیم، سرور فایل‌ها را روی "
            "ولوم کانتینر می‌نوشت و اولین دیپلوی بعدی همه‌ی ویدیوهای رندرشده "
            "را با خودش می‌برد."
        ) from exc

    _s3 = {
        "bucket_name": os.getenv("S3_BUCKET", ""),
        "endpoint_url": os.getenv("S3_ENDPOINT_URL", ""),
        "access_key": os.getenv("S3_ACCESS_KEY", ""),
        "secret_key": os.getenv("S3_SECRET_KEY", ""),
        "region_name": os.getenv("S3_REGION", ""),
        # Private by default. A bucket of customer product photos and unreleased
        # campaign videos is not a public directory, and "we will lock it down
        # later" has never once happened.
        "default_acl": os.getenv("S3_ACL", "private"),
        "querystring_auth": os.getenv("S3_SIGNED_URLS", "true").lower() == "true",
        "file_overwrite": False,
    }
    _missing = [k for k in ("bucket_name", "access_key", "secret_key") if not _s3[k]]
    if _missing and not IS_TEST:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(
            f"MEDIA_STORAGE=s3 است ولی این‌ها خالی‌اند: {', '.join(_missing)}. "
            "S3_BUCKET، S3_ACCESS_KEY و S3_SECRET_KEY را در .env پر کنید."
        )

    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3.S3Storage", "OPTIONS": _s3},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
elif MEDIA_STORAGE != "local":
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        f"MEDIA_STORAGE='{MEDIA_STORAGE}' را نمی‌شناسیم — local یا s3."
    )

#: Whether media is somewhere every worker can reach. Read by the health
#: endpoint and by anything that hands a local path to ffmpeg: those callers
#: need a real file on disk, and on S3 they have to fetch it first.
MEDIA_IS_SHARED = MEDIA_STORAGE != "local"


# =====================================================================
# NMarketing — ابزارهای ادغام‌شده: سرورهای پردازش (apps.compute)،
# سایت‌ساز (apps.projects و دوستانش، دیتابیسِ جدا) و ویدیوی سه‌بعدی (apps.up3d)
# =====================================================================
import sys as _sys

NM_DATA_DIR = Path(os.getenv("NM_DATA_DIR", BASE_DIR / "data"))
NM_DATA_DIR.mkdir(parents=True, exist_ok=True)
NM_COMPUTE_DEDUPE_HOURS = int(os.getenv("NM_COMPUTE_DEDUPE_HOURS", "72"))
NM_COMPUTE_TIMEOUT = int(os.getenv("NM_COMPUTE_TIMEOUT", "1800"))

INSTALLED_APPS += [
    "django.contrib.humanize",
    "rest_framework.authtoken",
    "apps.compute",
    "apps.panel",
    "apps.up3d",
    "apps.projects",
    "apps.code_generation",
    "apps.template_editor",
    "apps.ai_engine",
    "apps.project_importer",
]
REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"].append("rest_framework.authentication.TokenAuthentication")
LOGIN_URL = "/admin/login/"
DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024

# --- سایت‌ساز (studio): دیتابیسِ خودش + کارگاه‌های پروژه‌ها
DATABASES["studio"] = {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": Path(os.getenv("STUDIO_DB", NM_DATA_DIR / "studio.sqlite3")),
    "OPTIONS": {"timeout": 30, "init_command": "PRAGMA journal_mode=WAL;"},
}
DATABASE_ROUTERS = ["config.studio_router.StudioRouter"]
WORKSPACES_ROOT = Path(os.getenv("STUDIO_WORKSPACES", NM_DATA_DIR / "studio-workspaces"))
WORKSPACES_ROOT.mkdir(parents=True, exist_ok=True)
PREVIEW_PORT_RANGE = (8601, 8650)
PREVIEW_BIND = os.getenv("STUDIO_PREVIEW_BIND", "0.0.0.0")
IMPORT_SERVER_ROOTS = [x for x in os.getenv("STUDIO_IMPORT_ROOTS", "/var/www").split(",") if x]
AI_RUN_SYNC = os.getenv("STUDIO_AI_SYNC", "False") == "True"
if "fa" not in dict(globals().get("LANGUAGES", [])):
    LANGUAGES = [("fa", "فارسی"), ("en", "English")]

# --- ویدیوی سه‌بعدی (up3d): هسته/موتور/دارایی‌ها کنارِ backend، داده‌ها در data/up3d
UP3D_ROOT = Path(os.getenv("UP3D_ROOT", BASE_DIR.parent / "up3d-engine"))
UP3D_DATA_DIR = Path(os.getenv("UP3D_DATA", NM_DATA_DIR / "up3d"))
UP3D_DATA_DIR.mkdir(parents=True, exist_ok=True)
UP3D_FILES_URL = "/3d/files/"
os.environ.setdefault("UP3D_ROOT", str(UP3D_ROOT))
os.environ.setdefault("UP3D_DATA", str(UP3D_DATA_DIR))
if str(UP3D_ROOT) not in _sys.path:
    _sys.path.insert(0, str(UP3D_ROOT))

CELERY_BEAT_SCHEDULE["compute-maintenance"] = {
    "task": "apps.compute.tasks.maintenance",
    "schedule": 60.0,
    "options": {"expires": 50},
}
