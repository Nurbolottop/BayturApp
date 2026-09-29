from django.conf import settings
from django.core.checks import Error, Warning, register


@register(deploy=True)
def production_providers(app_configs, **kwargs):
    """manage.py check --deploy: в production не должно остаться заглушек провайдеров."""
    if settings.APP_ENV != 'production':
        return []
    issues = []
    if settings.PAYMENT_BACKEND == 'fake':
        issues.append(Error('PAYMENT_BACKEND=fake в production: подключите реальный платёжный шлюз',
                            id='baytur.E001'))
    if settings.SMS_BACKEND == 'console':
        issues.append(Error('SMS_BACKEND=console в production: SMS-коды не уходят клиентам', id='baytur.E002'))
    if settings.OTP_FIXED_CODE:
        issues.append(Error('OTP_FIXED_CODE задан в production — уберите переменную', id='baytur.E003'))
    if settings.PUSH_BACKEND == 'console':
        issues.append(Warning('PUSH_BACKEND=console в production: push не отправляются', id='baytur.W001'))
    if settings.PAYMENT_WEBHOOK_SECRET == settings.SECRET_KEY:
        issues.append(Warning('PAYMENT_WEBHOOK_SECRET не задан отдельно', id='baytur.W002'))
    return issues
