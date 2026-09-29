"""Вход: email + пароль → TOTP (при первом входе — QR для приложения-аутентификатора) → сессия."""
import io

from django.conf import settings
from django.contrib.auth import login, logout
from django.shortcuts import redirect, render
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from apps.common.audit import audit
from apps.common.errors import ApiError
from apps.common.throttling import client_ip
from apps.staff import auth as staff_auth

from ..access import api_error_message, is_staff_user
from ..forms import LoginForm, TotpForm
from ..sections import home_url

SESSION_KEY = 'panel_2fa'


def qr_svg(data):
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode()
    if svg.startswith('<?xml'):
        svg = svg[svg.index('?>') + 2:]
    return mark_safe(svg)


def _next(request):
    nxt = request.POST.get('next') or request.GET.get('next') or ''
    return nxt if nxt.startswith('/panel/') else ''


def login_view(request):
    if is_staff_user(request.user):
        return redirect(_next(request) or home_url(request.user) or 'panel:logout')
    form = LoginForm(request.POST or None)
    error = None
    if request.method == 'POST' and form.is_valid():
        try:
            _, payload = staff_auth.check_password_step(form.cleaned_data['email'], form.cleaned_data['password'],
                                                        client_ip(request))
        except ApiError as e:
            error = api_error_message(e)
        else:
            request.session[SESSION_KEY] = {'token': payload['twoFactorToken'],
                                            'uri': payload.get('otpauthUri'), 'next': _next(request)}
            return redirect('panel:login-2fa')
    return render(request, 'panel/auth/login.html', {'form': form, 'error': error, 'next': _next(request)})


def totp_view(request):
    state = request.session.get(SESSION_KEY)
    if not state:
        return redirect('panel:login')
    form = TotpForm(request.POST or None)
    error = None
    if request.method == 'POST' and form.is_valid():
        code = form.cleaned_data['code'].replace(' ', '')
        try:
            user = staff_auth.check_totp_step(state['token'], code)
        except ApiError as e:
            error = api_error_message(e)
            if e.code == 'token_invalid':
                request.session.pop(SESSION_KEY, None)
                return render(request, 'panel/auth/login.html', {'form': LoginForm(), 'error': error})
        else:
            request.session.pop(SESSION_KEY, None)
            login(request, user, backend=settings.AUTHENTICATION_BACKENDS[0]
                  if getattr(settings, 'AUTHENTICATION_BACKENDS', None)
                  else 'django.contrib.auth.backends.ModelBackend')
            audit(request, 'staff.login', user)
            return redirect(state.get('next') or home_url(user) or 'panel:logout')
    ctx = {'form': form, 'error': error, 'setup': bool(state.get('uri'))}
    if state.get('uri'):
        ctx['qr'] = qr_svg(state['uri'])
        ctx['secret'] = state['uri'].split('secret=')[1].split('&')[0] if 'secret=' in state['uri'] else ''
    return render(request, 'panel/auth/totp.html', ctx)


@require_POST
def logout_view(request):
    logout(request)
    return redirect('panel:login')


def password_view(request):
    """Смена пароля: обязательна после входа с временным паролем, доступна и по желанию."""
    from django.contrib.auth import update_session_auth_hash
    from django.contrib.auth.views import redirect_to_login
    from ..forms import PasswordChangeForm
    if not is_staff_user(request.user):
        return redirect_to_login(request.get_full_path())
    user = request.user
    form = PasswordChangeForm(request.POST or None)
    error = None
    if request.method == 'POST' and form.is_valid():
        try:
            staff_auth.change_password(user, form.cleaned_data['current'], form.cleaned_data['new'])
        except ApiError as e:
            error = api_error_message(e)
        else:
            update_session_auth_hash(request, user)
            audit(request, 'staff.password_change', user)
            from django.contrib import messages
            messages.success(request, 'Пароль изменён')
            return redirect(home_url(user) or 'panel:logout')
    return render(request, 'panel/auth/password.html', {
        'form': form, 'error': error, 'forced': getattr(user, 'must_change_password', False)})
