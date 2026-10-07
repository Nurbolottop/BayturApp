"""Условия программы 1.2 (ТЗ лояльности 08.10.2026): 1 балл = 1 сом, кешбек 5 % + надбавка уровня, постоянный статус
по баллам за всё время и стажу. Клиенты примут новую версию при следующем входе."""
from django.conf import settings
from django.db import migrations
from django.utils import timezone


def forward(apps, schema_editor):
    from apps.members.legal_texts import TERMS
    LegalDocument = apps.get_model('members', 'LegalDocument')
    if not LegalDocument.objects.filter(kind='terms').exists():
        return  # пустая база — документы создаст сид
    page = f'{settings.PUBLIC_BASE_URL}/legal/terms'
    LegalDocument.objects.get_or_create(kind='terms', version='1.2', defaults={
        'url': {lang: f'{page}?lang={lang}' for lang in ('ru', 'ky', 'en')}, 'body': TERMS,
        'requires_acceptance': True, 'published_at': timezone.now()})


class Migration(migrations.Migration):

    dependencies = [
        ('members', '0006_app_legal_documents'),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
