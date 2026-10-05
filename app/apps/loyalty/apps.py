from django.apps import AppConfig


class LoyaltyConfig(AppConfig):
    name = 'apps.loyalty'
    label = 'loyalty'

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from .models import Achievement, LoyaltySettings, Tier, TierAchievement
        # Правка уровней и заданий меняет версию программы (её номер хранится в итогах периодов)
        for model in (Tier, Achievement, TierAchievement):
            post_save.connect(LoyaltySettings.bump_version, sender=model, dispatch_uid=f'loyalty-v-save-{model.__name__}')
            post_delete.connect(LoyaltySettings.bump_version, sender=model, dispatch_uid=f'loyalty-v-del-{model.__name__}')
