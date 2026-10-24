"""Настройки программы, контакты, точки, документы, тестовый аккаунт; сотрудники админки; аудит-лог."""
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.catalog.models import Outlet
from apps.common.audit import audit, model_snapshot
from apps.common.models import AuditLog, ProgramSettings
from apps.members.models import LegalDocument
from apps.staff.models import StaffUser
from apps.staff.roles import PERMISSIONS, Role, RoleKind, role_choices, role_kind

from ..access import panel_view
from ..forms import ContactsForm, LegalForm, OutletForm, ProgramSettingsForm, StaffUserForm, StoreTestForm
from .money import _date, page

SETTINGS_TABS = [('program', 'Программа'), ('contacts', 'Контакты'), ('outlets', 'Точки (кассы)'),
                 ('legal', 'Документы'), ('store', 'Тестовый аккаунт')]


def _ps():
    return ProgramSettings.objects.get_or_create(pk=1)[0]


@panel_view('settings')
def settings_view(request, tab='program'):
    ps = _ps()
    form_cls = {'program': ProgramSettingsForm, 'contacts': ContactsForm, 'store': StoreTestForm}.get(tab)
    ctx = {'tab': tab, 'tabs': SETTINGS_TABS}
    if form_cls:
        form = form_cls(request.POST or None, instance=ps)
        if request.method == 'POST' and form.is_valid():
            before = model_snapshot(ps, list(form.fields))
            obj = form.save()
            audit(request, f'settings.{tab}', obj, before=before, after=model_snapshot(obj, list(form.fields)))
            messages.success(request, 'Настройки сохранены. Правила действуют только на новые заявки'
                             if tab == 'program' else 'Сохранено')
            return redirect('panel:settings-tab', tab=tab)
        ctx['form'] = form
    elif tab == 'outlets':
        ctx['outlets'] = Outlet.objects.all()
    elif tab == 'legal':
        ctx['docs'] = LegalDocument.objects.all()
        ctx['current'] = {k: LegalDocument.current(k) for k in ('terms', 'privacy', 'deletion')}
        form = LegalForm(request.POST or None)
        if request.method == 'POST' and form.is_valid():
            doc = form.save()
            audit(request, 'legal.create', doc, after=model_snapshot(doc))
            messages.success(request, 'Версия документа добавлена' + (
                '. Клиенты примут её при следующем входе' if doc.requires_acceptance and doc.published_at else ''))
            return redirect('panel:settings-tab', tab='legal')
        ctx['form'] = form
    else:
        return redirect('panel:settings')
    return render(request, 'panel/settings/index.html', ctx)


@panel_view('settings')
def outlet_edit(request, pk=None):
    obj = get_object_or_404(Outlet, pk=pk) if pk else None
    form = OutletForm(request.POST or None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        before = model_snapshot(obj) if obj else None
        saved = form.save()
        audit(request, 'outlet.update' if obj else 'outlet.create', saved, before=before, after=model_snapshot(saved))
        messages.success(request, 'Точка сохранена')
        return redirect('panel:settings-tab', tab='outlets')
    return render(request, 'panel/settings/outlet.html', {'form': form, 'obj': obj, 'tab': 'outlets',
                                                          'tabs': SETTINGS_TABS})


# ---------------------------------------------------------------- сотрудники

@panel_view('staff')
def staff_list(request):
    g = request.GET
    qs = StaffUser.objects.prefetch_related('outlets').order_by('-is_active', 'full_name')
    if g.get('role'):
        qs = qs.filter(role=g['role'])
    if g.get('q'):
        qs = qs.filter(Q(email__icontains=g['q']) | Q(full_name__icontains=g['q']) | Q(phone__icontains=g['q']))
    return render(request, 'panel/staff/list.html', {'users': qs, 'roles': role_choices(), 'f': g})


def _staff_snapshot(u):
    return {'email': u.email, 'full_name': u.full_name, 'role': u.role, 'is_active': u.is_active,
            'phone': u.phone, 'outlets': sorted(u.outlets.values_list('pk', flat=True)) if u.pk else []}


@panel_view('staff')
def staff_edit(request, pk=None):
    obj = get_object_or_404(StaffUser, pk=pk) if pk else None
    form = StaffUserForm(request.POST or None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        if obj and obj.pk == request.user.pk and (not form.cleaned_data['is_active']
                                                  or form.cleaned_data['role'] != Role.OWNER):
            messages.error(request, 'Нельзя отключить себя или снять с себя роль директора')
        else:
            before = _staff_snapshot(obj) if obj else None
            saved = form.save(commit=False)
            director = role_kind(saved.role) == RoleKind.PANEL  # вход в панель по паролю
            if director and form.cleaned_data.get('password') and saved.pk != request.user.pk:
                saved.must_change_password = True  # временный пароль — директор сменит при входе
            if not director:
                saved.must_change_password = False
            saved.save()
            form.save_m2m()
            if not director and form.cleaned_data.get('pin') and obj:
                # PIN сменили — выйти из приложения на всех устройствах
                saved.refresh_tokens.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
            changed = [w for w, k in (('пароль', 'password'), ('PIN', 'pin')) if form.cleaned_data.get(k)]
            audit(request, 'staff.update' if obj else 'staff.create', saved, before=before,
                  after=_staff_snapshot(saved), comment=(', '.join(changed) + ' изменён') if changed else '')
            messages.success(request, 'Сотрудник сохранён')
            return redirect('panel:staff')
    kinds = {r: role_kind(r) for r, _ in role_choices()}
    return render(request, 'panel/staff/edit.html', {'form': form, 'obj': obj, 'role_kinds': kinds})


@require_POST
@panel_view('staff')
def staff_reset_2fa(request, pk):
    obj = get_object_or_404(StaffUser, pk=pk)
    obj.totp_enabled = False
    obj.totp_secret = ''
    obj.save(update_fields=['totp_enabled', 'totp_secret'])
    obj.refresh_tokens.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
    audit(request, 'staff.reset_2fa', obj)
    messages.success(request, f'2FA сброшена — при следующем входе {obj.email} заново настроит приложение')
    return redirect('panel:staff-edit', pk=obj.pk)


# ---------------------------------------------------------------- аудит

@panel_view('audit')
def audit_log(request):
    user = request.user
    g = request.GET
    qs = AuditLog.objects.select_related('actor')
    if not user.can('audit.view_all'):
        qs = qs.filter(actor=user)
    elif g.get('actor'):
        qs = qs.filter(actor_id=g['actor'])
    if g.get('action'):
        qs = qs.filter(action__startswith=g['action'])
    if g.get('object'):
        qs = qs.filter(Q(object_id=g['object']) | Q(object_type__icontains=g['object']))
    if _date(g.get('from')):
        qs = qs.filter(at__gte=_date(g['from']))
    if _date(g.get('to'), True):
        qs = qs.filter(at__lte=_date(g['to'], True))
    return render(request, 'panel/audit/list.html', {
        'page': page(request, qs), 'f': g, 'all': user.can('audit.view_all'),
        'actors': StaffUser.objects.order_by('full_name') if user.can('audit.view_all') else [],
    })


# ---------------------------------------------------------------- роли

def _role_rows():
    from django.db.models import Count

    from apps.staff.models import StaffRole
    counts = dict(StaffUser.objects.values_list('role').annotate(n=Count('id')))
    from apps.staff.roles import DEPARTMENTS
    return [{'role': r, 'users': counts.get(r.pk, 0), 'dept': DEPARTMENTS.get(r.department, ('',))[0],
             'perms': len(PERMISSIONS) if r.pk == Role.OWNER else len(r.permissions or [])}
            for r in sorted(StaffRole.objects.all(),
                            key=lambda r: ({Role.OWNER: 0, Role.STAFF: 1}.get(r.pk, 2), r.name))]


@panel_view('roles')
def roles_list(request):
    return render(request, 'panel/roles/list.html', {'rows': _role_rows(), 'total': len(PERMISSIONS)})


@panel_view('roles')
def role_edit(request, role_id=None):
    """Роль и её права галочками. Директор — все права всегда; у системных ролей нельзя менять код и вход."""
    from apps.common.text import slug_from_title
    from apps.staff.models import StaffRole
    from apps.staff.roles import DEPARTMENTS, PERMISSION_GROUPS
    role = get_object_or_404(StaffRole, pk=role_id) if role_id else None
    locked = role is not None and role.pk == Role.OWNER
    known = set(PERMISSIONS)
    errors = {}
    if request.method == 'POST' and not locked:
        name = (request.POST.get('name') or '').strip()[:60]
        kind = request.POST.get('kind') if role is None or not role.is_system else role.kind
        perms = sorted(p for p in request.POST.getlist('perm') if p in known)
        department = request.POST.get('department') or ''
        if department and department not in DEPARTMENTS:
            errors['department'] = 'Неизвестный отдел'
        if department and any(p in perms for p in ('staff.manage', 'settings.edit')):
            errors['perm'] = 'Роли с отделом нельзя давать управление сотрудниками и настройками'
        if not name:
            errors['name'] = 'Укажите название'
        if kind not in RoleKind.values:
            errors['kind'] = 'Выберите, где работает роль'
        if kind == RoleKind.APP and any(p in perms for p in ('staff.manage', 'settings.edit')):
            errors['perm'] = 'Сотрудникам приложения кассира нельзя давать управление сотрудниками и настройками'
        if not errors:
            before = model_snapshot(role) if role else None
            if role is None:
                role = StaffRole(id=slug_from_title(name, StaffRole, max_length=30, fallback='role'))
            role.name, role.kind, role.permissions, role.department = name, kind, perms, department
            role.save()
            audit(request, 'role.update' if before else 'role.create', role, before=before,
                  after=model_snapshot(role))
            messages.success(request, f'Роль «{role.name}» сохранена')
            return redirect('panel:roles')
    current = set(PERMISSIONS) if locked else set(request.POST.getlist('perm') if request.method == 'POST'
                                                  else (role.permissions if role else []))
    groups = [(title, [(p, label, p in current) for p, label in items]) for title, items in PERMISSION_GROUPS]
    users = StaffUser.objects.filter(role=role.pk).order_by('full_name') if role else []
    return render(request, 'panel/roles/edit.html', {
        'role': role, 'locked': locked, 'groups': groups, 'errors': errors, 'kinds': RoleKind.choices,
        'name': request.POST.get('name', role.name if role else ''),
        'kind': request.POST.get('kind', role.kind if role else RoleKind.PANEL), 'users': users,
        'departments': [(k, v[0]) for k, v in DEPARTMENTS.items()],
        'department': request.POST.get('department', role.department if role else '')})


@require_POST
@panel_view('roles')
def role_delete(request, role_id):
    from apps.staff.models import StaffRole
    role = get_object_or_404(StaffRole, pk=role_id)
    if role.is_system:
        messages.error(request, 'Системную роль удалить нельзя')
    elif StaffUser.objects.filter(role=role.pk).exists():
        messages.error(request, 'У роли есть сотрудники — сначала смените им роль')
    else:
        audit(request, 'role.delete', role, before=model_snapshot(role))
        role.delete()
        messages.success(request, 'Роль удалена')
        return redirect('panel:roles')
    return redirect('panel:role', role_id=role.pk)
