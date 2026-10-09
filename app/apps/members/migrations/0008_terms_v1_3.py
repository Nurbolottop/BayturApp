"""Условия программы 1.3: курс оплаты баллами берётся из настроек ({points_per_som}), а не «1 балл = 1 сом»."""
from django.conf import settings
from django.db import migrations
from django.utils import timezone


def forward(apps, schema_editor):
    from apps.members.legal_texts import TERMS
    LegalDocument = apps.get_model('members', 'LegalDocument')
    if not LegalDocument.objects.filter(kind='terms').exists():
        return
    page = f'{settings.PUBLIC_BASE_URL}/legal/terms'
    LegalDocument.objects.get_or_create(kind='terms', version='1.3', defaults={
        'url': {lang: f'{page}?lang={lang}' for lang in ('ru', 'ky', 'en')}, 'body': TERMS,
        'requires_acceptance': True, 'published_at': timezone.now()})


class Migration(migrations.Migration):

    dependencies = [
        ('members', '0007_terms_v1_2'),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
