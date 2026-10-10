"""Сезон Baytur S&K для всех пользователей: автоматически по датам или вручную — зима / лето."""
from django.contrib import messages
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.common.audit import audit, model_snapshot
from apps.common.models import ProgramSettings

from ..access import panel_view

LABELS = {'': 'автоматически по датам', 'ski': 'зима — Baytur Ski', 'kymyz': 'лето — Baytur Kymyz'}


@require_POST
@panel_view(perm='catalog.edit')
def sk_season(request):
    value = request.POST.get('sk_mode', '')
    if value in LABELS:
        ps = ProgramSettings.get()
        before = model_snapshot(ps)
        ps.sk_mode = value
        ps.save()
        audit(request, 'settings.sk_mode', ps, before=before, after=model_snapshot(ps))
        messages.success(request, f'Сезон Baytur S&K: {LABELS[value]}')
    nxt = request.POST.get('next') or ''
    if not (nxt.startswith('/panel/') and url_has_allowed_host_and_scheme(nxt, {request.get_host()})):
        nxt = '/panel/'
    return redirect(nxt)
