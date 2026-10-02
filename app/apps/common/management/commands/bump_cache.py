from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Сбросить кеш публичных справочников (выполняется при каждой выкладке — формат ответа мог измениться).'

    def handle(self, *args, **opts):
        from apps.common.caching import bump_content_version
        bump_content_version()
        self.stdout.write('Кеш справочников сброшен')
