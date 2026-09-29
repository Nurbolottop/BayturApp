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
