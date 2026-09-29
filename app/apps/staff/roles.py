"""
Роли админки и матрица прав (ТЗ §7.1, §7.5, §9.3). Права проверяет бек — это единственное
место, где они описаны; интерфейс админки и API читают их отсюда.
"""
from django.db import models


class Role(models.TextChoices):
    OWNER = 'owner', 'Владелец'
    MANAGER = 'manager', 'Менеджер программы'
    EDITOR = 'editor', 'Редактор контента'
    STAFF = 'staff', 'Сотрудник'
    ACCOUNTANT = 'accountant', 'Бухгалтер'
    CARE = 'care', 'Служба заботы'


O, M, E, S, A, C = Role.OWNER, Role.MANAGER, Role.EDITOR, Role.STAFF, Role.ACCOUNTANT, Role.CARE

PERMISSIONS = {
    # Заявки
    'requests.process': {O, M, S},        # сотрудник — только своих точек
    'requests.view_all': {O, M, A},
    'requests.approve_escalated': {O, M},
    # Клиенты
    'members.view': {O, M, S, A, C},      # сотрудник — без баланса и истории
    'members.history': {O, M, A, C},
    'members.manage': {O, M},             # блокировка, корректировки, ДР, телефон, экспорт
    'members.restore': {O, M},            # удалённые аккаунты
    # Каталог и правила
    'catalog.edit': {O, M},
    'catalog.texts': {O, M, E},
    'tiers.edit': {O, M},
    'tiers.texts': {O, M, E},
    # Контент и рассылки
    'content.edit': {O, M, E},
    'campaigns.send': {O, M},
    'campaigns.draft': {O, M, E},
    # Деньги
    'payments.view': {O, M, A},
    'payments.refund': {O, A},
    'reports.view': {O, M, A},
    # Администрирование
    'settings.edit': {O},
    'staff.manage': {O},
    'audit.view_all': {O},
    'audit.view_own': {O, M},
    # Обращения
    'complaints.view': {O, M, C, S},      # сотрудник — только своей точки
    'complaints.reply': {O, M, C},
    'complaints.notes': {O, M, C, S},
    'complaints.compensate': {O, M},
    'complaints.settings': {O, M},
    # Аналитика по блокам
    'analytics.funnel': {O, M},
    'analytics.members': {O, M},
    'analytics.cohorts': {O, M},
    'analytics.points': {O, M, A},
    'analytics.money': {O, M, A},
    'analytics.catalog': {O, M},
    'analytics.content': {O, M, E},
    'analytics.operations': {O, M, C},
    'analytics.export': {O, M, A, E, C},
}


def role_has(role, perm):
    return role in PERMISSIONS.get(perm, set())
