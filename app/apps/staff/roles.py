"""
Роли сотрудников и матрица прав. Две роли:
- Директор — полный доступ, работает в веб-панели (email + пароль + 2FA), создаёт точки и администраторов;
- Администратор кассы — привязан к точкам (ресепшен, бассейн, баня, спортзал…), работает в приложении
  кассира (телефон + 6-значный PIN): заявки, оплата баллами по QR, поиск клиента, обращения своих точек.
Права проверяет бек — это единственное место, где они описаны.
"""
from django.db import models


class Role(models.TextChoices):
    OWNER = 'owner', 'Директор'
    STAFF = 'staff', 'Администратор кассы'


O, S = Role.OWNER, Role.STAFF

PERMISSIONS = {
    # Заявки
    'requests.process': {O, S},        # администратор — только своих точек
    'requests.view_all': {O},
    'requests.approve_escalated': {O},
    # Клиенты
    'members.view': {O, S},      # администратор — без баланса и истории
    'members.history': {O},
    'members.manage': {O},             # блокировка, корректировки, ДР, телефон, экспорт
    'members.restore': {O},            # удалённые аккаунты
    # Каталог и правила
    'catalog.edit': {O},
    'catalog.texts': {O},
    'tiers.edit': {O},
    'tiers.texts': {O},
    # Контент и рассылки
    'content.edit': {O},
    'campaigns.send': {O},
    'campaigns.draft': {O},
    # Деньги
    'payments.view': {O},
    'payments.refund': {O},
    'reports.view': {O},
    # Администрирование
    'settings.edit': {O},
    'staff.manage': {O},
    'audit.view_all': {O},
    'audit.view_own': {O},
    # Обращения
    'complaints.view': {O, S},      # администратор — только своих точек
    'complaints.reply': {O},
    'complaints.notes': {O, S},
    'complaints.compensate': {O},
    'complaints.settings': {O},
    # Аналитика по блокам
    'analytics.funnel': {O},
    'analytics.members': {O},
    'analytics.cohorts': {O},
    'analytics.points': {O},
    'analytics.money': {O},
    'analytics.catalog': {O},
    'analytics.content': {O},
    'analytics.operations': {O},
    'analytics.export': {O},
}


def role_has(role, perm):
    return role in PERMISSIONS.get(perm, set())
