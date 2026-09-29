"""
Отчёты и аналитика (ТЗ §7.2 «Отчёты», §7.5 «Аналитика», §9.3 «Отчёт» по обращениям).

Чистые функции над ORM: принимают ReportParams, возвращают JSON-сериализуемый dict единой формы

    {"kpis":   [{"key", "label", "value", "prev", "unit"}],
     "series": [{"key", "label", "points": [{"x": "2026-09-01", "y": 123}]}],
     "tables": [{"key", "label", "columns": [{"key", "label"}], "rows": [{...}]}],
     "period": {...}, ...дополнительные ключи блока}

Общие правила:
- тестовые аккаунты (member.is_test / request.is_test / payment.is_test) исключены везде;
- «активный» — реальное действие (заявка, начисление, списание) за 30 дней; заходы в приложение не в счёт;
  удалённые (deactivated) и стёртые (purged) в активных не считаются;
- период — даты по Asia/Bishkek включительно; prev — предыдущий период той же длины.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import (Aggregate, Avg, Count, DateTimeField, Exists, ExpressionWrapper, F, FloatField, Func,
                              Min, OuterRef, Q, Subquery, Sum)
from django.db.models.functions import Coalesce, TruncDay, TruncMonth, TruncWeek
from django.utils import timezone

from apps.cashback.models import CashbackRequest, RejectReason, RequestStatus
from apps.catalog.models import Category, Item, ItemPromo, Outlet, PaymentMethod
from apps.common.models import ProgramSettings
from apps.loyalty.models import Operation, OperationKind, Tier, Wallet
from apps.members.models import Device, Member, MemberStatus

from .models import AppEvent, DeviceLink

GROUPS = ('day', 'week', 'month')
ACTIVE_DAYS = 30
REPEAT_DAYS = 90
CAMPAIGN_WINDOW_DAYS = 7
DONE_STATUSES = (RequestStatus.CONFIRMED, RequestStatus.CREDITED)
REAL_ACTION_KINDS = (OperationKind.CASHBACK, OperationKind.SPEND)
GONE_STATUSES = (MemberStatus.DEACTIVATED, MemberStatus.PURGED)

METHOD_LABELS = {**dict(PaymentMethod.choices), None: 'Только баллы', '': 'Только баллы'}
REJECT_LABELS = dict(RejectReason.choices)


def _tz():
    return timezone.get_default_timezone()


# ============================================================== параметры

def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_bool(value, default=True):
    if value is None or value == '':
        return default
    return str(value).lower() not in ('0', 'false', 'no', 'off')


@dataclass
class ReportParams:
    date_from: date
    date_to: date
    group_by: str = 'day'            # day | week | month
    category: str | None = None
    outlet: str | None = None
    tier: str | None = None
    platform: str | None = None
    language: str | None = None
    compare: bool = True             # также считать предыдущий период той же длины

    def __post_init__(self):
        if self.group_by not in GROUPS:
            self.group_by = 'day'
        if self.date_from > self.date_to:
            self.date_from, self.date_to = self.date_to, self.date_from

    @classmethod
    def from_query(cls, qd) -> 'ReportParams':
        """Из request.GET / query_params: from, to, groupBy, category, outlet, tier, platform, language, compare."""
        qd = qd or {}
        get = qd.get
        today = timezone.localdate()
        date_to = _parse_date(get('to')) or today
        date_from = _parse_date(get('from')) or (date_to - timedelta(days=29))
        return cls(
            date_from=date_from, date_to=date_to, group_by=(get('groupBy') or get('group_by') or 'day'),
            category=get('category') or None, outlet=get('outlet') or None, tier=get('tier') or None,
            platform=get('platform') or None, language=get('language') or None,
            compare=_parse_bool(get('compare'), True),
        )

    def to_query(self) -> dict:
        """Обратно в query-формат (для ExportJob.params)."""
        d = {'from': self.date_from.isoformat(), 'to': self.date_to.isoformat(), 'groupBy': self.group_by,
             'compare': '1' if self.compare else '0'}
        for k in ('category', 'outlet', 'tier', 'platform', 'language'):
            if getattr(self, k):
                d[k] = getattr(self, k)
        return d

    # --- окно
    @property
    def start(self) -> datetime:
        return timezone.make_aware(datetime.combine(self.date_from, time.min), _tz())

    @property
    def end(self) -> datetime:
        """Исключительная граница: начало дня после date_to."""
        return timezone.make_aware(datetime.combine(self.date_to + timedelta(days=1), time.min), _tz())

    @property
    def days(self) -> int:
        return (self.date_to - self.date_from).days + 1

    def previous(self) -> 'ReportParams':
        prev_to = self.date_from - timedelta(days=1)
        return replace(self, date_from=prev_to - timedelta(days=self.days - 1), date_to=prev_to, compare=False)

    def period(self) -> dict:
        d = {'from': self.date_from.isoformat(), 'to': self.date_to.isoformat(), 'groupBy': self.group_by,
             'filters': {k: getattr(self, k) for k in ('category', 'outlet', 'tier', 'platform', 'language')
                         if getattr(self, k)}}
        if self.compare:
            prev = self.previous()
            d['prev'] = {'from': prev.date_from.isoformat(), 'to': prev.date_to.isoformat()}
        return d


# ============================================================== общие помощники

class Seconds(Func):
    """EXTRACT(EPOCH FROM (end - start)) — длительность в секундах (PostgreSQL)."""
    template = 'EXTRACT(EPOCH FROM (%(expressions)s))::float8'
    arg_joiner = ' - '
    output_field = FloatField()


class Percentile(Aggregate):
    """percentile_cont(p) WITHIN GROUP (ORDER BY expr) — медиана и 90-й перцентиль (PostgreSQL)."""
    function = 'PERCENTILE_CONT'
    template = '%(function)s(%(percentile)s) WITHIN GROUP (ORDER BY %(expressions)s)'
    output_field = FloatField()

    def __init__(self, expression, percentile, **extra):
        super().__init__(expression, percentile=float(percentile), **extra)


def _num(v, digits=2):
    if v is None:
        return None
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, timedelta):
        v = v.total_seconds()
    if isinstance(v, float):
        return round(v, digits)
    return v


def _hours(seconds):
    return None if seconds is None else round(float(seconds) / 3600, 2)


def _minutes(seconds):
    return None if seconds is None else round(float(seconds) / 60, 1)


def _ratio(a, b, digits=4):
    if not b:
        return None
    return round(float(a or 0) / float(b), digits)


def _pps():
    return ProgramSettings.get().points_per_som or 100


def _som(points, pps=None):
    return round((points or 0) / (pps or _pps()), 2)


def _l10n(value):
    if isinstance(value, dict):
        return value.get('ru') or next((v for v in value.values() if v), '')
    return value or ''


def _kpis(defs, cur, prev):
    """defs: [(key, label, unit)]; cur/prev — dict значений (prev может быть None)."""
    return [{'key': k, 'label': label, 'value': _num(cur.get(k)),
             'prev': _num(prev.get(k)) if prev is not None else None, 'unit': unit}
            for k, label, unit in defs]


def _with_prev(fn, p):
    """Считает fn(p) и, если compare, fn(p.previous())."""
    return fn(p), (fn(p.previous()) if p.compare else None)


def _table(key, label, columns, rows):
    return {'key': key, 'label': label, 'columns': [{'key': k, 'label': lbl} for k, lbl in columns],
            'rows': [{k: _num(v) for k, v in r.items()} for r in rows]}


def _trunc(p, field):
    cls = {'day': TruncDay, 'week': TruncWeek, 'month': TruncMonth}[p.group_by]
    return cls(field, tzinfo=_tz())


def _bucket_key(p, d: date) -> date:
    if p.group_by == 'week':
        return d - timedelta(days=d.weekday())
    if p.group_by == 'month':
        return d.replace(day=1)
    return d


def _buckets(p):
    out, d = [], _bucket_key(p, p.date_from)
    while d <= p.date_to:
        out.append(d)
        if p.group_by == 'day':
            d += timedelta(days=1)
        elif p.group_by == 'week':
            d += timedelta(days=7)
        else:
            d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def _as_date(v):
    if isinstance(v, datetime):
        return timezone.localtime(v, _tz()).date() if timezone.is_aware(v) else v.date()
    return v


def _series(p, qs, field, key, label, value=None):
    """Ряд по бакетам (пустые бакеты = 0). value — агрегат (по умолчанию Count('pk'))."""
    value = value if value is not None else Count('pk')
    rows = qs.annotate(_b=_trunc(p, field)).values('_b').annotate(_y=value).order_by('_b')
    got = {_as_date(r['_b']): r['_y'] for r in rows}
    return {'key': key, 'label': label,
            'points': [{'x': b.isoformat(), 'y': _num(got.get(b) or 0)} for b in _buckets(p)]}


def _in(p, field):
    return {f'{field}__gte': p.start, f'{field}__lt': p.end}


# --- фильтры по участнику / категории / точке

def _member_filter(qs, p, path='member', use_tier=True, use_language=True, use_platform=True):
    """Исключает тестовых и применяет фильтры tier / language / platform через связь с участником."""
    pre = f'{path}__' if path else ''
    qs = qs.filter(**{f'{pre}is_test': False})
    if use_tier and p.tier:
        qs = qs.filter(**{f'{pre}wallet__tier_id': p.tier})
    if use_language and p.language:
        qs = qs.filter(**{f'{pre}language': p.language})
    if use_platform and p.platform:
        ref = OuterRef(f'{path}_id') if path else OuterRef('pk')
        qs = qs.filter(Exists(Device.objects.filter(member_id=ref, platform=p.platform)))
    return qs


def _requests(p, use_category=True, use_outlet=True):
    qs = CashbackRequest.objects.filter(is_test=False)
    qs = _member_filter(qs, p)
    if use_category and p.category:
        qs = qs.filter(item_snapshot__category=p.category)
    if use_outlet and p.outlet:
        qs = qs.filter(outlet_id=p.outlet)
    return qs


def _operations(p, use_category=True, use_outlet=True):
    qs = _member_filter(Operation.objects.all(), p)
    if use_category and p.category:
        qs = qs.filter(category=p.category)
    if use_outlet and p.outlet:
        qs = qs.filter(request__outlet_id=p.outlet)
    return qs


def _members(p):
    return _member_filter(Member.objects.all(), p, path='')


def _events(p, name=None):
    qs = AppEvent.objects.filter(**_in(p, 'at')).exclude(member__is_test=True)
    if name:
        qs = qs.filter(name__in=[name] if isinstance(name, str) else name)
    if p.platform:
        qs = qs.filter(platform=p.platform)
    if p.language:
        qs = qs.filter(language=p.language)
    return qs


def _active_count(p, at_end=None):
    """Активные за 30 дней до конца периода: реальное действие, не удалены/не стёрты."""
    end = at_end or p.end
    start = end - timedelta(days=ACTIVE_DAYS)
    req = CashbackRequest.objects.filter(member_id=OuterRef('pk'), is_test=False, created_at__gte=start,
                                         created_at__lt=end)
    ops = Operation.objects.filter(member_id=OuterRef('pk'), kind__in=REAL_ACTION_KINDS, at__gte=start, at__lt=end)
    return _members(p).exclude(status__in=GONE_STATUSES).filter(Q(Exists(req)) | Q(Exists(ops))).count()


def _tier_names():
    return {t.id: _l10n(t.name) for t in Tier.objects.all()}


def _category_names():
    return {c.id: _l10n(c.title) for c in Category.objects.all()}


def _outlet_names():
    return {o.id: _l10n(o.name) for o in Outlet.objects.all()}


def _staff_names(ids):
    from apps.staff.models import StaffUser
    return {u.pk: (u.full_name or u.email) for u in StaffUser.objects.filter(pk__in=[i for i in ids if i])}


def _points_totals(p):
    ops = _operations(p).filter(**_in(p, 'at'))
    agg = ops.aggregate(
        credited=Coalesce(Sum('points', filter=Q(kind=OperationKind.CASHBACK)), 0),
        spend=Coalesce(Sum('points', filter=Q(kind=OperationKind.SPEND)), 0),
        refund=Coalesce(Sum('points', filter=Q(kind=OperationKind.REFUND)), 0),
        expired=Coalesce(Sum('points', filter=Q(kind=OperationKind.EXPIRE)), 0),
        forfeit=Coalesce(Sum('points', filter=Q(kind=OperationKind.FORFEIT)), 0),
        adj_plus=Coalesce(Sum('points', filter=Q(kind=OperationKind.ADJUSTMENT, points__gt=0)), 0),
        adj_minus=Coalesce(Sum('points', filter=Q(kind=OperationKind.ADJUSTMENT, points__lt=0)), 0),
    )
    spent = -agg['spend'] - agg['refund']
    return {
        'credited': agg['credited'], 'spent': spent, 'refunded': agg['refund'],
        'expired': -agg['expired'], 'forfeit': -agg['forfeit'], 'burned': -agg['expired'] - agg['forfeit'],
        'adjust_plus': agg['adj_plus'], 'adjust_minus': -agg['adj_minus'],
        'adjust_net': agg['adj_plus'] + agg['adj_minus'],
        'spent_share': _ratio(spent, agg['credited']),
    }


def _money_totals(p):
    qs = _requests(p).filter(status__in=DONE_STATUSES, **_in(p, 'confirmed_at'))
    agg = qs.aggregate(n=Count('pk'), money=Coalesce(Sum('money_som'), 0), s_total=Coalesce(Sum('total'), 0),
                       s_points_som=Coalesce(Sum('points_som'), 0), s_cashback=Coalesce(Sum('cashback'), 0),
                       avg_check=Avg('total'),
                       avg_share=Avg(ExpressionWrapper(F('points_som') * 1.0 / F('total'), FloatField()),
                                     filter=Q(total__gt=0)))
    return {'n': agg['n'], 'money': agg['money'], 'total': agg['s_total'], 'points_som': agg['s_points_som'],
            'cashback': agg['s_cashback'], 'avg_check': agg['avg_check'], 'avg_share': agg['avg_share']}


def _confirm_seconds_avg(p):
    return _requests(p).filter(confirmed_at__isnull=False, **_in(p, 'confirmed_at')) \
        .aggregate(s=Avg(Seconds(F('confirmed_at'), F('created_at'))))['s']


# ============================================================== обязательство

def liability(on_date: date) -> dict:
    """
    Обязательство курорта на конец дня on_date: сумма непотраченных баллов (восстанавливается
    из журнала Operation.at) в баллах и сомах. Тестовые аккаунты не учитываются.
    """
    on_date = _parse_date(on_date) or timezone.localdate()
    end = timezone.make_aware(datetime.combine(on_date + timedelta(days=1), time.min), _tz())
    pps = _pps()
    ops = Operation.objects.filter(at__lt=end, member__is_test=False)
    points = ops.aggregate(s=Coalesce(Sum('points'), 0))['s']
    holders = ops.values('member_id').annotate(s=Sum('points')).filter(s__gt=0).count()
    som = _som(points, pps)
    return {
        'date': on_date.isoformat(), 'points': points, 'som': som, 'members': holders, 'pointsPerSom': pps,
        'kpis': [
            {'key': 'liability_points', 'label': 'Обязательство, баллов', 'value': points, 'prev': None,
             'unit': 'points'},
            {'key': 'liability_som', 'label': 'Обязательство, сом', 'value': som, 'prev': None, 'unit': 'som'},
            {'key': 'holders', 'label': 'Клиентов с баллами', 'value': holders, 'prev': None, 'unit': 'members'},
        ],
        'series': [], 'tables': [],
    }


def expiry_forecast(days_list=(30, 90), now=None) -> dict:
    """Прогноз сгорания: баланс кошельков, у которых срок «N мес. без активности» наступит в ближайшие дни."""
    from apps.loyalty.services import _add_months
    now = now or timezone.now()
    months = ProgramSettings.get().expiry_months
    base = Wallet.objects.filter(balance__gt=0, last_activity_at__isnull=False, member__is_test=False) \
        .exclude(member__status__in=GONE_STATUSES)
    out = {}
    for d in days_list:
        cutoff = _add_months(now + timedelta(days=d), -months)
        agg = base.filter(last_activity_at__lte=cutoff).aggregate(p=Coalesce(Sum('balance'), 0), n=Count('pk'))
        out[d] = {'points': agg['p'], 'members': agg['n']}
    return out


# ============================================================== дашборд (§7.2)

DASHBOARD_KPIS = [
    ('points_credited', 'Начислено баллов', 'points'),
    ('points_spent', 'Списано баллов', 'points'),
    ('revenue', 'Выручка деньгами', 'som'),
    ('requests', 'Заявок создано', 'count'),
    ('requests_done', 'Заявок подтверждено', 'count'),
    ('new_members', 'Новые клиенты', 'members'),
    ('active_members', 'Активные за 30 дней', 'members'),
    ('avg_confirm_minutes', 'Среднее время подтверждения', 'min'),
]


def _dashboard_values(p):
    pts = _points_totals(p)
    money = _money_totals(p)
    return {
        'points_credited': pts['credited'], 'points_spent': pts['spent'], 'revenue': money['money'],
        'requests': _requests(p).filter(**_in(p, 'created_at')).count(), 'requests_done': money['n'],
        'new_members': _members(p).filter(**_in(p, 'created_at')).count(),
        'active_members': _active_count(p),
        'avg_confirm_minutes': _minutes(_confirm_seconds_avg(p)),
    }


def _by_category_table(p):
    names = _category_names()
    rows = _requests(p).filter(status__in=DONE_STATUSES, **_in(p, 'confirmed_at')) \
        .values(cat=F('item_snapshot__category')) \
        .annotate(requests=Count('pk'), revenue=Sum('money_som'), s_total=Sum('total'),
                  s_points_som=Sum('points_som'), s_cashback=Sum('cashback')).order_by('-revenue')
    return _table('by_category', 'По категориям', [
        ('category', 'Категория'), ('requests', 'Заявок'), ('revenue', 'Выручка деньгами, сом'),
        ('total', 'Сумма заявок, сом'), ('points_som', 'Оплачено баллами, сом'), ('cashback', 'Кешбек, баллов')],
        [{'category': names.get(r['cat'], r['cat']), 'category_id': r['cat'], 'requests': r['requests'],
          'revenue': r['revenue'], 'total': r['s_total'], 'points_som': r['s_points_som'],
          'cashback': r['s_cashback']}
         for r in rows])


def _by_method_table(p):
    rows = _requests(p).filter(status__in=DONE_STATUSES, **_in(p, 'confirmed_at')) \
        .values('method').annotate(requests=Count('pk'), revenue=Sum('money_som')) \
        .order_by('-revenue')
    grand = sum(r['revenue'] or 0 for r in rows)
    return _table('by_method', 'По способам оплаты', [
        ('method', 'Способ'), ('requests', 'Заявок'), ('revenue', 'Выручка, сом'), ('share', 'Доля выручки')],
        [{'method': METHOD_LABELS.get(r['method'], r['method']), 'method_id': r['method'] or 'points',
          'requests': r['requests'], 'revenue': r['revenue'], 'share': _ratio(r['revenue'], grand)} for r in rows])


def _tier_distribution(p):
    names = _tier_names()
    qs = Wallet.objects.filter(member__is_test=False).exclude(member__status__in=GONE_STATUSES)
    if p.tier:
        qs = qs.filter(tier_id=p.tier)
    if p.language:
        qs = qs.filter(member__language=p.language)
    if p.platform:
        qs = qs.filter(Exists(Device.objects.filter(member_id=OuterRef('member_id'), platform=p.platform)))
    counts = {r['tier_id']: r['n'] for r in qs.values('tier_id').annotate(n=Count('pk'))}
    total = sum(counts.values())
    rows = [{'tier': names.get(t.id, t.id), 'tier_id': t.id, 'members': counts.get(t.id, 0),
             'share': _ratio(counts.get(t.id, 0), total)} for t in Tier.objects.order_by('from_points')]
    if counts.get(None):
        rows.append({'tier': 'Без уровня', 'tier_id': None, 'members': counts[None],
                     'share': _ratio(counts[None], total)})
    return _table('tiers', 'Распределение по уровням', [
        ('tier', 'Уровень'), ('members', 'Клиентов'), ('share', 'Доля')], rows)


def _staff_table(p):
    base = _requests(p)
    conf = base.filter(confirmed_by__isnull=False, **_in(p, 'confirmed_at')).values(sid=F('confirmed_by')) \
        .annotate(n=Count('pk'), sec=Avg(Seconds(F('confirmed_at'), F('created_at'))),
                  med=Percentile(Seconds(F('confirmed_at'), F('created_at')), 0.5),
                  cash=Coalesce(Sum('money_som', filter=Q(method=PaymentMethod.CASH)), 0))
    rej = base.filter(rejected_by__isnull=False, **_in(p, 'rejected_at')).values(sid=F('rejected_by')) \
        .annotate(n=Count('pk'))
    adj = base.filter(adjusted_by__isnull=False, **_in(p, 'adjusted_at')).values(sid=F('adjusted_by')) \
        .annotate(n=Count('pk'))
    stats = {}
    for r in conf:
        stats.setdefault(r['sid'], {}).update(confirmed=r['n'], avg=r['sec'], med=r['med'], cash=r['cash'])
    for r in rej:
        stats.setdefault(r['sid'], {})['rejected'] = r['n']
    for r in adj:
        stats.setdefault(r['sid'], {})['adjusted'] = r['n']
    names = _staff_names(stats.keys())
    rows = []
    for sid, s in stats.items():
        done = s.get('confirmed', 0) + s.get('rejected', 0)
        rows.append({'staff': names.get(sid, f'#{sid}'), 'staff_id': sid, 'confirmed': s.get('confirmed', 0),
                     'rejected': s.get('rejected', 0), 'adjusted': s.get('adjusted', 0),
                     'reject_share': _ratio(s.get('rejected', 0), done),
                     'avg_confirm_minutes': _minutes(s.get('avg')), 'median_confirm_minutes': _minutes(s.get('med')),
                     'cash_som': s.get('cash', 0)})
    rows.sort(key=lambda r: -(r['confirmed'] + r['rejected']))
    return _table('staff', 'Работа сотрудников', [
        ('staff', 'Сотрудник'), ('confirmed', 'Подтвердил'), ('rejected', 'Отклонил'), ('adjusted', 'Правок суммы'),
        ('reject_share', 'Доля отклонённых'), ('avg_confirm_minutes', 'Ср. время подтверждения, мин'),
        ('median_confirm_minutes', 'Медиана, мин'), ('cash_som', 'Наличных принято, сом')], rows)


def dashboard(p: ReportParams) -> dict:
    """§7.2: баллы, выручка, категории и способы оплаты, клиенты, уровни, время подтверждения, сотрудники, обязательство."""
    cur, prev = _with_prev(_dashboard_values, p)
    liab = liability(p.date_to)
    kpis = _kpis(DASHBOARD_KPIS, cur, prev)
    liab_prev = liability(p.previous().date_to) if p.compare else None
    kpis += [
        {'key': 'liability_points', 'label': 'Обязательство, баллов', 'value': liab['points'],
         'prev': liab_prev['points'] if liab_prev else None, 'unit': 'points'},
        {'key': 'liability_som', 'label': 'Обязательство курорта, сом', 'value': liab['som'],
         'prev': liab_prev['som'] if liab_prev else None, 'unit': 'som'},
    ]
    ops = _operations(p).filter(**_in(p, 'at'))
    done = _requests(p).filter(status__in=DONE_STATUSES, **_in(p, 'confirmed_at'))
    series = [
        _series(p, ops.filter(kind=OperationKind.CASHBACK), 'at', 'points_credited', 'Начислено баллов',
                Sum('points')),
        _series(p, ops.filter(kind=OperationKind.SPEND), 'at', 'points_spent', 'Списано баллов', -Sum('points')),
        _series(p, done, 'confirmed_at', 'revenue', 'Выручка деньгами, сом', Sum('money_som')),
        _series(p, _members(p).filter(**_in(p, 'created_at')), 'created_at', 'new_members', 'Новые клиенты'),
    ]
    return {
        'period': p.period(), 'kpis': kpis, 'series': series,
        'tables': [_by_category_table(p), _by_method_table(p), _tier_distribution(p), _staff_table(p)],
        'liability': {k: liab[k] for k in ('date', 'points', 'som', 'members', 'pointsPerSom')},
    }


# ============================================================== воронка

def _funnel_rows(p):
    """
    Когорта — устройства с первым app_open в периоде. Для каждого: регистрация (registration_completed
    на устройстве или участник, созданный после первого запуска), первая заявка, первый начисленный
    кешбек, повторная заявка в течение 90 дней после первой.
    """
    first_open = AppEvent.objects.filter(name='app_open').exclude(member__is_test=True).values('device_id') \
        .annotate(first=Min('at'))
    if p.platform:
        first_open = first_open.filter(platform=p.platform)
    if p.language:
        first_open = first_open.filter(language=p.language)
    first_open = first_open.filter(first__gte=p.start, first__lt=p.end)
    devices = {r['device_id']: r['first'] for r in first_open}
    if not devices:
        return []
    reg_events = dict(AppEvent.objects.filter(name='registration_completed', device_id__in=devices.keys())
                      .values('device_id').annotate(at=Min('at')).values_list('device_id', 'at'))
    links = dict(DeviceLink.objects.filter(device_id__in=devices.keys(), member__isnull=False)
                 .values_list('device_id', 'member_id'))
    # участники, у которых первый запуск был на этом устройстве (first_device_id), тоже связываем
    for m_id, dev in Member.objects.filter(first_device_id__in=devices.keys()).values_list('pk', 'first_device_id'):
        links.setdefault(dev, m_id)

    members_qs = Member.objects.filter(pk__in=set(links.values()), is_test=False) \
        .annotate(first_req=Min('cashback_requests__created_at', filter=Q(cashback_requests__is_test=False)),
                  first_credit=Min('cashback_requests__credited_at', filter=Q(cashback_requests__is_test=False)))
    if p.tier:
        members_qs = members_qs.filter(wallet__tier_id=p.tier)
    members = {m['pk']: m for m in members_qs.values('pk', 'created_at', 'first_req', 'first_credit')}
    # вторая заявка в течение 90 дней после первой
    if members:
        first_sq = CashbackRequest.objects.filter(member_id=OuterRef('member_id'), is_test=False) \
            .order_by('created_at').values('created_at')[:1]
        second = CashbackRequest.objects.filter(member_id__in=members.keys(), is_test=False) \
            .annotate(first=Subquery(first_sq)) \
            .filter(created_at__gt=F('first'), created_at__lte=F('first') + timedelta(days=REPEAT_DAYS)) \
            .order_by().values('member_id').annotate(second=Min('created_at')).values_list('member_id', 'second')
        for pk, sec in second:
            members[pk]['second_req'] = sec

    rows = []
    for dev, opened in devices.items():
        m = members.get(links.get(dev))
        reg_at = reg_events.get(dev)
        if m is not None and m['created_at'] >= opened - timedelta(minutes=5):
            reg_at = min(reg_at, m['created_at']) if reg_at else m['created_at']
        if p.tier and m is None:
            continue
        row = {'opened': opened, 'registered': reg_at}
        if m is not None and reg_at is not None:
            row.update(first_req=m['first_req'], first_credit=m['first_credit'], second_req=m.get('second_req'))
        rows.append(row)
    return rows


FUNNEL_STEPS = [
    ('opened', 'Первый запуск'),
    ('registered', 'Регистрация'),
    ('first_req', 'Первая заявка'),
    ('first_credit', 'Первый начисленный кешбек'),
    ('second_req', 'Повторная заявка за 90 дней'),
]


def _funnel_values(p):
    rows = _funnel_rows(p)
    steps, prev_key, prev_n = [], None, None
    for key, label in FUNNEL_STEPS:
        reached = [r for r in rows if r.get(key) and (prev_key is None or r.get(prev_key))]
        n = len(reached)
        durations = []
        if prev_key:
            base = 'first_req' if key == 'second_req' else prev_key
            durations = [(r[key] - r[base]).total_seconds() for r in reached if r.get(base) and r[key] >= r[base]]
        steps.append({
            'key': key, 'label': label, 'count': n,
            'conversion': _ratio(n, prev_n) if prev_key else None,
            'conversionFromStart': _ratio(n, len(rows)) if prev_key else None,
            'dropoff': (prev_n - n) if prev_key else None,
            'avgHoursFromPrev': _hours(sum(durations) / len(durations)) if durations else None,
        })
        prev_key, prev_n = key, n
    shown = _events(p, 'login_prompt_shown').values('device_id').distinct().count()
    accepted = _events(p, 'login_prompt_accepted').values('device_id').distinct().count()
    return {'steps': steps, 'login': {'shown': shown, 'accepted': accepted, 'conversion': _ratio(accepted, shown)}}


def funnel(p: ReportParams) -> dict:
    cur, prev = _with_prev(_funnel_values, p)
    prev_counts = {s['key']: s['count'] for s in prev['steps']} if prev else {}
    for s in cur['steps']:
        s['prev'] = prev_counts.get(s['key']) if prev else None
    kpi_cur = {s['key']: s['count'] for s in cur['steps']}
    kpi_cur.update(login_shown=cur['login']['shown'], login_accepted=cur['login']['accepted'],
                   login_conversion=cur['login']['conversion'])
    kpi_prev = None
    if prev:
        kpi_prev = dict(prev_counts, login_shown=prev['login']['shown'], login_accepted=prev['login']['accepted'],
                        login_conversion=prev['login']['conversion'])
    defs = [(k, lbl, 'devices' if k in ('opened', 'registered') else 'members') for k, lbl in FUNNEL_STEPS]
    defs += [('login_shown', 'Увидели окно входа', 'devices'), ('login_accepted', 'Вошли из окна входа', 'devices'),
             ('login_conversion', 'Конверсия окна входа', 'ratio')]
    series = [
        _series(p, _events(p, 'app_open'), 'at', 'app_open_devices', 'Устройства с запуском',
                Count('device_id', distinct=True)),
        _series(p, _members(p).filter(**_in(p, 'created_at')), 'created_at', 'registrations', 'Регистрации'),
        _series(p, _events(p, 'login_prompt_shown'), 'at', 'login_prompt_shown', 'Показы окна входа'),
        _series(p, _events(p, 'login_prompt_accepted'), 'at', 'login_prompt_accepted', 'Входы из окна входа'),
    ]
    table = _table('funnel', 'Воронка', [
        ('label', 'Шаг'), ('count', 'Число'), ('prev', 'Прошлый период'), ('conversion', 'Конверсия с пред. шага'),
        ('conversionFromStart', 'Конверсия с начала'), ('dropoff', 'Отток'),
        ('avgHoursFromPrev', 'Ср. время от пред. шага, ч')], cur['steps'])
    login_table = _table('login_prompt', 'Окно входа', [
        ('shown', 'Увидели'), ('accepted', 'Вошли'), ('conversion', 'Конверсия')], [cur['login']])
    return {'period': p.period(), 'kpis': _kpis(defs, kpi_cur, kpi_prev), 'series': series,
            'tables': [table, login_table], 'steps': cur['steps'], 'login': cur['login']}


# ============================================================== клиенты

MEMBERS_KPIS = [
    ('new', 'Новые клиенты', 'members'),
    ('active', 'Активные за 30 дней', 'members'),
    ('deleted', 'Удалили аккаунт', 'members'),
    ('restored', 'Восстановили аккаунт', 'members'),
    ('upgrades', 'Повысили уровень', 'members'),
    ('total', 'Всего участников', 'members'),
]


def _tier_transitions(p):
    """Переходы между уровнями за период: lifetime на начало и конец периода из журнала."""
    tiers = list(Tier.objects.order_by('from_points'))
    if not tiers:
        return {}

    def tier_of(lifetime):
        cur = tiers[0]
        for t in tiers:
            if t.from_points <= (lifetime or 0):
                cur = t
        return cur.id

    ops = _member_filter(Operation.objects.filter(affects_lifetime=True, points__gt=0), p, use_tier=False)
    rows = ops.values('member_id').annotate(
        before=Coalesce(Sum('points', filter=Q(at__lt=p.start)), 0),
        during=Coalesce(Sum('points', filter=Q(at__gte=p.start, at__lt=p.end)), 0)).filter(during__gt=0)
    moves = {}
    for r in rows:
        a, b = tier_of(r['before']), tier_of(r['before'] + r['during'])
        if a != b and (not p.tier or b == p.tier):
            moves[(a, b)] = moves.get((a, b), 0) + 1
    return moves


def _members_values(p):
    ms = _members(p)
    return {
        'new': ms.filter(**_in(p, 'created_at')).count(),
        'active': _active_count(p),
        'deleted': ms.filter(**_in(p, 'deleted_at')).count(),
        'restored': ms.filter(**_in(p, 'restored_at')).count(),
        'upgrades': sum(_tier_transitions(p).values()),
        'total': ms.filter(created_at__lt=p.end).exclude(status__in=GONE_STATUSES).count(),
    }


def members(p: ReportParams) -> dict:
    cur, prev = _with_prev(_members_values, p)
    ms = _members(p)
    acting = _requests(p).filter(**_in(p, 'created_at'))
    series = [
        _series(p, ms.filter(**_in(p, 'created_at')), 'created_at', 'new', 'Новые клиенты'),
        _series(p, acting, 'created_at', 'acting', 'Клиенты с заявками', Count('member_id', distinct=True)),
        _series(p, ms.filter(**_in(p, 'deleted_at')), 'deleted_at', 'deleted', 'Удалили аккаунт'),
        _series(p, ms.filter(**_in(p, 'restored_at')), 'restored_at', 'restored', 'Восстановили аккаунт'),
    ]
    names = _tier_names()
    moves = _tier_transitions(p)
    trans = _table('tier_transitions', 'Переходы между уровнями', [
        ('from', 'С уровня'), ('to', 'На уровень'), ('members', 'Клиентов')],
        [{'from': names.get(a, a), 'to': names.get(b, b), 'from_id': a, 'to_id': b, 'members': n}
         for (a, b), n in sorted(moves.items(), key=lambda kv: -kv[1])])
    by_lang = _table('languages', 'По языку', [('language', 'Язык'), ('members', 'Клиентов')],
                     [{'language': r['language'], 'members': r['n']} for r in
                      ms.exclude(status__in=GONE_STATUSES).values('language').annotate(n=Count('pk')).order_by('-n')])
    return {'period': p.period(), 'kpis': _kpis(MEMBERS_KPIS, cur, prev), 'series': series,
            'tables': [_tier_distribution(p), trans, by_lang]}


# ============================================================== когорты

def cohorts(p: ReportParams) -> dict:
    """
    Строка — месяц регистрации (месяцы периода), столбцы — доля участников когорты с реальным
    действием в месяце +1…+12 после регистрации.
    """
    tz = _tz()
    first_month = p.date_from.replace(day=1)
    start = timezone.make_aware(datetime.combine(first_month, time.min), tz)
    cohort_members = dict(_members(p).filter(created_at__gte=start, created_at__lt=p.end)
                          .annotate(m=TruncMonth('created_at', tzinfo=tz)).values_list('pk', 'm'))
    sizes = {}
    for m in cohort_members.values():
        sizes[_as_date(m)] = sizes.get(_as_date(m), 0) + 1

    activity = set()
    if cohort_members:
        ids = list(cohort_members.keys())
        for mid, m in CashbackRequest.objects.filter(member_id__in=ids, is_test=False, created_at__gte=start) \
                .annotate(mm=TruncMonth('created_at', tzinfo=tz)).order_by().values_list('member_id', 'mm').distinct():
            activity.add((mid, _as_date(m)))
        for mid, m in Operation.objects.filter(member_id__in=ids, kind__in=REAL_ACTION_KINDS, at__gte=start) \
                .annotate(mm=TruncMonth('at', tzinfo=tz)).order_by().values_list('member_id', 'mm').distinct():
            activity.add((mid, _as_date(m)))

    def month_index(d):
        return d.year * 12 + d.month - 1

    counts = {}
    for mid, act_month in activity:
        c = _as_date(cohort_members[mid])
        k = month_index(act_month) - month_index(c)
        if 1 <= k <= 12:
            counts[(c, k)] = counts.get((c, k), 0) + 1

    today = timezone.localdate()
    months, d = [], first_month
    while d <= p.date_to:
        months.append(d)
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    matrix, rows = [], []
    for c in months:
        size = sizes.get(c, 0)
        cells = []
        for k in range(1, 13):
            elapsed = month_index(today) - month_index(c) >= k
            cells.append(_ratio(counts.get((c, k), 0), size) if (size and elapsed) else None)
        matrix.append({'cohort': c.strftime('%Y-%m'), 'size': size, 'values': cells})
        rows.append({'cohort': c.strftime('%Y-%m'), 'size': size, **{f'm{k}': v for k, v in enumerate(cells, 1)}})
    table = _table('cohorts', 'Удержание по когортам', [('cohort', 'Месяц регистрации'), ('size', 'Размер')]
                   + [(f'm{k}', f'+{k} мес.') for k in range(1, 13)], rows)
    total = sum(sizes.values())
    return {'period': p.period(),
            'kpis': [{'key': 'cohort_members', 'label': 'Участников в когортах', 'value': total, 'prev': None,
                      'unit': 'members'}],
            'series': [], 'tables': [table],
            'cohorts': {'columns': [f'+{k}' for k in range(1, 13)], 'rows': matrix}}


# ============================================================== баллы

POINTS_KPIS = [
    ('credited', 'Начислено', 'points'),
    ('spent', 'Списано', 'points'),
    ('expired', 'Сгорело (неактивность)', 'points'),
    ('forfeit', 'Списано при удалении', 'points'),
    ('adjust_plus', 'Корректировки +', 'points'),
    ('adjust_minus', 'Корректировки −', 'points'),
    ('spent_share', 'Доля потраченных (списано / начислено)', 'ratio'),
]


def points(p: ReportParams) -> dict:
    cur, prev = _with_prev(_points_totals, p)
    kpis = _kpis(POINTS_KPIS, cur, prev)
    liab = liability(p.date_to)
    liab_prev = liability(p.previous().date_to) if p.compare else None
    forecast = expiry_forecast()
    pps = liab['pointsPerSom']
    kpis += [
        {'key': 'liability_points', 'label': 'Обязательство на конец периода, баллов', 'value': liab['points'],
         'prev': liab_prev['points'] if liab_prev else None, 'unit': 'points'},
        {'key': 'liability_som', 'label': 'Обязательство на конец периода, сом', 'value': liab['som'],
         'prev': liab_prev['som'] if liab_prev else None, 'unit': 'som'},
        {'key': 'expiring_30', 'label': 'Сгорит в ближайшие 30 дней', 'value': forecast[30]['points'],
         'prev': None, 'unit': 'points'},
        {'key': 'expiring_90', 'label': 'Сгорит в ближайшие 90 дней', 'value': forecast[90]['points'],
         'prev': None, 'unit': 'points'},
    ]
    ops = _operations(p).filter(**_in(p, 'at'))
    series = [
        _series(p, ops.filter(kind=OperationKind.CASHBACK), 'at', 'credited', 'Начислено', Sum('points')),
        _series(p, ops.filter(kind=OperationKind.SPEND), 'at', 'spent', 'Списано', -Sum('points')),
        _series(p, ops.filter(kind__in=(OperationKind.EXPIRE, OperationKind.FORFEIT)), 'at', 'burned', 'Сгорело',
                -Sum('points')),
        _series(p, ops.filter(kind=OperationKind.ADJUSTMENT), 'at', 'adjustments', 'Корректировки (нетто)',
                Sum('points')),
    ]
    names = _category_names()
    by_cat = ops.values('category').annotate(
        credited=Coalesce(Sum('points', filter=Q(kind=OperationKind.CASHBACK)), 0),
        spent=Coalesce(-Sum('points', filter=Q(kind=OperationKind.SPEND)), 0)).order_by('-credited')
    kinds = dict(OperationKind.choices)
    by_kind = ops.values('kind').annotate(n=Count('pk'), s=Sum('points')).order_by('kind')
    tables = [
        _table('by_category', 'Баллы по категориям', [
            ('category', 'Категория'), ('credited', 'Начислено'), ('spent', 'Списано'), ('spent_share', 'Доля')],
            [{'category': names.get(r['category'], r['category'] or '—'), 'credited': r['credited'],
              'spent': r['spent'], 'spent_share': _ratio(r['spent'], r['credited'])} for r in by_cat]),
        _table('by_kind', 'Операции по видам', [
            ('kind', 'Вид'), ('operations', 'Операций'), ('points', 'Баллов'), ('som', 'Сом')],
            [{'kind': kinds.get(r['kind'], r['kind']), 'kind_id': r['kind'], 'operations': r['n'],
              'points': r['s'], 'som': _som(r['s'], pps)} for r in by_kind]),
        _table('expiry_forecast', 'Прогноз сгорания', [
            ('days', 'Горизонт, дней'), ('points', 'Баллов'), ('som', 'Сом'), ('members', 'Клиентов')],
            [{'days': d, 'points': v['points'], 'som': _som(v['points'], pps), 'members': v['members']}
             for d, v in forecast.items()]),
    ]
    return {'period': p.period(), 'kpis': kpis, 'series': series, 'tables': tables,
            'liability': {k: liab[k] for k in ('date', 'points', 'som', 'members', 'pointsPerSom')},
            'forecast': {str(d): v for d, v in forecast.items()}}


# ============================================================== деньги

MONEY_KPIS = [
    ('revenue', 'Выручка деньгами', 'som'),
    ('total', 'Сумма заявок', 'som'),
    ('requests', 'Подтверждённых заявок', 'count'),
    ('avg_check', 'Средний чек', 'som'),
    ('points_share', 'Доля оплаты баллами', 'ratio'),
    ('cashback_som', 'Начисленный кешбек, сом', 'som'),
    ('program_cost', 'Стоимость программы (кешбек / выручка)', 'ratio'),
    ('online_paid', 'Оплачено онлайн', 'som'),
    ('online_refunded', 'Возвраты онлайн', 'som'),
]


def _payments(p):
    from apps.payments.models import Payment
    qs = _member_filter(Payment.objects.filter(is_test=False), p)
    if p.category:
        qs = qs.filter(request__item_snapshot__category=p.category)
    if p.outlet:
        qs = qs.filter(request__outlet_id=p.outlet)
    return qs


def _money_values(p):
    agg = _money_totals(p)
    pps = _pps()
    credited = _operations(p).filter(kind=OperationKind.CASHBACK, **_in(p, 'at')) \
        .aggregate(s=Coalesce(Sum('points'), 0))['s']
    pay = _payments(p).filter(paid_at__isnull=False, **_in(p, 'paid_at')) \
        .aggregate(paid=Coalesce(Sum('amount'), 0), refunded=Coalesce(Sum('refunded_amount'), 0))
    cashback_som = _som(credited, pps)
    return {
        'revenue': agg['money'], 'total': agg['total'], 'requests': agg['n'], 'avg_check': agg['avg_check'],
        'points_share': _ratio(agg['points_som'], agg['total']), 'avg_points_share': agg['avg_share'],
        'cashback_som': cashback_som, 'program_cost': _ratio(cashback_som, agg['money']),
        'online_paid': pay['paid'], 'online_refunded': pay['refunded'],
    }


def money(p: ReportParams) -> dict:
    cur, prev = _with_prev(_money_values, p)
    done = _requests(p).filter(status__in=DONE_STATUSES, **_in(p, 'confirmed_at'))
    series = [
        _series(p, done, 'confirmed_at', 'revenue', 'Выручка деньгами, сом', Sum('money_som')),
        _series(p, done, 'confirmed_at', 'points_som', 'Оплачено баллами, сом', Sum('points_som')),
        _series(p, done, 'confirmed_at', 'avg_check', 'Средний чек, сом', Avg('total')),
    ]
    pay_rows = _payments(p).filter(paid_at__isnull=False, **_in(p, 'paid_at')).values('method') \
        .annotate(n=Count('pk'), paid=Sum('amount'), refunded=Sum('refunded_amount')).order_by('-paid')
    orphans = _payments(p).filter(paid_at__isnull=False, request__isnull=True, **_in(p, 'paid_at')) \
        .aggregate(n=Count('pk'), s=Coalesce(Sum('amount'), 0))
    tables = [
        _by_method_table(p),
        _by_category_table(p),
        _table('online_payments', 'Онлайн-платежи', [
            ('method', 'Провайдер'), ('payments', 'Платежей'), ('paid', 'Оплачено, сом'),
            ('refunded', 'Возвращено, сом')],
            [{'method': METHOD_LABELS.get(r['method'], r['method']), 'payments': r['n'], 'paid': r['paid'],
              'refunded': r['refunded']} for r in pay_rows]),
    ]
    kpis = _kpis(MONEY_KPIS + [('avg_points_share', 'Средняя доля баллов в заявке', 'ratio')], cur, prev)
    return {'period': p.period(), 'kpis': kpis, 'series': series, 'tables': tables,
            'orphanPayments': {'count': orphans['n'], 'som': orphans['s']}}


# ============================================================== каталог и акции

def _promo_effect(p):
    """Акции, пересекающиеся с периодом: заявки в дни акции против равного периода до неё + доп. кешбек."""
    now = timezone.now()
    pps = _pps()
    promos = ItemPromo.objects.select_related('item__category').filter(
        Q(starts_at__isnull=True) | Q(starts_at__lt=p.end), Q(ends_at__isnull=True) | Q(ends_at__gt=p.start))
    if p.category:
        promos = promos.filter(item__category_id=p.category)
    if p.outlet:
        promos = promos.filter(item__outlet_id=p.outlet)
    rows = []
    for promo in promos[:100]:
        start = promo.starts_at or promo.created_at
        end = min(promo.ends_at or now, now)
        if end <= start:
            continue
        span = end - start
        base = _requests(p, use_category=False, use_outlet=False).filter(item_id=promo.item_id) \
            .exclude(status=RequestStatus.CANCELLED)
        during = base.filter(created_at__gte=start, created_at__lt=end)
        before = base.filter(created_at__gte=start - span, created_at__lt=start)
        d_agg = during.aggregate(n=Count('pk'), money=Coalesce(Sum('money_som', filter=Q(status__in=DONE_STATUSES)), 0),
                                 s_cashback=Coalesce(Sum('cashback', filter=Q(status__in=DONE_STATUSES)), 0),
                                 weighted=Sum(ExpressionWrapper(F('money_som') * F('rate'), FloatField()),
                                              filter=Q(status__in=DONE_STATUSES)))
        b_agg = before.aggregate(n=Count('pk'), money=Coalesce(Sum('money_som', filter=Q(status__in=DONE_STATUSES)), 0))
        base_rate = float(promo.item.category.rate)
        # доп. кешбек = Σ money × (ставка заявки − базовая ставка категории) × курс
        extra = max(0.0, (float(d_agg['weighted'] or 0) - d_agg['money'] * base_rate) * pps)
        rows.append({
            'item': _l10n(promo.item.title), 'item_id': promo.item_id, 'promo_id': promo.pk,
            'rate': float(promo.rate), 'base_rate': base_rate,
            'starts': timezone.localtime(start).date().isoformat(), 'ends': timezone.localtime(end).date().isoformat(),
            'requests_during': d_agg['n'], 'requests_before': b_agg['n'],
            'uplift': _ratio(d_agg['n'] - b_agg['n'], b_agg['n']),
            'revenue_during': d_agg['money'], 'revenue_before': b_agg['money'],
            'cashback_during': d_agg['s_cashback'], 'extra_cashback_points': round(extra),
            'extra_cashback_som': _som(extra, pps),
        })
    return _table('promo_effect', 'Эффект акций', [
        ('item', 'Услуга'), ('starts', 'Начало'), ('ends', 'Конец'), ('rate', 'Ставка акции'),
        ('base_rate', 'Базовая ставка'), ('requests_during', 'Заявок в акцию'),
        ('requests_before', 'Заявок до акции'), ('uplift', 'Прирост'), ('revenue_during', 'Выручка в акцию, сом'),
        ('revenue_before', 'Выручка до акции, сом'), ('extra_cashback_points', 'Доп. кешбек, баллов'),
        ('extra_cashback_som', 'Доп. кешбек, сом')], rows)


def _catalog_values(p):
    created = _requests(p).filter(**_in(p, 'created_at'))
    done = _requests(p).filter(status__in=DONE_STATUSES, **_in(p, 'confirmed_at'))
    agg = done.aggregate(money=Coalesce(Sum('money_som'), 0), s_total=Coalesce(Sum('total'), 0))
    return {'requests': created.count(), 'requests_done': done.count(), 'revenue': agg['money'],
            'total': agg['s_total'], 'items': done.values('item_id').distinct().count()}


def catalog(p: ReportParams) -> dict:
    cur, prev = _with_prev(_catalog_values, p)
    kpis = _kpis([('requests', 'Заявок создано', 'count'), ('requests_done', 'Заявок подтверждено', 'count'),
                  ('revenue', 'Выручка деньгами', 'som'), ('total', 'Сумма заявок', 'som'),
                  ('items', 'Услуг с заявками', 'count')], cur, prev)
    created = _requests(p).filter(**_in(p, 'created_at'))
    done = _requests(p).filter(status__in=DONE_STATUSES, **_in(p, 'confirmed_at'))
    series = [_series(p, created, 'created_at', 'requests', 'Заявок создано'),
              _series(p, done, 'confirmed_at', 'revenue', 'Выручка деньгами, сом', Sum('money_som'))]
    created_by_item = dict(created.values('item_id').annotate(n=Count('pk')).values_list('item_id', 'n'))
    items = {i.pk: i for i in Item.objects.select_related('category', 'outlet')}
    outlets = _outlet_names()
    cats = _category_names()
    item_rows = []
    for r in done.values('item_id').annotate(n=Count('pk'), money=Sum('money_som'), s_total=Sum('total'),
                                              s_cashback=Sum('cashback')).order_by('-money'):
        it = items.get(r['item_id'])
        item_rows.append({'item': _l10n(it.title) if it else r['item_id'], 'item_id': r['item_id'],
                          'category': cats.get(it.category_id) if it else None,
                          'outlet': outlets.get(it.outlet_id) if it else None,
                          'requests': created_by_item.get(r['item_id'], 0), 'confirmed': r['n'],
                          'revenue': r['money'], 'total': r['s_total'], 'cashback': r['s_cashback']})
    seen = {r['item_id'] for r in item_rows}
    for iid, n in created_by_item.items():
        if iid not in seen:
            it = items.get(iid)
            item_rows.append({'item': _l10n(it.title) if it else iid, 'item_id': iid,
                              'category': cats.get(it.category_id) if it else None,
                              'outlet': outlets.get(it.outlet_id) if it else None, 'requests': n, 'confirmed': 0,
                              'revenue': 0, 'total': 0, 'cashback': 0})
    cols = [('item', 'Услуга'), ('category', 'Категория'), ('outlet', 'Точка'), ('requests', 'Заявок'),
            ('confirmed', 'Подтверждено'), ('revenue', 'Выручка деньгами, сом'), ('total', 'Сумма, сом'),
            ('cashback', 'Кешбек, баллов')]
    top = sorted(item_rows, key=lambda r: -(r['revenue'] or 0))[:10]
    return {'period': p.period(), 'kpis': kpis, 'series': series, 'tables': [
        _by_category_table(p),
        _table('items', 'Заявки и выручка по услугам', cols, item_rows),
        _table('top_items', 'Топ-10 услуг по выручке', cols, top),
        _promo_effect(p),
    ]}


# ============================================================== контент и push

def _content_values(p):
    ev = _events(p)
    starts = ev.filter(name='cashback_flow_started', props__source__in=['story', 'article'])
    submitted = ev.filter(name='cashback_flow_submitted', props__source__in=['story', 'article'])
    return {
        'article_views': ev.filter(name='article_view').count(),
        'promo_clicks': ev.filter(name='promo_click').count(),
        'story_views': ev.filter(name='story_view').values('device_id', 'props__category').distinct().count(),
        'cta_clicks': starts.count(),
        'cta_requests': submitted.count(),
        'push_opened': ev.filter(name='push_opened').count(),
    }


def _campaign_table(p):
    from apps.notifications.models import Campaign, Notification
    campaigns = Campaign.objects.filter(Q(**_in(p, 'sent_at')) | Q(notifications__created_at__gte=p.start,
                                                                    notifications__created_at__lt=p.end)).distinct()
    ids = list(campaigns.values_list('pk', flat=True)[:200])
    if not ids:
        return _table('campaigns', 'Push-рассылки', [], [])
    conv = CashbackRequest.objects.filter(
        member_id=OuterRef('member_id'), is_test=False, created_at__gte=OuterRef('created_at'),
        created_at__lt=ExpressionWrapper(OuterRef('created_at') + timedelta(days=CAMPAIGN_WINDOW_DAYS),
                                         output_field=DateTimeField()))
    notifs = _member_filter(Notification.objects.filter(campaign_id__in=ids), p).annotate(conv=Exists(conv))
    stats = {r['campaign_id']: r for r in notifs.values('campaign_id').annotate(
        sent=Count('pk'), delivered=Count('pk', filter=Q(push_status='sent')),
        opened=Count('pk', filter=Q(opened_at__isnull=False)),
        converted=Count('pk', filter=Q(conv=True)))}
    rows = []
    for c in Campaign.objects.filter(pk__in=ids).order_by('-sent_at', '-created_at'):
        s = stats.get(c.pk, {})
        sent = s.get('sent', 0)
        rows.append({'campaign': _l10n(c.title) or f'#{c.pk}', 'campaign_id': c.pk,
                     'sent_at': timezone.localtime(c.sent_at).isoformat() if c.sent_at else None,
                     'sent': sent, 'delivered': s.get('delivered', 0), 'opened': s.get('opened', 0),
                     'requests_7d': s.get('converted', 0), 'open_rate': _ratio(s.get('opened', 0), s.get('delivered')),
                     'conversion': _ratio(s.get('converted', 0), sent)})
    return _table('campaigns', 'Push-рассылки', [
        ('campaign', 'Рассылка'), ('sent_at', 'Отправлена'), ('sent', 'Отправлено'), ('delivered', 'Доставлено'),
        ('opened', 'Открыто'), ('open_rate', 'Открываемость'), ('requests_7d', 'Заявки за 7 дней'),
        ('conversion', 'Конверсия в заявку')], rows)


def content(p: ReportParams) -> dict:
    """
    Досмотр сторис — устройство дошло до последнего слайда (props.slide ≥ числа слайдов − 1,
    нумерация с 0) или прислало props.kind = 'complete'.
    """
    from apps.content.models import Article, Promo, Story
    cur, prev = _with_prev(_content_values, p)
    kpis = _kpis([('article_views', 'Просмотры статей', 'count'), ('promo_clicks', 'Нажатия на баннеры', 'count'),
                  ('story_views', 'Просмотры сторис', 'count'),
                  ('cta_clicks', '«Получить кешбек» из сторис и статей', 'count'),
                  ('cta_requests', 'Из них стали заявками', 'count'), ('push_opened', 'Открытия push', 'count')],
                 cur, prev)
    ev = _events(p)
    series = [
        _series(p, ev.filter(name='article_view'), 'at', 'article_views', 'Просмотры статей'),
        _series(p, ev.filter(name='promo_click'), 'at', 'promo_clicks', 'Нажатия на баннеры'),
        _series(p, ev.filter(name='story_view'), 'at', 'story_views', 'Просмотры сторис (слайды)'),
    ]
    titles = {a.pk: _l10n(a.title) for a in Article.objects.all()}
    art = ev.filter(name='article_view').values(aid=F('props__articleId')) \
        .annotate(views=Count('pk'), devices=Count('device_id', distinct=True)).order_by('-views')
    promo_titles = {str(pr.pk): titles.get(pr.article_id, pr.article_id) for pr in Promo.objects.all()}
    promo_titles.update({str(pr.article_id): titles.get(pr.article_id, pr.article_id) for pr in Promo.objects.all()})
    promos = ev.filter(name='promo_click').values(pid=F('props__promoId')) \
        .annotate(clicks=Count('pk'), devices=Count('device_id', distinct=True)).order_by('-clicks')

    cats = _category_names()
    slides = {s.category_id: s.slides.count() for s in Story.objects.all()}
    story_rows = []
    sv = ev.filter(name='story_view')
    for r in sv.values(cat=F('props__category')).annotate(views=Count('device_id', distinct=True)).order_by('-views'):
        n = slides.get(r['cat'], 0)
        completed_q = Q(props__kind__in=['complete', 'completed'])
        if n:
            completed_q |= Q(props__slide__gte=max(0, n - 1))
        completed = sv.filter(props__category=r['cat']).filter(completed_q).values('device_id').distinct().count()
        story_rows.append({'story': cats.get(r['cat'], r['cat']), 'category_id': r['cat'], 'slides': n,
                           'viewers': r['views'], 'completed': completed,
                           'completion': _ratio(completed, r['views'])})
    cta_rows = []
    for src, label in (('story', 'Сторис'), ('article', 'Статьи')):
        clicks = ev.filter(name='cashback_flow_started', props__source=src).count()
        subm = ev.filter(name='cashback_flow_submitted', props__source=src).count()
        cta_rows.append({'source': label, 'clicks': clicks, 'requests': subm, 'conversion': _ratio(subm, clicks)})
    tables = [
        _table('articles', 'Просмотры статей', [('article', 'Статья'), ('views', 'Просмотров'),
                                                ('devices', 'Устройств')],
               [{'article': titles.get(r['aid'], r['aid']), 'article_id': r['aid'], 'views': r['views'],
                 'devices': r['devices']} for r in art]),
        _table('promos', 'Нажатия на баннеры акций', [('promo', 'Акция'), ('clicks', 'Нажатий'),
                                                      ('devices', 'Устройств')],
               [{'promo': promo_titles.get(str(r['pid']), r['pid']), 'promo_id': r['pid'], 'clicks': r['clicks'],
                 'devices': r['devices']} for r in promos]),
        _table('stories', 'Сторис: просмотры и досмотры', [
            ('story', 'Сторис'), ('viewers', 'Посмотрели'), ('completed', 'Досмотрели'),
            ('completion', 'Доля досмотров')], story_rows),
        _table('cta', '«Получить кешбек» из контента', [
            ('source', 'Источник'), ('clicks', 'Нажатий'), ('requests', 'Стали заявками'),
            ('conversion', 'Конверсия')], cta_rows),
        _campaign_table(p),
    ]
    return {'period': p.period(), 'kpis': kpis, 'series': series, 'tables': tables}


# ============================================================== работа курорта

def _operations_values(p):
    base = _requests(p)
    confirmed = base.filter(confirmed_at__isnull=False, **_in(p, 'confirmed_at'))
    secs = Seconds(F('confirmed_at'), F('created_at'))
    agg = confirmed.aggregate(n=Count('pk'), avg=Avg(secs), med=Percentile(secs, 0.5), p90=Percentile(secs, 0.9))
    rejected = base.filter(**_in(p, 'rejected_at')).count()
    adjusted = base.filter(original_total__isnull=False, **_in(p, 'adjusted_at')).count()
    closed = agg['n'] + rejected
    return {'confirmed': agg['n'], 'rejected': rejected, 'reject_share': _ratio(rejected, closed),
            'adjusted': adjusted, 'adjust_share': _ratio(adjusted, closed),
            'avg_confirm_minutes': _minutes(agg['avg']), 'median_confirm_minutes': _minutes(agg['med']),
            'p90_confirm_minutes': _minutes(agg['p90'])}


def _by_outlet_table(p):
    base = _requests(p)
    secs = Seconds(F('confirmed_at'), F('created_at'))
    conf = {r['outlet_id']: r for r in base.filter(confirmed_at__isnull=False, **_in(p, 'confirmed_at'))
            .values('outlet_id').annotate(n=Count('pk'), med=Percentile(secs, 0.5), p90=Percentile(secs, 0.9))}
    rej = dict(base.filter(**_in(p, 'rejected_at')).values('outlet_id').annotate(n=Count('pk'))
               .values_list('outlet_id', 'n'))
    adj = {r['outlet_id']: r for r in base.filter(original_total__isnull=False, **_in(p, 'adjusted_at'))
           .values('outlet_id').annotate(n=Count('pk'), diff=Sum(F('total') - F('original_total')))}
    names = _outlet_names()
    rows = []
    for oid in set(conf) | set(rej) | set(adj):
        c = conf.get(oid, {})
        n_conf, n_rej = c.get('n', 0), rej.get(oid, 0)
        rows.append({'outlet': names.get(oid, oid or '—'), 'outlet_id': oid, 'confirmed': n_conf,
                     'rejected': n_rej, 'reject_share': _ratio(n_rej, n_conf + n_rej),
                     'adjusted': adj.get(oid, {}).get('n', 0), 'adjust_diff_som': adj.get(oid, {}).get('diff', 0),
                     'median_confirm_minutes': _minutes(c.get('med')), 'p90_confirm_minutes': _minutes(c.get('p90'))})
    rows.sort(key=lambda r: -(r['confirmed'] + r['rejected']))
    return _table('by_outlet', 'По точкам', [
        ('outlet', 'Точка'), ('confirmed', 'Подтверждено'), ('rejected', 'Отклонено'),
        ('reject_share', 'Доля отклонённых'), ('adjusted', 'Правок суммы'), ('adjust_diff_som', 'Изменение суммы, сом'),
        ('median_confirm_minutes', 'Медиана подтверждения, мин'), ('p90_confirm_minutes', '90 % заявок, мин')], rows)


def operations(p: ReportParams) -> dict:
    cur, prev = _with_prev(_operations_values, p)
    kpis = _kpis([('confirmed', 'Подтверждено заявок', 'count'), ('rejected', 'Отклонено заявок', 'count'),
                  ('reject_share', 'Доля отклонённых', 'ratio'), ('adjusted', 'Правок суммы', 'count'),
                  ('median_confirm_minutes', 'Медиана подтверждения', 'min'),
                  ('p90_confirm_minutes', '90 % заявок подтверждены за', 'min'),
                  ('avg_confirm_minutes', 'Среднее время подтверждения', 'min')], cur, prev)
    base = _requests(p)
    series = [
        _series(p, base.filter(confirmed_at__isnull=False, **_in(p, 'confirmed_at')), 'confirmed_at',
                'median_confirm_minutes', 'Медиана подтверждения, мин',
                Percentile(Seconds(F('confirmed_at'), F('created_at')), 0.5) / 60.0),
        _series(p, base.filter(**_in(p, 'rejected_at')), 'rejected_at', 'rejected', 'Отклонено'),
    ]
    reasons = base.filter(**_in(p, 'rejected_at')).values('reject_code').annotate(n=Count('pk')).order_by('-n')
    total_rej = sum(r['n'] for r in reasons)
    reasons_table = _table('reject_reasons', 'Причины отклонения', [
        ('reason', 'Причина'), ('count', 'Заявок'), ('share', 'Доля')],
        [{'reason': REJECT_LABELS.get(r['reject_code'], r['reject_code'] or '—'), 'code': r['reject_code'],
          'count': r['n'], 'share': _ratio(r['n'], total_rej)} for r in reasons])
    comp = complaints_report(replace(p, compare=False))
    return {'period': p.period(), 'kpis': kpis + [k for k in comp['kpis'] if k['key'] in (
        'complaints', 'avg_first_response_hours', 'avg_rating')], 'series': series,
        'tables': [_by_outlet_table(p), _staff_table(p), reasons_table] + comp['tables']}


# ============================================================== обращения (§9.3)

def _complaints_qs(p):
    from apps.complaints.models import Complaint
    qs = _member_filter(Complaint.objects.all(), p).filter(**_in(p, 'created_at'))
    if p.outlet:
        qs = qs.filter(outlet_id=p.outlet)
    if p.category:
        qs = qs.filter(category_id=p.category)
    return qs


def _complaints_values(p):
    qs = _complaints_qs(p)
    agg = qs.aggregate(
        n=Count('pk'), closed=Count('pk', filter=Q(closed_at__isnull=False)),
        first=Avg(Seconds(F('first_reply_at'), F('created_at')), filter=Q(first_reply_at__isnull=False)),
        resolve=Avg(Seconds(F('closed_at'), F('created_at')), filter=Q(closed_at__isnull=False)),
        s_rating=Avg('rating'), rated=Count('pk', filter=Q(rating__isnull=False)),
        overdue=Count('pk', filter=Q(due_at__isnull=False) & (
            Q(first_reply_at__gt=F('due_at')) | Q(first_reply_at__isnull=True, due_at__lt=timezone.now()))),
    )
    return {'complaints': agg['n'], 'closed': agg['closed'], 'avg_first_response_hours': _hours(agg['first']),
            'avg_resolution_hours': _hours(agg['resolve']), 'avg_rating': _num(agg['s_rating']),
            'rated': agg['rated'], 'overdue': agg['overdue']}


def complaints_report(p: ReportParams) -> dict:
    """§9.3: число обращений по темам и точкам, среднее время первого ответа и решения, средняя оценка."""
    from apps.complaints.models import ComplaintCategory
    cur, prev = _with_prev(_complaints_values, p)
    kpis = _kpis([('complaints', 'Обращений', 'count'), ('closed', 'Закрыто', 'count'),
                  ('overdue', 'Первый ответ с просрочкой', 'count'),
                  ('avg_first_response_hours', 'Среднее время первого ответа', 'h'),
                  ('avg_resolution_hours', 'Среднее время решения', 'h'), ('avg_rating', 'Средняя оценка', 'score')],
                 cur, prev)
    qs = _complaints_qs(p)
    group_aggs = dict(
        n=Count('pk'),
        first=Avg(Seconds(F('first_reply_at'), F('created_at')), filter=Q(first_reply_at__isnull=False)),
        resolve=Avg(Seconds(F('closed_at'), F('created_at')), filter=Q(closed_at__isnull=False)),
        s_rating=Avg('rating'))
    cat_names = {c.pk: _l10n(c.title) for c in ComplaintCategory.objects.all()}
    outlets = _outlet_names()

    def rows(field, names):
        return [{'name': names.get(r[field], r[field] or '—'), 'id': r[field], 'complaints': r['n'],
                 'avg_first_response_hours': _hours(r['first']), 'avg_resolution_hours': _hours(r['resolve']),
                 'avg_rating': _num(r['s_rating'])}
                for r in qs.values(field).annotate(**group_aggs).order_by('-n')]

    cols = [('complaints', 'Обращений'), ('avg_first_response_hours', 'Первый ответ, ч'),
            ('avg_resolution_hours', 'Решение, ч'), ('avg_rating', 'Оценка')]
    return {'period': p.period(), 'kpis': kpis,
            'series': [_series(p, qs, 'created_at', 'complaints', 'Обращения')],
            'tables': [_table('complaints_by_category', 'Обращения по темам', [('name', 'Тема')] + cols,
                              rows('category_id', cat_names)),
                       _table('complaints_by_outlet', 'Обращения по точкам', [('name', 'Точка')] + cols,
                              rows('outlet_id', outlets))]}


# ============================================================== реестр

def _liability_report(p: ReportParams) -> dict:
    data = liability(p.date_to)
    data['period'] = p.period()
    return data


# report → (функция, права: достаточно любого из списка)
REPORTS = {
    'dashboard': (dashboard, ('reports.view',)),
    'funnel': (funnel, ('analytics.funnel',)),
    'members': (members, ('analytics.members',)),
    'cohorts': (cohorts, ('analytics.cohorts',)),
    'points': (points, ('analytics.points',)),
    'money': (money, ('analytics.money',)),
    'catalog': (catalog, ('analytics.catalog',)),
    'content': (content, ('analytics.content',)),
    'operations': (operations, ('analytics.operations',)),
    'liability': (_liability_report, ('analytics.points', 'reports.view')),
    'complaints': (complaints_report, ('analytics.operations',)),
}

REPORT_TITLES = {
    'dashboard': 'Дашборд', 'funnel': 'Воронка', 'members': 'Клиенты', 'cohorts': 'Когорты', 'points': 'Баллы',
    'money': 'Деньги', 'catalog': 'Каталог и акции', 'content': 'Контент и push', 'operations': 'Работа курорта',
    'liability': 'Обязательство', 'complaints': 'Обращения',
}


def can_view(user, report) -> bool:
    entry = REPORTS.get(report)
    return bool(entry) and any(user.can(perm) for perm in entry[1])


def run(report, params) -> dict:
    """params — ReportParams или dict/QueryDict в query-формате."""
    fn = REPORTS[report][0]
    if not isinstance(params, ReportParams):
        params = ReportParams.from_query(params or {})
    return fn(params)
