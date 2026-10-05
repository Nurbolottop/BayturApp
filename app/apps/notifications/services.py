"""
Уведомления (ТЗ §5.4): лента под колокольчиком + push (FCM) + realtime.

- Тексты — шаблоны PushTemplate на 3 языках, язык — из settings.language участника.
- Сервисные (кешбек начислен) — по notifyCashback; «заявка отклонена» — всегда;
  рекламные — notifyPromos + согласие на рекламу, не чаще N в месяц.
- Тихие часы 22:00–09:00 для всего, кроме операций с баллами: push откладывается.
"""
import logging
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.common.i18n import iso, tr
from apps.common.models import ProgramSettings
from apps.common.realtime import publish_member

from .models import POINTS_KINDS, Campaign, CampaignStatus, Notification, PushKind, PushTemplate

log = logging.getLogger(__name__)

DEFAULT_TEMPLATES = {
    PushKind.REQUEST_CREDITED: (
        {'ru': 'Кешбек начислен', 'ky': 'Кешбек эсептелди', 'en': 'Cashback credited'},
        {'ru': '+{points} баллов за «{item}»', 'ky': '«{item}» үчүн +{points} упай', 'en': '+{points} points for “{item}”'}),
    PushKind.REQUEST_REJECTED: (
        {'ru': 'Заявка отклонена', 'ky': 'Өтүнмө четке кагылды', 'en': 'Request rejected'},
        {'ru': '«{item}»: {reason}', 'ky': '«{item}»: {reason}', 'en': '“{item}”: {reason}'}),
    PushKind.REQUEST_PAID: (
        {'ru': 'Оплачено баллами', 'ky': 'Упай менен төлөндү', 'en': 'Paid with points'},
        {'ru': '−{points} баллов за «{item}»', 'ky': '«{item}» үчүн −{points} упай', 'en': '−{points} points for “{item}”'}),
    PushKind.TIER_UPGRADED: (
        {'ru': 'Новый уровень!', 'ky': 'Жаңы деңгээл!', 'en': 'New tier!'},
        {'ru': 'Вам открыт уровень «{tier}»', 'ky': 'Сизге «{tier}» деңгээли ачылды', 'en': 'You reached the {tier} tier'}),
    PushKind.TIER_DOWNGRADED: (
        {'ru': 'Ваш уровень — «{tier}»', 'ky': 'Сиздин деңгээл — «{tier}»', 'en': 'Your tier is now {tier}'},
        {'ru': 'В {year} году вы собрали {points} из {limit}. Соберите баллы, чтобы вернуть прежний уровень', 'ky': '{year}-жылы {limit} ичинен {points} чогулттуңуз. Мурунку деңгээлди кайтаруу үчүн упай чогултуңуз', 'en': 'In {year} you collected {points} of {limit}. Earn points to get your tier back'}),
    PushKind.TIER_RETAINED: (
        {'ru': 'Уровень подтверждён', 'ky': 'Деңгээл ырасталды', 'en': 'Tier confirmed'},
        {'ru': 'Уровень «{tier}» остаётся с вами ещё на год', 'ky': '«{tier}» деңгээли дагы бир жылга сизде калат', 'en': 'Your {tier} tier is kept for another year'}),
    PushKind.TIER_AT_RISK: (
        {'ru': 'Подтвердите «{tier}»', 'ky': '«{tier}» деңгээлин ырастаңыз', 'en': 'Confirm your {tier} tier'},
        {'ru': 'Осталось собрать {left} баллов за {days} дн.', 'ky': '{days} күндө дагы {left} упай чогултуу керек', 'en': 'Collect {left} more points in {days} days'}),
    PushKind.ACHIEVEMENT_COMPLETED: (
        {'ru': 'Задание выполнено', 'ky': 'Тапшырма аткарылды', 'en': 'Achievement unlocked'},
        {'ru': '«{achievement}»', 'ky': '«{achievement}»', 'en': '“{achievement}”'}),
    PushKind.POINTS_ADJUSTED: (
        {'ru': 'Баланс изменён', 'ky': 'Баланс өзгөрдү', 'en': 'Balance updated'},
        {'ru': 'Корректировка: {points} баллов', 'ky': 'Оңдоо: {points} упай', 'en': 'Adjustment: {points} points'}),
    PushKind.COMPLAINT_REPLY: (
        {'ru': 'Ответ на обращение {number}', 'ky': '{number} кайрылууга жооп', 'en': 'Reply to request {number}'},
        {'ru': 'Команда BAYTUR ответила на ваше обращение', 'ky': 'BAYTUR командасы жооп берди', 'en': 'The BAYTUR team has replied'}),
}


class _SafeDict(dict):
    def __missing__(self, key):
        return '{' + key + '}'


def render(kind, lang, **params):
    tpl = PushTemplate.objects.filter(pk=kind).first()
    if tpl:
        title, body = tpl.title, tpl.body
    else:
        title, body = DEFAULT_TEMPLATES.get(kind, ({'ru': ''}, {'ru': ''}))
    params = _SafeDict({k: (f'{v:,}'.replace(',', ' ') if isinstance(v, int) else v) for k, v in params.items()})
    return (tr(title, lang) or '').format_map(params), (tr(body, lang) or '').format_map(params)


# ---------------------------------------------------------------- тихие часы

def in_quiet_hours(at, ps=None):
    ps = ps or ProgramSettings.get()
    t = timezone.localtime(at).time()
    start, end = ps.quiet_hours_start, ps.quiet_hours_end
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def quiet_hours_end(at, ps=None):
    ps = ps or ProgramSettings.get()
    local = timezone.localtime(at)
    end = datetime.combine(local.date(), ps.quiet_hours_end, tzinfo=local.tzinfo)
    if end <= local:
        end += timedelta(days=1)
    return end


# ---------------------------------------------------------------- ядро

def notify(member, kind, title, body, data=None, push=True, promo=False, campaign=None, store=True):
    """Сохраняет уведомление в ленту, шлёт realtime и (если разрешено) push."""
    from apps.members.models import MemberStatus
    if member.status != MemberStatus.ACTIVE:
        return None
    data = {'type': kind, **(data or {})}
    n = Notification(member=member, kind=kind, title=title, body=body, data=data, is_promo=promo,
                     campaign=campaign)
    now = timezone.now()
    if push:
        ps = ProgramSettings.get()
        if kind not in POINTS_KINDS and in_quiet_hours(now, ps):
            n.push_status = 'queued'
            n.push_after = quiet_hours_end(now, ps)
        else:
            n.push_status = 'queued'
    if store:
        n.save()
        publish_member(member.pk, 'notification.created', notification_payload(n))
    if push and n.push_after is None:
        transaction.on_commit(lambda: _deliver_async(n))
    return n


def _deliver_async(n):
    """Push уходит из Celery, чтобы HTTP-запрос к FCM не тормозил API; без брокера — сразу."""
    if n.pk and Notification.objects.filter(pk=n.pk).exists():
        from .tasks import deliver_notification
        try:
            deliver_notification.delay(n.pk)
            return
        except Exception:
            log.warning('broker unavailable, delivering push inline')
    deliver(n)


def deliver(n):
    from .push import backend
    devices = list(n.member.devices.all())
    if not devices:
        _set_push_status(n, 'skipped')
        return
    ok_any = False
    for d in devices:
        try:
            ok, invalid = backend().send(d.token, d.platform, n.title, n.body, n.data)
        except Exception:
            log.exception('push failed')
            ok, invalid = False, False
        ok_any = ok_any or ok
        if invalid:
            d.delete()
    _set_push_status(n, 'sent' if ok_any else 'failed')


def _set_push_status(n, status):
    n.push_status = status
    if n.pk and Notification.objects.filter(pk=n.pk).exists():
        Notification.objects.filter(pk=n.pk).update(push_status=status, push_after=None)


def deliver_delayed(now=None):
    now = now or timezone.now()
    count = 0
    for n in Notification.objects.filter(push_status='queued', push_after__lte=now).select_related('member')[:1000]:
        deliver(n)
        count += 1
    return count


def notification_payload(n):
    return {
        'id': n.pk,
        'type': n.kind,
        'title': n.title,
        'body': n.body,
        'data': n.data,
        'createdAt': iso(n.created_at),
        'read': n.read_at is not None,
    }


def purge_old_notifications():
    days = ProgramSettings.get().notification_retention_days
    return Notification.objects.filter(created_at__lt=timezone.now() - timedelta(days=days)).delete()[0]


# ---------------------------------------------------------------- события программы

def _member(member_pk):
    from apps.members.models import Member
    return Member.objects.filter(pk=member_pk).first()


def notify_request_credited(req_id):
    from apps.cashback.models import CashbackRequest
    req = CashbackRequest.objects.select_related('member').get(pk=req_id)
    m = req.member
    if not req.cashback:
        # оплачено целиком баллами — кешбека нет, сообщаем о списании
        title, body = render(PushKind.REQUEST_PAID, m.language, points=req.points,
                             item=tr(req.item_snapshot.get('title'), m.language))
        notify(m, PushKind.REQUEST_PAID, title, body, {'requestId': req.pk, 'points': -req.points},
               push=m.notify_cashback)
        return
    title, body = render(PushKind.REQUEST_CREDITED, m.language, points=req.cashback,
                         item=tr(req.item_snapshot.get('title'), m.language))
    notify(m, PushKind.REQUEST_CREDITED, title, body, {'requestId': req.pk, 'points': req.cashback},
           push=m.notify_cashback)


def notify_request_rejected(req_id):
    from apps.cashback.models import CashbackRequest
    from apps.cashback.serializers import reject_reason_text
    req = CashbackRequest.objects.select_related('member').get(pk=req_id)
    m = req.member
    title, body = render(PushKind.REQUEST_REJECTED, m.language, item=tr(req.item_snapshot.get('title'), m.language),
                         reason=reject_reason_text(req, m.language) or '')
    notify(m, PushKind.REQUEST_REJECTED, title, body, {'requestId': req.pk}, push=True)


def _publish_event(member_pk, kind, data):
    """События уровня и заданий — ещё и отдельным типом в WebSocket /events (§4.3)."""
    publish_member(member_pk, kind, {'type': kind, **data})


def notify_tier_upgraded(member_pk, tier_id, from_tier_id=None):
    from apps.loyalty.models import Tier
    m = _member(member_pk)
    tier = Tier.objects.filter(pk=tier_id).first()
    if not m or not tier:
        return
    data = {'tierId': tier_id, 'tier': tier_id, **({'fromTierId': from_tier_id} if from_tier_id else {})}
    title, body = render(PushKind.TIER_UPGRADED, m.language, tier=tr(tier.name, m.language))
    notify(m, PushKind.TIER_UPGRADED, title, body, data, push=m.notify_cashback)
    _publish_event(m.pk, PushKind.TIER_UPGRADED, data)


def notify_tier_downgraded(member_pk, tier_id, from_tier_id, period_key, collected, limit):
    from apps.loyalty.models import Tier
    m = _member(member_pk)
    tier = Tier.objects.filter(pk=tier_id).first()
    if not m or not tier:
        return
    data = {'tierId': tier_id, 'fromTierId': from_tier_id}
    title, body = render(PushKind.TIER_DOWNGRADED, m.language, tier=tr(tier.name, m.language),
                         year=str(period_key)[:4], points=int(collected), limit=int(limit))
    notify(m, PushKind.TIER_DOWNGRADED, title, body, data, push=True)
    _publish_event(m.pk, PushKind.TIER_DOWNGRADED, data)


def notify_tier_retained(member_pk, tier_id):
    from apps.loyalty.models import Tier
    m = _member(member_pk)
    tier = Tier.objects.filter(pk=tier_id).first()
    if not m or not tier:
        return
    data = {'tierId': tier_id}
    title, body = render(PushKind.TIER_RETAINED, m.language, tier=tr(tier.name, m.language))
    notify(m, PushKind.TIER_RETAINED, title, body, data, push=m.notify_cashback)
    _publish_event(m.pk, PushKind.TIER_RETAINED, data)


def notify_tier_at_risk(member_pk, tier_id, left, days, drop_to=None):
    """Только push (настройка «Акции и события»), в ленту не пишется."""
    from apps.loyalty.models import Tier
    m = _member(member_pk)
    tier = Tier.objects.filter(pk=tier_id).first()
    if not m or not tier or not m.notify_promos:
        return
    data = {'tierId': tier_id, **({'dropTo': drop_to} if drop_to else {})}
    title, body = render(PushKind.TIER_AT_RISK, m.language, tier=tr(tier.name, m.language), left=int(left),
                         days=int(days))
    notify(m, PushKind.TIER_AT_RISK, title, body, data, push=True, store=False)


def notify_achievement_completed(member_pk, achievement_id):
    from apps.loyalty.models import Achievement
    m = _member(member_pk)
    ach = Achievement.objects.filter(pk=achievement_id).first()
    if not m or not ach:
        return
    link = ach.tier_links.filter(tier__deleted_at__isnull=True).order_by('tier__order').first()
    data = {'achievementId': achievement_id, **({'tierId': link.tier_id} if link else {})}
    title, body = render(PushKind.ACHIEVEMENT_COMPLETED, m.language, achievement=tr(ach.title, m.language))
    notify(m, PushKind.ACHIEVEMENT_COMPLETED, title, body, data, push=m.notify_cashback and ach.visible)
    _publish_event(m.pk, PushKind.ACHIEVEMENT_COMPLETED, data)


def notify_points_adjusted(member_pk, points):
    m = _member(member_pk)
    if not m:
        return
    title, body = render(PushKind.POINTS_ADJUSTED, m.language, points=f'{points:+,}'.replace(',', ' '))
    notify(m, PushKind.POINTS_ADJUSTED, title, body, {}, push=m.notify_cashback)


def notify_complaint_reply(complaint):
    m = complaint.member
    title, body = render(PushKind.COMPLAINT_REPLY, m.language, number=complaint.number)
    # сервисный push, не зависит от согласия на рекламу
    notify(m, PushKind.COMPLAINT_REPLY, title, body, {'complaintId': complaint.pk}, push=True)


# ---------------------------------------------------------------- рассылки

def campaign_audience(campaign):
    """Только notifyPromos = true и согласие на рекламу; сегмент: уровни / языки."""
    from apps.members.models import Member, MemberStatus
    qs = Member.objects.filter(status=MemberStatus.ACTIVE, notify_promos=True, marketing_consent=True,
                               is_test=False)
    seg = campaign.segment or {}
    if seg.get('tiers'):
        qs = qs.filter(wallet__tier__in=seg['tiers'])
    if seg.get('languages'):
        qs = qs.filter(language__in=seg['languages'])
    return qs


def promo_sent_this_month(member, now=None):
    now = timezone.localtime(now or timezone.now())
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return Notification.objects.filter(member=member, is_promo=True, created_at__gte=start).count()


def _campaign_data(c):
    data = {'campaignId': c.pk}
    if c.article_id:
        data['articleId'] = c.article_id
    if c.item_id:
        data['itemId'] = c.item_id
    return data


def send_campaign(campaign_id):
    with transaction.atomic():
        c = Campaign.objects.select_for_update().get(pk=campaign_id)
        if c.status not in (CampaignStatus.DRAFT, CampaignStatus.SCHEDULED):
            return c
        c.status = CampaignStatus.SENDING
        c.save(update_fields=['status'])
    limit = ProgramSettings.get().promo_push_monthly_limit
    sent = skipped = 0
    for m in campaign_audience(c).iterator():
        if promo_sent_this_month(m) >= limit:
            skipped += 1
            continue
        notify(m, PushKind.CAMPAIGN, tr(c.title, m.language), tr(c.body, m.language), _campaign_data(c),
               push=True, promo=True, campaign=c)
        sent += 1
    c.status = CampaignStatus.SENT
    c.sent_at = timezone.now()
    c.stats = {'sent': sent, 'skipped': skipped, 'delivered': 0, 'opened': 0}
    c.save(update_fields=['status', 'sent_at', 'stats'])
    return c


def send_campaign_test(campaign, staff):
    """Тестовая отправка себе: на участника с номером телефона сотрудника (если он есть)."""
    from apps.members.models import Member
    m = Member.objects.filter(phone=staff.phone).first() if staff.phone else None
    if not m:
        return None
    return notify(m, PushKind.CAMPAIGN, '[TEST] ' + (tr(campaign.title, m.language) or ''),
                  tr(campaign.body, m.language), _campaign_data(campaign), push=True, promo=False, store=False)


def campaign_stats(c):
    qs = c.notifications.all()
    return {
        'sent': qs.count(),
        'delivered': qs.filter(push_status='sent').count(),
        'opened': qs.filter(opened_at__isnull=False).count(),
        'skipped': (c.stats or {}).get('skipped', 0),
    }


def send_scheduled_campaigns(now=None):
    now = now or timezone.now()
    ids = list(Campaign.objects.filter(status=CampaignStatus.SCHEDULED, scheduled_at__lte=now)
               .values_list('pk', flat=True))
    for cid in ids:
        send_campaign(cid)
    return len(ids)
