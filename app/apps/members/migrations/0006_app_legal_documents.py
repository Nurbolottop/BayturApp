"""Политика и условия мобильного приложения: версия 1.1 со страницами на нашем сервере (/legal/<документ>?lang=…).
Прежние ссылки baytur.kg/…/privacy|terms отдавали 404. Новая версия попросит клиентов принять документы заново."""
from django.conf import settings
from django.db import migrations
from django.utils import timezone

VERSION = '1.1'


def forward(apps, schema_editor):
    from apps.members.legal_texts import PRIVACY, TERMS
    LegalDocument = apps.get_model('members', 'LegalDocument')
    if not LegalDocument.objects.exists():
        return  # пустая база — документы создаст сид
    now = timezone.now()
    for kind, body in (('privacy', PRIVACY), ('terms', TERMS)):
        page = f'{settings.PUBLIC_BASE_URL}/legal/{kind}'
        LegalDocument.objects.get_or_create(kind=kind, version=VERSION, defaults={
            'url': {lang: f'{page}?lang={lang}' for lang in ('ru', 'ky', 'en')}, 'body': body,
            'requires_acceptance': True, 'published_at': now})


class Migration(migrations.Migration):

    dependencies = [
        ('members', '0005_legaldocument_body'),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
