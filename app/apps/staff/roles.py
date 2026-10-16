"""
Роли сотрудников и права. Системные роли:
- Директор — полный доступ, работает в веб-панели (email + пароль + 2FA), создаёт точки, сотрудников и роли;
- Администратор кассы — привязан к точкам (ресепшен, бассейн, баня, спортзал…), работает в приложении
  кассира (телефон + 6-значный PIN): заявки, оплата баллами по QR, поиск клиента, обращения своих точек.
Остальные роли (например, «Маркетинг») директор создаёт и настраивает в панели: набор прав — галочками
(модель StaffRole). PERMISSIONS ниже — права по умолчанию для системных ролей и полный список прав.
Права проверяет бек — здесь единственное место, где они описаны.
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
    'promotions.edit': {O},            # акции на цену
    'coupons.manage': {O},             # приветственный купон: настройка и выданные купоны
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


class RoleKind(models.TextChoices):
    PANEL = 'panel', 'Веб-панель (email + пароль + 2FA)'
    APP = 'app', 'Приложение кассира (телефон + PIN)'


# Подписи прав для экрана «Роли» — по группам, в порядке показа
PERMISSION_GROUPS = [
    ('Заявки и касса', [
        ('requests.process', 'Обрабатывать заявки и принимать оплату баллами (кассир — только своих точек)'),
        ('requests.view_all', 'Видеть все заявки'),
        ('requests.approve_escalated', 'Одобрять заявки, ушедшие менеджеру'),
    ]),
    ('Клиенты', [
        ('members.view', 'Искать клиентов и открывать карточку'),
        ('members.history', 'Видеть баланс и историю клиента'),
        ('members.manage', 'Блокировать, корректировать баллы, менять ДР и телефон, экспорт'),
        ('members.restore', 'Восстанавливать удалённые аккаунты'),
    ]),
    ('Каталог и программа', [
        ('catalog.edit', 'Услуги, цены, разделы, объекты, главная'),
        ('catalog.texts', 'Только тексты и фото услуг'),
        ('promotions.edit', 'Акции на цену: добавлять, менять, удалять'),
        ('tiers.edit', 'Уровни и привилегии'),
        ('tiers.texts', 'Только тексты уровней и привилегий'),
        ('coupons.manage', 'Приветственный купон за регистрацию'),
    ]),
    ('Контент и рассылки', [
        ('content.edit', 'Баннеры, статьи, события, сторис, «вечная новость»'),
        ('campaigns.draft', 'Готовить push-рассылки (черновики)'),
        ('campaigns.send', 'Отправлять push-рассылки'),
    ]),
    ('Деньги и отчёты', [
        ('payments.view', 'Платежи'),
        ('payments.refund', 'Возвраты денег'),
        ('reports.view', 'Дашборд'),
    ]),
    ('Обращения', [
        ('complaints.view', 'Видеть обращения (кассир — только своих точек)'),
        ('complaints.reply', 'Отвечать клиентам и закрывать'),
        ('complaints.notes', 'Внутренние заметки'),
        ('complaints.compensate', 'Компенсация баллами'),
        ('complaints.settings', 'Темы и шаблоны ответов'),
    ]),
    ('Аналитика', [
        ('analytics.funnel', 'Воронка'), ('analytics.members', 'Клиенты'), ('analytics.cohorts', 'Когорты'),
        ('analytics.points', 'Баллы'), ('analytics.money', 'Деньги'), ('analytics.catalog', 'Каталог и акции'),
        ('analytics.content', 'Контент и push'), ('analytics.operations', 'Работа курорта и обращения'),
        ('analytics.export', 'Выгрузка отчётов'),
    ]),
    ('Администрирование', [
        ('settings.edit', 'Настройки программы'),
        ('staff.manage', 'Сотрудники и роли'),
        ('audit.view_all', 'Весь аудит-лог'),
        ('audit.view_own', 'Свои действия в аудит-логе'),
    ]),
]

# Права новой роли «Маркетинг» по умолчанию (директор меняет их в панели)
MARKETING_DEFAULT = ['promotions.edit', 'content.edit', 'campaigns.draft', 'campaigns.send', 'coupons.manage',
                     'analytics.content', 'analytics.catalog', 'audit.view_own']

ROLES_CACHE_KEY = 'staff_roles:v1'


def default_permissions(role):
    return sorted(p for p, roles in PERMISSIONS.items() if role in roles)


def roles_map():
    """{role_id: {'name', 'kind', 'perms': set}} — из БД, с кешем до изменения ролей."""
    from django.core.cache import cache
    data = cache.get(ROLES_CACHE_KEY)
    if data is None:
        from .models import StaffRole
        data = {r.pk: {'name': r.name, 'kind': r.kind, 'perms': set(r.permissions or [])}
                for r in StaffRole.objects.all()}
        if not data:  # до миграции с ролями — системные по умолчанию
            data = {Role.OWNER: {'name': Role.OWNER.label, 'kind': RoleKind.PANEL, 'perms': set(PERMISSIONS)},
                    Role.STAFF: {'name': Role.STAFF.label, 'kind': RoleKind.APP,
                                 'perms': set(default_permissions(Role.STAFF))}}
        cache.set(ROLES_CACHE_KEY, data, 300)
    return data


def forget_roles():
    from django.core.cache import cache
    cache.delete(ROLES_CACHE_KEY)


def role_kind(role):
    if role == Role.OWNER:
        return RoleKind.PANEL
    info = roles_map().get(role)
    return info['kind'] if info else RoleKind.APP


def role_name(role):
    info = roles_map().get(role)
    return info['name'] if info else role


def role_choices():
    """[(id, название)] — Директор первым, кассир вторым, остальные по названию."""
    order = {Role.OWNER: 0, Role.STAFF: 1}
    items = sorted(roles_map().items(), key=lambda kv: (order.get(kv[0], 2), kv[1]['name']))
    return [(k, v['name']) for k, v in items]


def role_has(role, perm):
    if role == Role.OWNER:  # директор — всегда все права
        return perm in PERMISSIONS
    info = roles_map().get(role)
    return bool(info) and perm in info['perms']
