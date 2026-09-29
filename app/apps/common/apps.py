from django.apps import AppConfig


class CommonConfig(AppConfig):
    name = 'apps.common'
    label = 'common'

    # Изменение любой из этих моделей сбрасывает кеш публичных справочников
    PUBLIC_MODELS = (
        'catalog.Outlet', 'catalog.Category', 'catalog.Item', 'catalog.ItemPromo',
        'loyalty.Tier', 'loyalty.Privilege',
        'content.Article', 'content.Promo', 'content.ResortEvent', 'content.Story', 'content.StorySlide',
        'members.LegalDocument', 'common.ProgramSettings', 'complaints.ComplaintCategory',
    )

    def ready(self):
        from django.apps import apps
        from django.db.models.signals import post_delete, post_save

        from . import checks  # noqa: F401 — регистрация проверок
        from .caching import bump_content_version
        for label in self.PUBLIC_MODELS:
            model = apps.get_model(label)
            post_save.connect(bump_content_version, sender=model, dispatch_uid=f'bump-save-{label}')
            post_delete.connect(bump_content_version, sender=model, dispatch_uid=f'bump-del-{label}')
