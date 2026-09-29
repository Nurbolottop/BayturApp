"""Теги и фильтры панели: иконки, суммы, статусы-пилюли, медали уровней, график без библиотек."""
import json
import re
from decimal import Decimal

from django import template
from django.core.files.storage import default_storage
from django.utils import timezone
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

from apps.panel import icons

register = template.Library()

NNBSP = ' '


# ---------------------------------------------------------------- иконки

@register.simple_tag
def icon(name, size=20):
    return icons.svg(name, size)


@register.simple_tag
def bubble(name, size=20, tone=''):
    return icons.bubble(name, size, tone)


# ---------------------------------------------------------------- тексты и числа

@register.filter
def tr(value, lang='ru'):
    from apps.common.i18n import tr as _tr
    res = _tr(value, lang)
    if isinstance(res, list):
        return ' '.join(res)
    return res or ''


@register.filter
def num(value):
    if value in (None, ''):
        return '—'
    try:
        d = Decimal(str(value))
    except Exception:
        return value
    neg = d < 0
    d = abs(d)
    if d == d.to_integral_value():
        s = f'{int(d):,}'.replace(',', NNBSP)
    else:
        s = f'{d:,.2f}'.replace(',', NNBSP).replace('.', ',').rstrip('0').rstrip(',')
    return ('−' if neg else '') + s


@register.filter
def signed(value):
    try:
        v = int(value)
    except (TypeError, ValueError):
        return value
    return ('+' if v > 0 else '') + num(v)


@register.filter
def som(value):
    return '—' if value in (None, '') else f'{num(value)}{NNBSP}сом'


@register.filter
def pct(value):
    if value in (None, ''):
        return '—'
    v = Decimal(str(value)) * 100
    v = v.quantize(Decimal('0.1')).normalize()
    return f'{num(v)}{NNBSP}%'


@register.filter
def unit(value, u):
    if value in (None, ''):
        return '—'
    if u in ('%', 'percent', 'ratio', 'share'):
        return pct(value) if abs(Decimal(str(value))) <= 1 else f'{num(value)}{NNBSP}%'
    if u in ('som', 'сом'):
        return som(value)
    if u in ('points', 'pts', 'баллов'):
        return f'{num(value)}'
    if u in ('min', 'minutes'):
        return f'{num(value)}{NNBSP}мин'
    if u in ('h', 'hours'):
        return f'{num(value)}{NNBSP}ч'
    return num(value) if isinstance(value, (int, float, Decimal)) else value


@register.filter
def delta(kpi):
    """Изменение к прошлому периоду: (+12 %, 'up'|'down'|'flat')."""
    try:
        v, p = Decimal(str(kpi.get('value'))), Decimal(str(kpi.get('prev')))
    except Exception:
        return None
    if p == 0:
        return None
    ch = (v - p) / abs(p) * 100
    direction = 'up' if ch > 0 else 'down' if ch < 0 else 'flat'
    return {'text': f'{"+" if ch > 0 else ""}{num(ch.quantize(Decimal("0.1")))}{NNBSP}%', 'dir': direction}


@register.filter
def get(d, key):
    if d is None:
        return None
    try:
        return d.get(key)
    except AttributeError:
        try:
            return d[key]
        except Exception:
            return None


@register.filter
def media(path):
    if not path:
        return ''
    if str(path).startswith(('http://', 'https://', '/')):
        return path
    try:
        return default_storage.url(path)
    except Exception:
        return path


@register.filter
def mask(phone):
    from apps.cashback.serializers import mask_phone
    return mask_phone(phone) or '—'


@register.filter
def local(dt, fmt='d.m.Y H:i'):
    if not dt:
        return '—'
    from django.utils.dateformat import format as dformat
    if isinstance(dt, str):
        from django.utils.dateparse import parse_datetime
        dt = parse_datetime(dt) or dt
        if isinstance(dt, str):
            return dt
    if hasattr(dt, 'tzinfo') and timezone.is_aware(dt):
        dt = timezone.localtime(dt)
    return dformat(dt, fmt)


@register.filter
def ago(dt):
    if not dt:
        return ''
    secs = int((timezone.now() - dt).total_seconds())
    if secs < 60:
        return 'только что'
    if secs < 3600:
        return f'{secs // 60} мин назад'
    if secs < 86400:
        return f'{secs // 3600} ч назад'
    return f'{secs // 86400} дн назад'


@register.filter
def jsonattr(value):
    return json.dumps(value, ensure_ascii=False, default=str)


@register.filter
def can(user, perm):
    return bool(user and getattr(user, 'can', None) and user.can(perm))


# ---------------------------------------------------------------- статусы

STATUS = {
    'request': {
        'pending': ('Ожидает', 'live'), 'confirmed': ('Подтверждена', 'live'),
        'credited': ('Кешбек начислен', 'positive'), 'rejected': ('Отклонена', 'negative'),
        'cancelled': ('Отменена', 'muted'),
    },
    'complaint': {
        'new': ('Новое', 'accent'), 'in_progress': ('В работе', 'live'), 'answered': ('Отвечено', 'positive'),
        'closed': ('Закрыто', 'muted'),
    },
    'payment': {
        'created': ('Создан', 'live'), 'pending': ('Ожидает', 'live'), 'paid': ('Оплачен', 'positive'),
        'failed': ('Ошибка', 'negative'), 'expired': ('Истёк', 'muted'), 'refunded': ('Возвращён', 'muted'),
    },
    'publish': {'draft': ('Черновик', 'muted'), 'published': ('Опубликовано', 'positive')},
    'campaign': {
        'draft': ('Черновик', 'muted'), 'scheduled': ('Запланирована', 'live'), 'sending': ('Отправляется', 'live'),
        'sent': ('Отправлена', 'positive'), 'cancelled': ('Отменена', 'negative'),
    },
    'member': {
        'active': ('Активен', 'positive'), 'blocked': ('Заблокирован', 'negative'),
        'deactivated': ('Удалён', 'warning'), 'purged': ('Стёрт', 'muted'),
    },
    'bool': {True: ('Вкл', 'positive'), False: ('Выкл', 'muted')},
}


@register.simple_tag
def pill(kind, status, label=None):
    text, tone = STATUS.get(kind, {}).get(status, (status, 'muted'))
    dot = '<i class="dot"></i>' if tone in ('live', 'accent') else ''
    return format_html('<span class="pill pill-{}">{}{}</span>', tone, mark_safe(dot), label or text)


# ---------------------------------------------------------------- уровни

TIER_NAMES = {'bronze': 'Бронза', 'silver': 'Серебро', 'gold': 'Золото', 'platinum': 'Платина',
              'diamond': 'Бриллиант'}


@register.filter
def tier_name(tier_id):
    return TIER_NAMES.get(tier_id, tier_id or '—')


@register.simple_tag
def medal(tier_id, size=28):
    """Медаль уровня — градиент tier_style.dart."""
    if not tier_id:
        return ''
    gid = f'm-{tier_id}-{size}'
    return mark_safe(
        f'<svg class="medal" width="{size}" height="{size}" viewBox="0 0 32 32" aria-hidden="true">'
        f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="var(--tier-{tier_id}-0)"/>'
        f'<stop offset=".55" stop-color="var(--tier-{tier_id}-1)"/>'
        f'<stop offset="1" stop-color="var(--tier-{tier_id}-2)"/></linearGradient></defs>'
        f'<path d="M10 2h5l-3 9H7z M22 2h-5l3 9h5z" fill="var(--tier-{tier_id}-1)" opacity=".85"/>'
        f'<circle cx="16" cy="19" r="11" fill="url(#{gid})"/>'
        f'<circle cx="16" cy="19" r="7.5" fill="none" stroke="rgba(255,255,255,.55)" stroke-width="1.4"/>'
        f'<path d="m16 14.6 1.35 2.75 3 .44-2.18 2.12.52 3-2.69-1.42-2.69 1.42.52-3-2.18-2.12 3-.44z" '
        f'fill="rgba(255,255,255,.9)"/></svg>')


@register.simple_tag
def tier_badge(tier_id):
    if not tier_id:
        return mark_safe('<span class="muted">—</span>')
    return format_html('<span class="tier-badge tier-{}">{}<span>{}</span></span>', tier_id, medal(tier_id, 18),
                       tier_name(tier_id))


# ---------------------------------------------------------------- шкала этапов заявки

@register.simple_tag
def request_timeline(req):
    tl = req.timeline or {}
    steps = [('pending', 'Отправлена')]
    if req.status == 'rejected':
        steps.append(('rejected', 'Отклонена'))
    elif req.status == 'cancelled':
        steps.append(('cancelled', 'Отменена'))
    else:
        steps += [('confirmed', 'Подтверждена'), ('credited', 'Кешбек начислен')]
    if tl.get('adjusted'):
        steps.insert(1, ('adjusted', 'Сумма изменена'))
    out = []
    reached_all = True
    for key, label in steps:
        at = tl.get(key)
        done = bool(at)
        tone = 'negative' if key in ('rejected', 'cancelled') else ''
        out.append({'key': key, 'label': label, 'at': at, 'done': done, 'tone': tone,
                    'current': done and reached_all})
        reached_all = reached_all and done
    # текущий этап — последний выполненный
    last = max((i for i, s in enumerate(out) if s['done']), default=0)
    for i, s in enumerate(out):
        s['current'] = i == last
        s['next'] = i == last + 1
    html = ['<ol class="timeline">']
    for s in out:
        cls = ' '.join(filter(None, ['done' if s['done'] else '', 'current' if s['current'] else '', s['tone'],
                                     'next' if s['next'] and req.status in ('pending', 'confirmed') else '']))
        at = local(s['at'], 'd.m H:i') if s['at'] else ''
        html.append(f'<li class="{cls}"><i></i><b>{escape(s["label"])}</b><small>{escape(at)}</small></li>')
    html.append('</ol>')
    return mark_safe(''.join(html))


# ---------------------------------------------------------------- график (SVG без библиотек)

_DATE_RE = re.compile(r'^\d{4}-\d{2}')


def _nice_max(v):
    if v <= 0:
        return 1
    import math
    exp = 10 ** math.floor(math.log10(v))
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if m * exp >= v:
            return m * exp
    return 10 * exp


def _xlabel(x):
    s = str(x)
    if _DATE_RE.match(s):
        parts = s[:10].split('-')
        if len(parts) == 3:
            return f'{parts[2]}.{parts[1]}'
        if len(parts) == 2:
            return f'{parts[1]}.{parts[0][2:]}'
    return s if len(s) <= 12 else s[:11] + '…'


@register.simple_tag
def chart(series, kind=None, height=220):
    series = [s for s in (series or []) if s.get('points')]
    if not series:
        return mark_safe('<div class="chart-empty">Нет данных за период</div>')
    series = series[:4]
    xs = []
    for s in series:
        for p in s['points']:
            if p.get('x') not in xs:
                xs.append(p.get('x'))
    is_time = all(_DATE_RE.match(str(x)) for x in xs)
    kind = kind or ('line' if is_time and len(xs) > 2 else 'bar')
    values = [float(p.get('y') or 0) for s in series for p in s['points']]
    vmax = _nice_max(max(values + [0]))
    vmin = min(values + [0])
    vmin = -_nice_max(-vmin) if vmin < 0 else 0
    W, H = 640, height
    pl, pr, pt, pb = 48, 12, 12, 28
    iw, ih = W - pl - pr, H - pt - pb
    n = len(xs)

    def sx(i):
        if kind == 'bar':
            return pl + iw * (i + 0.5) / n
        return pl + (iw * i / (n - 1) if n > 1 else iw / 2)

    def sy(v):
        return pt + ih * (1 - (v - vmin) / ((vmax - vmin) or 1))

    out = [f'<svg class="chart" viewBox="0 0 {W} {H}" preserveAspectRatio="none" role="img" '
           f'data-chart=\'{escape(json.dumps({"x": [str(x) for x in xs], "labels": [s.get("label") for s in series], "kind": kind}, ensure_ascii=False))}\'>']
    for k in range(5):
        v = vmin + (vmax - vmin) * k / 4
        y = sy(v)
        out.append(f'<line class="grid" x1="{pl}" x2="{W - pr}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text class="axis" x="{pl - 8}" y="{y + 4:.1f}" text-anchor="end">{escape(_short(v))}</text>')
    step = max(1, round(n / 6))
    for i, x in enumerate(xs):
        if i % step == 0 or i == n - 1 and kind == 'bar':
            out.append(f'<text class="axis" x="{sx(i):.1f}" y="{H - 8}" text-anchor="middle">{escape(_xlabel(x))}</text>')
    single = len(series) == 1
    if kind == 'bar':
        m = len(series)
        slot = iw / n
        bw = max(3.0, min(28.0, (slot - 8) / m - 2))
        for si, s in enumerate(series):
            col = 'var(--ink)' if single else f'var(--series-{si + 1})'
            pts = {p.get('x'): float(p.get('y') or 0) for p in s['points']}
            for i, x in enumerate(xs):
                v = pts.get(x, 0)
                cx = sx(i) - (m * (bw + 2)) / 2 + si * (bw + 2) + 1
                y0, y1 = sy(max(v, 0)), sy(min(v, 0))
                hgt = max(1.0, y1 - y0)
                out.append(f'<rect class="bar" x="{cx:.1f}" y="{y0:.1f}" width="{bw:.1f}" height="{hgt:.1f}" '
                           f'rx="{min(4, bw / 2):.1f}" fill="{col}" data-i="{i}"><title>{escape(s.get("label", ""))}: '
                           f'{escape(num(v))}</title></rect>')
    else:
        for si, s in enumerate(series):
            col = 'var(--ink)' if single else f'var(--series-{si + 1})'
            pts = {p.get('x'): float(p.get('y') or 0) for p in s['points']}
            coords = [(sx(i), sy(pts[x])) for i, x in enumerate(xs) if x in pts]
            d = 'M' + ' L'.join(f'{x:.1f} {y:.1f}' for x, y in coords)
            if single and coords:
                area = d + f' L{coords[-1][0]:.1f} {sy(max(vmin, 0)):.1f} L{coords[0][0]:.1f} {sy(max(vmin, 0)):.1f} Z'
                out.append(f'<path class="area" d="{area}"/>')
            out.append(f'<path class="line" d="{d}" stroke="{col}" pathLength="1"/>')
        out.append(f'<line class="cross" x1="0" x2="0" y1="{pt}" y2="{pt + ih}"/>')
    out.append('</svg>')
    legend = ''
    if not single:
        legend = '<div class="legend">' + ''.join(
            f'<span><i style="background:var(--series-{i + 1})"></i>{escape(s.get("label", ""))}</span>'
            for i, s in enumerate(series)) + '</div>'
    data = json.dumps([{str(p.get('x')): p.get('y') for p in s['points']} for s in series], ensure_ascii=False)
    return mark_safe(f'<div class="chart-wrap" data-values=\'{escape(data)}\'>{"".join(out)}'
                     f'<div class="chart-tip" hidden></div>{legend}</div>')


def _short(v):
    a = abs(v)
    if a >= 1_000_000:
        return f'{v / 1_000_000:.1f}'.rstrip('0').rstrip('.') + ' млн'
    if a >= 10_000:
        return f'{v / 1000:.0f} тыс'
    if a >= 1000:
        return f'{v / 1000:.1f}'.rstrip('0').rstrip('.') + ' тыс'
    return f'{v:.0f}' if v == int(v) else f'{v:.2f}'


RATIO_KEY = re.compile(r'(share|conversion|dropoff|ratio|rate)$|^m\d+$', re.I)


@register.filter
def cell(row, col):
    """Ячейка таблицы отчёта: col — {key, label[, unit]}; доли (share, conversion, m1…m12) — в процентах."""
    key = col.get('key') if isinstance(col, dict) else col
    v = row.get(key) if isinstance(row, dict) else row
    unit_ = col.get('unit') if isinstance(col, dict) else None
    if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
        if unit_:
            return unit(v, unit_)
        if RATIO_KEY.search(str(key)) and abs(float(v)) <= 1:
            return pct(v)
        return num(v)
    if isinstance(v, dict):
        return tr(v)
    return '—' if v in (None, '') else v


@register.filter
def is_number(v):
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


@register.simple_tag
def icon_templates(names):
    """<template id="icon-…"> для JS-редакторов (сетка иконок в popover)."""
    return mark_safe(''.join(f'<template id="icon-{escape(n)}">{icons.svg(n, 20)}</template>' for n in names))


@register.simple_tag
def media_url():
    from django.conf import settings
    return settings.MEDIA_URL


@register.filter
def aslist(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return list(v)
    if isinstance(v, dict) and isinstance(v.get('series'), list):
        return v['series']  # серия-группа: {label, series:[...]} → один график на несколько рядов
    return [v]


METHODS = {'cash': 'Наличные', 'finik': 'Finik', 'freedomPay': 'Freedom Pay', 'elqr': 'ЭлQR'}


@register.filter
def method(v):
    return METHODS.get(v, v or '—')
