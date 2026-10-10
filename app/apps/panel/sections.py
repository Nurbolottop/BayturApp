"""
Единый реестр разделов панели: пункт меню + право доступа. Меню, вкладки на планшете
и проверка доступа во view читают его отсюда — права описаны один раз (матрица — apps.staff.roles).
"""
from dataclasses import dataclass, field

from django.urls import reverse


@dataclass(frozen=True)
class Section:
    key: str
    label: str
    url_name: str
    icon: str
    perms: tuple            # достаточно любого из прав
    group: str = 'main'
    tab: bool = False       # показывать во вкладках на планшете / телефоне
    badge: str = ''         # ключ счётчика из context processor
    children: tuple = field(default=())

    def allowed(self, user):
        return bool(user and user.is_authenticated and getattr(user, 'is_staff_user', False)
                    and any(user.can(p) for p in self.perms))

    @property
    def url(self):
        return reverse(self.url_name)


ANALYTICS_BLOCKS = [
    # key, заголовок, право, функция reports
    ('funnel', 'Воронка', 'analytics.funnel', 'funnel'),
    ('members', 'Клиенты', 'analytics.members', 'members'),
    ('cohorts', 'Когорты', 'analytics.cohorts', 'cohorts'),
    ('points', 'Баллы', 'analytics.points', 'points'),
    ('money', 'Деньги', 'analytics.money', 'money'),
    ('catalog', 'Каталог и акции', 'analytics.catalog', 'catalog'),
    ('content', 'Контент и push', 'analytics.content', 'content'),
    ('operations', 'Работа курорта', 'analytics.operations', 'operations'),
    ('complaints', 'Обращения', 'analytics.operations', 'complaints_report'),
]

SECTIONS = [
    Section('dashboard', 'Дашборд', 'panel:dashboard', 'home', ('reports.view',), tab=True),
    Section('analytics', 'Аналитика', 'panel:analytics', 'chart', tuple(sorted({b[2] for b in ANALYTICS_BLOCKS}))),
    Section('desk', 'Очередь', 'panel:desk', 'queue', ('requests.process',), group='work', tab=True, badge='queue'),
    Section('requests', 'Заявки', 'panel:requests', 'receipt', ('requests.view_all',), group='work', tab=True,
            badge='escalated'),
    Section('payments', 'Платежи', 'panel:payments', 'card', ('payments.view',), group='work'),
    Section('members', 'Клиенты', 'panel:members', 'users', ('members.view',), group='work', tab=True),
    Section('complaints', 'Обращения', 'panel:complaints', 'chat', ('complaints.view',), group='work', tab=True,
            badge='complaints'),
    Section('catalog', 'Каталог', 'panel:catalog', 'grid', ('catalog.edit', 'catalog.texts'), group='program'),
    Section('promotions', 'Акции', 'panel:promotions', 'gift', ('catalog.edit', 'catalog.texts'), group='program'),
    Section('tiers', 'Уровни', 'panel:tiers', 'medal', ('tiers.edit', 'tiers.texts'), group='program'),
    Section('content', 'Контент', 'panel:content', 'news', ('content.edit',), group='program', tab=True),
    Section('campaigns', 'Рассылки', 'panel:campaigns', 'megaphone', ('campaigns.draft', 'campaigns.send'),
            group='program'),
    Section('settings', 'Настройки', 'panel:settings', 'settings', ('settings.edit',), group='admin'),
    Section('staff', 'Сотрудники', 'panel:staff', 'shield', ('staff.manage',), group='admin'),
    Section('audit', 'Аудит-лог', 'panel:audit', 'history', ('audit.view_all', 'audit.view_own'), group='admin'),
]

GROUPS = [('main', ''), ('work', 'Работа'), ('program', 'Программа'), ('admin', 'Администрирование')]

BY_KEY = {s.key: s for s in SECTIONS}


def section(key):
    return BY_KEY[key]


def allowed_sections(user):
    return [s for s in SECTIONS if s.allowed(user)]


def home_url(user):
    """Первый доступный раздел — сотрудник попадает сразу в очередь."""
    if user.is_authenticated and getattr(user, 'is_outlet_bound', False) and BY_KEY['desk'].allowed(user):
        return BY_KEY['desk'].url
    for s in SECTIONS:
        if s.allowed(user):
            return s.url
    return None
