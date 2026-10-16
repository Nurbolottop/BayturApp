"""Подарок за первую регистрацию: настройка купона и выданные купоны."""
from django.contrib import messages
from django.db.models import Count
from django.shortcuts import redirect, render

from apps.common.audit import audit, model_snapshot
from apps.coupons.models import Coupon, WelcomeOffer
from apps.coupons.services import status_of

from ..access import panel_view
from ..forms import WelcomeOfferForm


@panel_view('welcome')
def welcome(request):
    offer = WelcomeOffer.get()
    form = WelcomeOfferForm(request.POST or None, instance=offer)
    if request.method == 'POST' and form.is_valid():
        before = model_snapshot(offer)
        saved = form.save()
        audit(request, 'welcome_offer.update', saved, before=before, after=model_snapshot(saved))
        messages.success(request, 'Подарок сохранён' + (' и включён' if saved.enabled else ' (выключен)'))
        return redirect('panel:welcome')
    stats = dict(Coupon.objects.filter(source='welcome').values_list('status').annotate(n=Count('id')))
    recent = list(Coupon.objects.filter(source='welcome').select_related('member', 'redeemed_by')[:50])
    for c in recent:
        c.shown_status = status_of(c)
    return render(request, 'panel/welcome.html', {'form': form, 'offer': offer, 'stats': stats, 'recent': recent})
