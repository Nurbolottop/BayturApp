"""
Публичная веб-страница удаления аккаунта без приложения (Google Play): номер → SMS-код → удаление.
Те же сервисы, что и /me/deletion/*. Не раскрывает, зарегистрирован ли номер.
"""
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from apps.common.errors import ApiError, message_for
from apps.common.i18n import parse_accept_language, set_language
from apps.common.models import ProgramSettings
from apps.common.throttling import client_ip

from . import auth, services
from .models import Member, MemberStatus, OtpPurpose


@require_http_methods(['GET', 'POST'])
def delete_account(request):
    lang = request.GET.get('lang') or parse_accept_language(request.headers.get('Accept-Language'))
    set_language(lang)
    ctx = {'step': 'phone', 'lang': lang, 'purge_days': ProgramSettings.get().purge_days}
    if request.method == 'POST':
        step = request.POST.get('step')
        try:
            if step == 'phone':
                phone = auth.normalize_phone(request.POST.get('phone'))
                member = Member.objects.filter(phone=phone, status=MemberStatus.ACTIVE).first()
                if member:
                    auth.request_otp(phone, OtpPurpose.DELETION, ip=client_ip(request))
                request.session['delete_phone'] = phone
                ctx.update(step='code', phone=phone)
            elif step == 'code':
                phone = request.session.get('delete_phone')
                member = Member.objects.filter(phone=phone, status=MemberStatus.ACTIVE).first() if phone else None
                if member is None:
                    raise ApiError('otp_invalid', 400)
                services.deletion_confirm(member, request.POST.get('code'))
                request.session.pop('delete_phone', None)
                ctx.update(step='done')
        except ApiError as e:
            ctx.update(error=message_for(e.code, lang), step=step or 'phone',
                       phone=request.session.get('delete_phone'))
    return render(request, 'members/delete_account.html', ctx)


# ---------------------------------------------------------------- документы приложения

def render_legal_text(text, values):
    """Простая разметка документа → HTML: «## Заголовок», «- пункт», пустая строка — абзац. Всё экранируется."""
    from django.utils.html import escape, urlize
    html, items = [], []

    def flush_items():
        if items:
            html.append('<ul>' + ''.join(f'<li>{i}</li>' for i in items) + '</ul>')
            items.clear()

    class _Safe(dict):
        def __missing__(self, key):
            return '{' + key + '}'

    text = (text or '').format_map(_Safe(values))
    lines = text.replace('\r\n', '\n').split('\n')
    title = escape(lines[0].strip()) if lines and lines[0].strip() and not lines[0].startswith(('#', '-')) else ''
    for line in (lines[1:] if title else lines):
        s = line.strip()
        if not s:
            flush_items()
        elif s.startswith('## '):
            flush_items()
            html.append(f'<h2>{escape(s[3:])}</h2>')
        elif s.startswith('- '):
            items.append(urlize(escape(s[2:])))
        else:
            flush_items()
            html.append(f'<p>{urlize(escape(s))}</p>')
    flush_items()
    return title, ''.join(html)


def legal_page(request, kind):
    """Публичная страница документа (политика, условия) на языке ?lang= — ссылки отдаёт GET /legal."""
    from django.http import Http404
    from django.utils.safestring import mark_safe

    from .models import LegalDocument, LegalKind
    if kind not in (LegalKind.TERMS, LegalKind.PRIVACY):
        raise Http404
    doc = LegalDocument.current(kind)
    lang = request.GET.get('lang') or parse_accept_language(request.headers.get('Accept-Language'))
    lang = lang if lang in ('ru', 'ky', 'en') else 'ru'
    body = (doc.body or {}) if doc else {}
    text = body.get(lang) or body.get('ru')
    if not text:
        raise Http404
    ps = ProgramSettings.get()
    title, html = render_legal_text(text, {'phone': ps.resort_phone, 'whatsapp': ps.resort_whatsapp.lstrip('+'),
                                           'purge_days': ps.purge_days, 'points_per_som': ps.points_per_som})
    return render(request, 'members/legal.html', {
        'lang': lang, 'kind': kind, 'title': title, 'html': mark_safe(html), 'doc': doc})
