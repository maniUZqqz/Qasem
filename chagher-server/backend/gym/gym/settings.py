from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# ==================== Media ====================
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# فایل‌های خصوصی — هرگز از طریق وب‌سرور مستقیم سرو نمی‌شوند.
PRIVATE_MEDIA_ROOT = os.environ.get(
    'DJANGO_PRIVATE_MEDIA_ROOT',
    os.path.join(BASE_DIR, 'private_media'),
)

# ==================== Static ====================
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'staticfiles_src'),
]

STATIC_ROOT = os.path.join(BASE_DIR, 'static')
STATIC_URL = '/static/'


# ==================== Environment Helpers ====================
def _env_bool(name, default):
    return os.environ.get(name, str(default)).strip().lower() in ('1', 'true', 'yes', 'on')


def _env_list(name):
    return [item.strip() for item in os.environ.get(name, '').split(',') if item.strip()]


# ==================== Core ====================
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-f8sgu=byn40z)4s%t$_dw4sej@v8@h)ht5&dgh3d61^o5pbaa)'
)

DEBUG = False


# ── تفکیکِ دنیای ورزشکار (B2C) از باشگاه (B2B) ──
# میزبانِ B2C جداست تا لندینگ، پنل و قیمت‌گذاری‌شان قاطی نشود.
# دو میزبانِ B2C، قرینهٔ دو میزبانِ B2B:
#   app.chagher.ir → هوم‌پیج/لندینگِ ورزشکار   (قرینهٔ chagher.ir)
#   my.chagher.ir  → پنلِ ورزشکار              (قرینهٔ panel.chagher.ir)
B2C_HOSTS = [h.strip() for h in os.environ.get(
    'B2C_HOSTS', 'app.chagher.ir,my.chagher.ir').split(',') if h.strip()]
# روی این میزبان، ریشه مستقیم می‌رود به پنلِ ورزشکار (نه لندینگ)
B2C_PANEL_HOST = os.environ.get('B2C_PANEL_HOST', 'my.chagher.ir')
B2B_HOST = os.environ.get('B2B_HOST', 'chagher.ir')

ALLOWED_HOSTS = ['chagher.ir', 'www.chagher.ir', 'panel.chagher.ir',
                 'app.chagher.ir', 'my.chagher.ir',
                 '185.239.3.189', '127.0.0.1', 'testserver']

ALLOW_MOCK_PAYMENT_GATEWAY = _env_bool('DJANGO_ALLOW_MOCK_GATEWAY', DEBUG)


# ==================== Applications ====================
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',

    'app',
    'accounting',          # حسابداریِ دوطرفه (۱۴۰۵/۰۸/۰۳)
    'portfolio',           # رزومه و نمونه‌کارِ تیم (۱۴۰۵/۰۸/۰۴)
    'rest_framework',
    'rest_framework.authtoken',
    'corsheaders',
    'drf_spectacular',
]

AUTH_USER_MODEL = 'app.CustomUser'

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'app.middleware_b2c.B2CHostMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'gym.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.media',
                'django.template.context_processors.static',
                'app.context_processors.app_mode',
                'app.context_processors.site_contact',
            ],
        },
    },
]

WSGI_APPLICATION = 'gym.wsgi.application'


# ==================== Database ====================
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        # مهلتِ انتظار برای قفلِ نوشتن؛ بی‌این، زیرِ هم‌زمانی خطا می‌دهد
        'OPTIONS': {'timeout': 20},
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# ==================== Auth ====================
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ==================== i18n ====================
TIME_ZONE = 'Asia/Tehran'
DEFAULT_CHARSET = 'utf-8'
LANGUAGE_CODE = 'fa-ir'
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ==================== DRF ====================
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_THROTTLE_RATES': {
        'login': '10/min',
        'password_reset': '5/hour',
        'password_reset_confirm': '10/hour',
        'client_access': '30/hour',
    },
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'Gym Management API',
    'DESCRIPTION': 'API چغر - ابزار هوش مصنوعی مربی‌ها برای برنامه ورزشی و غذایی',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'SCHEMA_PATH_PREFIX': r'/api/',
    'ENUM_NAME_OVERRIDES': {
        'GenderEnum': 'app.models.ClientProgram.GENDER_CHOICES',
        'ProgramSectionEnum': 'app.models.ClientProgram.PROGRAM_TYPE_CHOICES',
        'TrainingPlaceEnum': 'app.models.ClientProgram.TRAINING_PLACE_CHOICES',
        'AccountTypeEnum': 'app.models.CustomUser.ACCOUNT_TYPE_CHOICES',
        'PaymentMethodEnum': 'app.models.TokenPurchase.PAYMENT_METHOD_CHOICES',
        'PurchaseStatusEnum': 'app.models.TokenPurchase.STATUS_CHOICES',
        'AIProviderTypeEnum': 'app.models.APIConfig.PROVIDER_TYPE_CHOICES',
    },
}


# ==================== CORS / CSRF ====================
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_NULL_ORIGIN = True

CSRF_TRUSTED_ORIGINS = [
    'https://chagher.ir', 'https://www.chagher.ir',
    'http://185.239.3.189', 'http://185.239.3.189:8000',
    'https://panel.chagher.ir', 
]


# ==================== Production Hardening ====================
# چون هم روی HTTPS (دامنه) و هم HTTP (آی‌پی) سرویس می‌دیم، این‌ها رو خاموش می‌کنیم
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

# Nginx و Cloudflare مسئول SSL هستند، پس جنگو نباید ریدایرکت کنه
SECURE_SSL_REDIRECT = False
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# HSTS فعلاً خاموش — چون هنوز روی HTTP (IP) هم سرویس می‌دیم
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False


# ==================== Logging ====================
LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} [{name}] {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(LOG_DIR, 'gym.log'),
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 5,
            'encoding': 'utf-8',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console', 'file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'app': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'ai_engine': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'pdf_generator': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}


# ==================== SMS ====================
SMS_HOOK_URL = os.environ.get(
    'SMS_HOOK_URL',
    'http://127.0.0.1:8000/chagher/api/sms/webhook/'
)

SMS_HOOK_TIMEOUT = int(os.environ.get('SMS_HOOK_TIMEOUT', 5))
SMS_CODE_TTL = int(os.environ.get('SMS_CODE_TTL', 300))  # ۵ دقیقه

SMS_HOOK_HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
}

SMS_RETURN_CODE_IN_RESPONSE = _env_bool('SMS_RETURN_CODE_IN_RESPONSE', DEBUG)

SMS_EMERGENCY_CODE = os.environ.get('SMS_EMERGENCY_CODE', '6985').strip()


# ==================== Cache ====================
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'django_cache_table',
        'TIMEOUT': 300,
        'OPTIONS': {
            'MAX_ENTRIES': 10000,
        },
    }
}


# ==================== Public URL ====================
PUBLIC_BASE_URL = os.environ.get('PUBLIC_BASE_URL', 'https://chagher.ir')
# ⚠ جنگو روی ریشهٔ دامنه نشسته است (nginx: location / → gunicorn).
# پیشوندِ /chagher فقط برای لینک‌های قدیمیِ چاپ‌شده مانده و در nginx به ریشه
# تغییرِ مسیر می‌خورد. اگر روزی مسیر عوض شد، فقط همین خط عوض می‌شود.







