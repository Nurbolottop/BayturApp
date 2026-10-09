"""Из описаний привилегии «начисление» убираем «(1 балл = 1 сом)»: курс оплаты баллами задаётся в настройках."""
from django.db import migrations

STRIP = {'ru': ' (1 балл = 1 сом)', 'ky': ' (1 упай = 1 сом)', 'en': ' (1 point = 1 KGS)'}


def forward(apps, schema_editor):
    Privilege = apps.get_model('loyalty', 'Privilege')
    for p in Privilege.objects.filter(group='points-rate'):
        desc = dict(p.description or {})
        changed = False
        for lang, piece in STRIP.items():
            if piece in (desc.get(lang) or ''):
                desc[lang] = desc[lang].replace(piece, '')
                changed = True
        if changed:
            p.description = desc
            p.save(update_fields=['description'])


class Migration(migrations.Migration):

    dependencies = [
        ('loyalty', '0011_privilege_group_title'),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
