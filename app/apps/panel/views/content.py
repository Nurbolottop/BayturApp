"""Контент: статьи, акции-баннеры, события, сторис. Черновик / опубликовано, период показа, порядок, переводы."""
from django.contrib import messages
from django.db import transaction
from django.db.models import ProtectedError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.catalog.models import Item
from apps.common.audit import audit, model_snapshot
from apps.common.errors import message_for
from apps.content.models import Article, Promo, PublishStatus, ResortEvent, Story, StorySlide

from ..access import panel_view
from ..forms import ArticleForm, EventForm, PromoForm, StoryForm
from ..modes import current_mode

KINDS = {
    'articles': {'model': Article, 'form': ArticleForm, 'label': 'Статьи', 'one': 'Статья', 'icon': 'news'},
    'promos': {'model': Promo, 'form': PromoForm, 'label': 'Акции', 'one': 'Акция-баннер', 'icon': 'sparkle'},
    'events': {'model': ResortEvent, 'form': EventForm, 'label': 'События', 'one': 'Событие', 'icon': 'calendar'},
    'stories': {'model': Story, 'form': StoryForm, 'label': 'Сторис', 'one': 'Сторис', 'icon': 'story'},
}

FIELD_LABELS = {'tag': 'тег', 'title': 'заголовок', 'lead': 'подзаголовок', 'body': 'абзацы', 'quote': 'цитата',
                'subtitle': 'подпись', 'cta': 'кнопка', 'when': 'когда', 'place': 'где'}


def _kind(kind):
    if kind not in KINDS:
        raise Http404
    return KINDS[kind]


def missing_text(missing):
    parts = []
    import re
    for field, langs in missing.items():
        m = re.match(r'slides\[(\d+)\]\.(\w+)', field)
        if m:
            name = f'слайд {int(m.group(1)) + 1}: {"заголовок" if m.group(2) == "title" else "текст"}'
        else:
            name = FIELD_LABELS.get(field, field)
        parts.append(f'{name}: {", ".join(langs)}')
    return '; '.join(parts)


def obj_title(obj):
    if isinstance(obj, Article):
        return obj.title.get('ru') or obj.pk
    if isinstance(obj, (Promo, ResortEvent)):
        return obj.article.title.get('ru') or obj.article_id
    if isinstance(obj, Story):
        return obj.title.get('ru') or obj.category_id
    return str(obj)


@panel_view('content')
def content_list(request, kind='articles'):
    k = _kind(kind)
    qs = k['model'].objects.all()
    if not request.GET.get('all'):  # режим из шапки; ?all=1 — все режимы
        qs = qs.filter(modes__contains=[current_mode(request)])
    if kind in ('promos', 'events'):
        qs = qs.select_related('article')
    if kind == 'stories':
        qs = qs.select_related('category').prefetch_related('slides')
    status = request.GET.get('status')
    if status:
        qs = qs.filter(status=status)
    now = timezone.now()
    rows = []
    for o in qs:
        missing = o.missing_translations()
        rows.append({'obj': o, 'title': obj_title(o), 'missing': missing, 'missing_text': missing_text(missing),
                     'live': _is_live(o, now)})
    return render(request, 'panel/content/list.html', {
        'kind': kind, 'k': k, 'kinds': KINDS, 'rows': rows, 'status': status})


def _is_live(o, now):
    if o.status != PublishStatus.PUBLISHED:
        return False
    af, at = getattr(o, 'active_from', None), getattr(o, 'active_to', None)
    return (af is None or af <= now) and (at is None or now < at)


def _save_slides(story, slides):
    story.slides.all().delete()
    for i, s in enumerate(slides):
        StorySlide.objects.create(story=story, image=s['image'], title=s['title'], text=s['text'],
                                  item_id=s['item'], sort_order=i + 1)


@panel_view('content')
def content_edit(request, kind, pk=None):
    k = _kind(kind)
    obj = get_object_or_404(k['model'], pk=pk) if pk else None
    form = k['form'](request.POST or None, instance=obj)
    if kind == 'stories' and obj is not None and not request.POST:
        form.initial['slides'] = [{'image': s.image, 'title': s.title, 'text': s.text, 'item': s.item_id}
                                  for s in obj.slides.all()]
    if request.method == 'POST' and form.is_valid():
        before = model_snapshot(obj) if obj else None
        with transaction.atomic():
            saved = form.save()
            if kind == 'stories':
                _save_slides(saved, form.cleaned_data.get('slides') or [])
                saved.save()  # updated_at → клиенты перечитают сторис
            # опубликованный объект с новыми пустыми переводами — вернуть в черновик нельзя молча: предупреждаем
            missing = saved.missing_translations()
        audit(request, f'{kind}.update' if obj else f'{kind}.create', saved, before=before,
              after=model_snapshot(saved))
        if saved.status == PublishStatus.PUBLISHED and missing and not saved.use_ru_fallback:
            messages.warning(request, 'Сохранено, но не хватает переводов: ' + missing_text(missing))
        else:
            messages.success(request, 'Сохранено')
        if request.POST.get('then') == 'publish':
            return _publish(request, kind, saved)
        return redirect('panel:content-edit', kind=kind, pk=saved.pk)
    ctx = {'kind': kind, 'k': k, 'kinds': KINDS, 'form': form, 'obj': obj,
           'missing': missing_text(obj.missing_translations()) if obj else '',
           'items': Item.objects.all().only('id', 'title') if kind == 'stories' else None}
    if kind in ('promos', 'events'):
        ctx['articles'] = {a.pk: {'title': a.title, 'image': a.image, 'tag': a.tag}
                           for a in Article.objects.all()}
    return render(request, 'panel/content/edit.html', ctx)


def _publish(request, kind, obj):
    missing = obj.missing_translations()
    if missing and not obj.use_ru_fallback:
        messages.error(request, message_for('translations_missing', 'ru') + ' — ' + missing_text(missing))
        return redirect('panel:content-edit', kind=kind, pk=obj.pk)
    if kind in ('promos', 'events') and obj.article.status != PublishStatus.PUBLISHED:
        messages.error(request, 'Сначала опубликуйте статью, на которую ведёт карточка')
        return redirect('panel:content-edit', kind=kind, pk=obj.pk)
    before = {'status': obj.status}
    obj.status = PublishStatus.PUBLISHED
    obj.published_at = obj.published_at or timezone.now()
    obj.save()
    audit(request, f'{kind}.publish', obj, before=before, after={'status': obj.status})
    messages.success(request, 'Опубликовано')
    return redirect('panel:content-edit', kind=kind, pk=obj.pk)


@require_POST
@panel_view('content')
def content_action(request, kind, pk, action):
    k = _kind(kind)
    obj = get_object_or_404(k['model'], pk=pk)
    if action == 'publish':
        return _publish(request, kind, obj)
    if action == 'unpublish':
        before = {'status': obj.status}
        obj.status = PublishStatus.DRAFT
        obj.save()
        audit(request, f'{kind}.unpublish', obj, before=before, after={'status': obj.status})
        messages.success(request, 'Снято с публикации')
        return redirect('panel:content-edit', kind=kind, pk=obj.pk)
    if action == 'delete':
        snap = model_snapshot(obj)
        try:
            obj.delete()
        except ProtectedError:
            messages.error(request, 'На статью ссылаются акции или события — сначала удалите их')
            return redirect('panel:content-edit', kind=kind, pk=pk)
        audit(request, f'{kind}.delete', None, object_type=obj._meta.label_lower, object_id=pk, before=snap)
        messages.success(request, 'Удалено')
        return redirect('panel:content-kind', kind=kind)
    raise Http404
