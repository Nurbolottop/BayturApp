"""Проверка доступа во view панели: вход, сотрудник, право из реестра разделов или явное право."""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.template.loader import render_to_string

from apps.common.errors import ApiError, message_for

from .sections import BY_KEY


def forbidden(request, reason=''):
    html = render_to_string('panel/403.html', {'reason': reason}, request=request)
    return HttpResponseForbidden(html)


def is_staff_user(user):
    return bool(user and user.is_authenticated and getattr(user, 'is_staff_user', False) and user.is_active)


def panel_view(section=None, perm=None, perms=None, methods=None):
    """
    @panel_view('members')                 — право раздела из реестра
    @panel_view(perm='members.manage')      — явное право
    @panel_view('requests', perms={'POST': 'requests.process'}) — право для метода
    """
    def deco(fn):
        @wraps(fn)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not is_staff_user(user):
                return redirect_to_login(request.get_full_path())
            if getattr(user, 'must_change_password', False):
                # временный пароль: до смены доступны только экран смены пароля и выход
                return redirect('panel:password')
            if section and not BY_KEY[section].allowed(user):
                return forbidden(request)
            if perm and not user.can(perm):
                return forbidden(request)
            if perms and request.method in perms:
                need = perms[request.method]
                need = need if isinstance(need, (list, tuple, set)) else [need]
                if not any(user.can(p) for p in need):
                    return forbidden(request)
            request.panel_section = section
            return fn(request, *args, **kwargs)
        return wrapper
    return deco


def require(request, perm):
    """Внутри view: raise PermissionDeniedPanel, если нет права."""
    if not request.user.can(perm):
        raise PanelForbidden()


class PanelForbidden(Exception):
    pass


def api_error_message(e):
    msg = e.message or message_for(e.code, 'ru')
    extra = getattr(e, 'extra', None) or {}
    fields = extra.get('fields')
    if fields:
        details = '; '.join(f'{k}: {", ".join(map(str, v)) if isinstance(v, (list, tuple)) else v}'
                            for k, v in fields.items())
        msg = f'{msg} ({details})'
    return msg


def run_action(request, fn, success=None, back=None):
    """Выполнить сервис; ApiError → сообщение об ошибке. Возвращает (result, ok)."""
    try:
        result = fn()
    except ApiError as e:
        messages.error(request, api_error_message(e))
        return None, False
    except PanelForbidden:
        messages.error(request, message_for('permission_denied', 'ru'))
        return None, False
    if success:
        messages.success(request, success)
    return result, True


def back_or(request, default):
    nxt = request.POST.get('next') or request.GET.get('next')
    if nxt and nxt.startswith('/panel/'):
        return redirect(nxt)
    return redirect(default)
