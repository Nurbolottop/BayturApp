from apps.common.i18n import iso, tr
from apps.common.media import absolute_media_url


def article_payload(a):
    return {
        'id': a.id,
        'image': absolute_media_url(a.image),
        'tag': tr(a.tag) or '',
        'title': tr(a.title),
        'lead': tr(a.lead) or '',
        'body': tr(a.body) or [],
        'quote': tr(a.quote) if a.quote else None,
        'date': a.date.isoformat(),
        'minutes': a.minutes,
        'category': a.category_id,
    }


def promo_payload(p):
    return {
        'id': p.id,
        'subtitle': tr(p.subtitle),
        'cta': tr(p.cta),
        'cutout': absolute_media_url(p.cutout),
        'article': article_payload(p.article),
    }


def event_payload(e):
    return {
        'id': e.id,
        'when': tr(e.when),
        'place': tr(e.place),
        'article': article_payload(e.article),
    }


def story_payload(s):
    return {
        'category': s.category_id,
        'title': tr(s.title),
        'cover': absolute_media_url(s.cover),
        'updatedAt': iso(s.updated_at),
        'slides': [{
            'image': absolute_media_url(sl.image),
            'title': tr(sl.title),
            'text': tr(sl.text) or '',
            'itemId': sl.item_id,
        } for sl in s.slides.all()],
    }
