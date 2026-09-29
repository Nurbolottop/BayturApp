from core.settings.base import *  # noqa

DEBUG = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}

# Задачи в тестах не уходят в брокер: фоновые обработчики вызываются напрямую
CELERY_BROKER_URL = 'memory://'
CELERY_TASK_ALWAYS_EAGER = False

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
REST_FRAMEWORK = {**REST_FRAMEWORK, 'DEFAULT_THROTTLE_RATES': {
    'public_ip': '10000/min', 'public_device': '10000/min', 'otp_ip': '10000/hour', 'events': '10000/min',
}}
SMS_BACKEND = 'console'
PUSH_BACKEND = 'console'
PAYMENT_BACKEND = 'fake'
PAYMENT_WEBHOOK_SECRET = 'test-secret'
PUBLIC_BASE_URL = 'https://api.test'
MEDIA_ROOT = '/tmp/baytur-test-media'

# Параллельные прогоны тестов (разные разработчики/агенты) — разные тестовые БД
import os  # noqa: E402
DATABASES['default']['TEST'] = {'NAME': os.getenv('TEST_DB_NAME', 'test_baytur')}
LOGGING = {'version': 1, 'disable_existing_loggers': False, 'root': {'handlers': [], 'level': 'CRITICAL'}}
