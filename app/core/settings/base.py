from datetime import timedelta
from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# PATHS (ПУТИ)
# =============================================================================
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# =============================================================================
# SECURITY (БЕЗОПАСНОСТЬ)
# =============================================================================
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    raise Exception("SECRET_KEY не задан в переменных окружения")

_allowed_hosts_env = os.getenv('ALLOWED_HOSTS', '').strip()
ALLOWED_HOSTS = [host.strip() for host in _allowed_hosts_env.split(',') if host.strip()]

_csrf_trusted_origins_env = os.getenv('CSRF_TRUSTED_ORIGINS', '').strip()
CSRF_TRUSTED_ORIGINS = [
    origin.strip() for origin in _csrf_trusted_origins_env.split(',') if origin.strip()
]

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# dev | staging | production
APP_ENV = os.getenv('APP_ENV', 'dev')

# =============================================================================
# APPLICATIONS (ПРИЛОЖЕНИЯ)
# =============================================================================

INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party
    'rest_framework',
    'drf_spectacular',
    'channels',

    # Local apps
    'apps.common',
    'apps.staff',
    'apps.members',
    'apps.catalog',
    'apps.loyalty',
    'apps.content',
    'apps.cashback',
    'apps.payments',
    'apps.notifications',
    'apps.complaints',
    'apps.analytics',
    'apps.backoffice',
    'apps.panel',
]

AUTH_USER_MODEL = 'staff.StaffUser'

# =============================================================================
# MIDDLEWARE (ПРОМЕЖУТОЧНЫЕ ОБРАБОТЧИКИ)
# =============================================================================

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.common.middleware.ApiContextMiddleware',
]

# =============================================================================
# URLS & WSGI/ASGI (МАРШРУТЫ)
# =============================================================================

ROOT_URLCONF = 'core.urls'
WSGI_APPLICATION = 'core.wsgi.application'
ASGI_APPLICATION = 'core.asgi.application'

# =============================================================================
# TEMPLATES (ШАБЛОНЫ)
# =============================================================================

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.panel.context.panel',
            ],
        },
    },
]

# =============================================================================
# DATABASE (БАЗА ДАННЫХ)
# =============================================================================

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('POSTGRES_DB'),
        'USER': os.getenv('POSTGRES_USER'),
        'PASSWORD': os.getenv('POSTGRES_PASSWORD'),
        'HOST': os.getenv('POSTGRES_HOST'),
        'PORT': int(os.getenv('POSTGRES_PORT', 5432)),
        'CONN_MAX_AGE': 60,
    }
}

# =============================================================================
# CACHE / REDIS / CHANNELS / CELERY
# =============================================================================

REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': REDIS_URL,
        'KEY_PREFIX': 'baytur',
    }
}

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {'hosts': [REDIS_URL]},
    }
}

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = None
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TIMEZONE = 'Asia/Bishkek'
CELERY_BEAT_SCHEDULE = {
    # Автоподтверждение, начисление с задержкой, автоотказ просроченных pending.
    # Сроки хранятся в заявке (…_due_at), поэтому рестарт ничего не теряет.
    'cashback-process-due': {'task': 'apps.cashback.tasks.process_due_requests', 'schedule': 15.0},
    'payments-expire': {'task': 'apps.payments.tasks.expire_payments', 'schedule': 60.0},
    'payments-orphans': {'task': 'apps.payments.tasks.resolve_orphan_payments', 'schedule': 300.0},
    'promos-expire': {'task': 'apps.catalog.tasks.bump_on_promo_boundaries', 'schedule': 300.0},
    'notifications-deliver-delayed': {'task': 'apps.notifications.tasks.deliver_delayed', 'schedule': 60.0},
    'campaigns-send-scheduled': {'task': 'apps.notifications.tasks.send_scheduled_campaigns', 'schedule': 60.0},
    'complaints-overdue': {'task': 'apps.complaints.tasks.notify_overdue', 'schedule': 600.0},
    'daily-maintenance': {'task': 'apps.common.tasks.daily_maintenance', 'schedule': 3600.0},
}

# =============================================================================
# PASSWORD VALIDATION (ВАЛИДАЦИЯ ПАРОЛЕЙ)
# =============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LOGIN_URL = 'panel:login'

# =============================================================================
# INTERNATIONALIZATION (ИНТЕРНАЦИОНАЛИЗАЦИЯ)
# =============================================================================

LANGUAGE_CODE = os.getenv('LANGUAGE_CODE', 'ru')
TIME_ZONE = os.getenv('TIME_ZONE', 'Asia/Bishkek')
USE_I18N = True
USE_TZ = True

# Языки контента: всё локализуемое хранится как {ru, ky, en}, пустое → ru
CONTENT_LANGUAGES = ('ru', 'ky', 'en')
DEFAULT_CONTENT_LANGUAGE = 'ru'

# =============================================================================
# STATIC & MEDIA FILES (СТАТИЧЕСКИЕ И МЕДИА ФАЙЛЫ)
# =============================================================================

STATIC_URL = '/static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Внешний адрес — из него строятся абсолютные URL картинок в API
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')

# S3-совместимое хранилище включается переменной S3_BUCKET (нужен django-storages[s3])
if os.getenv('S3_BUCKET'):
    STORAGES = {
        'default': {
            'BACKEND': 'storages.backends.s3.S3Storage',
            'OPTIONS': {
                'bucket_name': os.getenv('S3_BUCKET'),
                'endpoint_url': os.getenv('S3_ENDPOINT_URL') or None,
                'custom_domain': os.getenv('S3_CDN_DOMAIN') or None,
                'querystring_auth': False,
            },
        },
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }

DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024

# =============================================================================
# DEFAULTS (ЗНАЧЕНИЯ ПО УМОЛЧАНИЮ)
# =============================================================================

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# =============================================================================
# REST API
# =============================================================================

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [],
    'DEFAULT_PERMISSION_CLASSES': [],
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.MultiPartParser',
    ],
    'EXCEPTION_HANDLER': 'apps.common.errors.exception_handler',
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'UNAUTHENTICATED_USER': None,
    'DEFAULT_THROTTLE_RATES': {
        'public_ip': '600/min',
        'public_device': '300/min',
        'otp_ip': '30/hour',
        'events': '120/min',
    },
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'BAYTUR API',
    'DESCRIPTION': 'Backend программы лояльности BAYTUR: клиентский API, рабочее место сотрудника и админ-API.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'SCHEMA_PATH_PREFIX': r'/api/v1',
    'PREPROCESSING_HOOKS': ['core.api_schema.exclude_admin_crud'],
    # Имена enum для генерации DTO в Dart — как в мобилке
    'ENUM_NAME_OVERRIDES': {
        'CategoryId': 'apps.catalog.models.CategoryId',
        'PaymentMethod': 'apps.catalog.models.PaymentMethod',
        'TierId': 'apps.loyalty.models.TierId',
        'OperationKind': 'apps.loyalty.models.OperationKind',
        'FeatureIcon': 'apps.catalog.models.FEATURE_ICONS',
        'PerkIcon': 'apps.loyalty.models.PERK_ICONS',
        'RequestStatus': ['pending', 'confirmed', 'credited', 'rejected', 'cancelled'],
        'PaymentStatus': ['created', 'pending', 'paid', 'failed', 'expired', 'refunded'],
        'OnlinePaymentMethod': ['finik', 'freedomPay', 'elqr'],
        'ComplaintStatus': ['new', 'in_progress', 'answered', 'closed'],
        'ComplaintSubtype': ['not_credited', 'credited_less', 'overcharged', 'other'],
        'Language': ['ru', 'ky', 'en'],
        'Platform': ['ios', 'android'],
        'PricingType': ['unit', 'check'],
        'PricingUnit': ['night', 'session', 'guest', 'hour', 'visit'],
        'BonusKind': ['promo', 'birthday'],
        'RejectReasonCode': ['not_provided', 'wrong_amount', 'duplicate', 'other'],
        'ConsentKind': ['terms', 'privacy'],
        'MessageAuthor': ['client', 'resort'],
        'RequestsFilter': ['active', 'all'],
    },
}

# JWT
JWT_ACCESS_TTL = timedelta(minutes=15)
JWT_REFRESH_TTL = timedelta(days=30)
JWT_ALGORITHM = 'HS256'

# =============================================================================
# ПРОВАЙДЕРЫ
# =============================================================================

SMS_BACKEND = os.getenv('SMS_BACKEND', 'console')      # console | (реальный — после выбора провайдера)
PUSH_BACKEND = os.getenv('PUSH_BACKEND', 'console')    # console | fcm
FCM_CREDENTIALS_FILE = os.getenv('FCM_CREDENTIALS_FILE', '')
PAYMENT_BACKEND = os.getenv('PAYMENT_BACKEND', 'fake')  # fake | (реальные — после выбора провайдеров)
PAYMENT_WEBHOOK_SECRET = os.getenv('PAYMENT_WEBHOOK_SECRET', SECRET_KEY)

EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'noreply@baytur.kg')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'verbose': {'format': '[{asctime}] {levelname} {name}: {message}', 'style': '{'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'verbose'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {'django.request': {'handlers': ['console'], 'level': 'ERROR', 'propagate': False}},
}
