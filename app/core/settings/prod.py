from core.settings.base import *

DEBUG = False

# Cookies только по HTTPS
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Приложение работает за nginx, который терминирует HTTPS.
# Без этого Django считает запрос http-запросом и ломает CSRF/редиректы.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# Прочие security-заголовки
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# HSTS включай только когда HTTPS точно настроен и работает,
# иначе браузеры запомнят домен и http перестанет открываться.
# SECURE_HSTS_SECONDS = 31536000
# SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# SECURE_HSTS_PRELOAD = True

# =============================================================================
# LOGGING — при DEBUG=False ошибки иначе уходят в никуда
# =============================================================================
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}

# Хеш в именах статики (panel.3f2a1c.css): после выкладки браузеры сразу берут новые стили,
# при этом nginx может кешировать их надолго. collectstatic выполняется в entrypoint.
STORAGES = {
    **globals().get('STORAGES', {'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}}),
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'},
}
