"""Контекст шаблонов панели: меню из реестра разделов и счётчики (очередь, эскалации, новые обращения)."""


def _counters(user):
    from apps.cashback.models import CashbackRequest, RequestStatus
    from apps.complaints.models import Complaint, ComplaintStatus
    out = {}
    from apps.cashback.desk import scoped_requests
    from apps.complaints.services import scoped_complaints
    if user.can('requests.process'):
        out['queue'] = scoped_requests(user).filter(status=RequestStatus.PENDING).count()
    if user.can('requests.approve_escalated'):
        out['escalated'] = CashbackRequest.objects.filter(status=RequestStatus.PENDING, escalated=True).count()
    if user.can('complaints.view'):
        out['complaints'] = scoped_complaints(user).filter(status=ComplaintStatus.NEW).count()
    return out


def panel(request):
    if not request.path.startswith('/panel/'):
        return {}
    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated and getattr(user, 'is_staff_user', False)):
        return {'panel_menu': [], 'panel_tabs': []}
    from .modes import modes_context
    from .sections import GROUPS, allowed_sections
    current = getattr(request, 'panel_section', None)
    counters = _counters(user)
    modes = modes_context(request)
    # «Вечная новость» есть только у режимов S&K
    allowed = [s for s in allowed_sections(user) if not (s.key == 'eternal' and modes['panel_mode'] == 'resort')]
    items = [{
        'key': s.key, 'label': s.label, 'url': s.url, 'icon': s.icon, 'group': s.group,
        'active': s.key == current, 'badge': counters.get(s.badge) if s.badge else None,
    } for s in allowed]
    groups = [{'label': label, 'items': [i for i in items if i['group'] == key]} for key, label in GROUPS]
    tabs = [i for s, i in zip(allowed, items) if s.tab][:5]
    return {
        'panel_menu': [g for g in groups if g['items']],
        'panel_tabs': tabs,
        'panel_counters': counters,
        'panel_role': user.role_label,
        **modes,
    }
