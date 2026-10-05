"""Каталог: разделы с правилами кешбека, услуги (редактор с галереей, «что входит», акциями), загрузка фото."""
from django.contrib import messages
from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.catalog.models import FEATURE_ICONS, Category, Item, ItemPromo, Outlet
from apps.common.audit import audit, model_snapshot
from apps.common.caching import bump_content_version
from apps.common.media import process_upload
from apps.common.models import ProgramSettings, Upload

from ..access import is_staff_user, panel_view
from ..forms import CategoryForm, ItemForm, PromoRateForm


def _editor_only(user):
    return not user.can('catalog.edit')


@panel_view('catalog')
def catalog(request):
    cats = Category.objects.all().prefetch_related('items__promos', 'items__outlet')
    now = timezone.now()
    q = (request.GET.get('q') or '').strip().lower()
    groups = []
    for c in cats:
        items = [i for i in c.items.all() if not q or q in (i.title.get('ru') or '').lower() or q in i.id]
        groups.append({'cat': c, 'items': [{'obj': i, 'promo': i.active_promo(now)} for i in items]})
    return render(request, 'panel/catalog/index.html', {'groups': groups, 'q': q,
                                                        'can_edit': request.user.can('catalog.edit')})


@panel_view('catalog')
def category_edit(request, category_id):
    cat = get_object_or_404(Category, pk=category_id)
    form = CategoryForm(request.POST or None, instance=cat)
    if _editor_only(request.user):
        form.lock(CategoryForm.RULE_FIELDS)
    if request.method == 'POST' and form.is_valid():
        before = model_snapshot(cat)
        obj = form.save()
        audit(request, 'category.update', obj, before=before, after=model_snapshot(obj))
        messages.success(request, 'Раздел сохранён. Новые правила действуют только на новые заявки')
        return redirect('panel:catalog')
    return render(request, 'panel/catalog/category.html', {'form': form, 'cat': cat})


@panel_view('catalog')
def item_edit(request, item_id=None):
    user = request.user
    item = get_object_or_404(Item.objects.select_related('category'), pk=item_id) if item_id else None
    if item is None and not user.can('catalog.edit'):
        from ..access import forbidden
        return forbidden(request, 'Создавать услуги может директор')
    initial = {}
    if item is None and request.GET.get('category'):
        initial['category'] = request.GET['category']
    form = ItemForm(request.POST or None, instance=item, initial=initial)
    if _editor_only(user):
        form.lock(ItemForm.RULE_FIELDS)
    if request.method == 'POST' and form.is_valid():
        before = model_snapshot(item) if item else None
        obj = form.save()
        audit(request, 'item.update' if item else 'item.create', obj, before=before, after=model_snapshot(obj))
        messages.success(request, 'Услуга сохранена')
        return redirect('panel:item', item_id=obj.pk)
    ctx = {
        'form': form, 'item': item, 'feature_icons': FEATURE_ICONS,
        'promos': item.promos.all() if item else [],
        'promo_form': PromoRateForm(prefix='promo'),
        'has_requests': item.requests.exists() if item else False,
        'rate': item.category.rate if item else None,
        'categories': {c.pk: str(c.rate) for c in Category.objects.all()},
        'promo_rate': str(item.promo_rate()) if item and item.promo_rate() is not None else '',
        'can_edit': user.can('catalog.edit'),
        'now': timezone.now(),
        'points_per_som': ProgramSettings.get().points_per_som,
    }
    return render(request, 'panel/catalog/item.html', ctx)


@require_POST
@panel_view(perm='catalog.edit')
def item_action(request, item_id, action):
    item = get_object_or_404(Item, pk=item_id)
    if action in ('hide', 'show'):
        before = {'is_active': item.is_active}
        item.is_active = action == 'show'
        item.save(update_fields=['is_active', 'updated_at'])
        audit(request, f'item.{action}', item, before=before, after={'is_active': item.is_active})
        messages.success(request, 'Услуга скрыта' if action == 'hide' else 'Услуга снова в каталоге')
    elif action == 'delete':
        if item.requests.exists():
            messages.error(request, 'На услугу есть заявки — её можно только скрыть')
            return redirect('panel:item', item_id=item.pk)
        snap = model_snapshot(item)
        audit(request, 'item.delete', item, before=snap)
        item.delete()
        messages.success(request, 'Услуга удалена')
        return redirect('panel:catalog')
    elif action == 'promo':
        form = PromoRateForm(request.POST, prefix='promo')
        if form.is_valid():
            promo = form.save(commit=False)
            promo.item = item
            promo.save()
            audit(request, 'item.promo_add', item, after=model_snapshot(promo))
            item.save(update_fields=['updated_at'])
            messages.success(request, 'Акция добавлена — по окончании ставка и бейдж снимутся сами')
        else:
            messages.error(request, 'Акция: ' + '; '.join(e for errs in form.errors.values() for e in errs))
    elif action == 'promo-off':
        promo = get_object_or_404(ItemPromo, pk=request.POST.get('promo'), item=item)
        promo.is_active = False
        promo.save(update_fields=['is_active'])
        item.save(update_fields=['updated_at'])
        audit(request, 'item.promo_off', item, before={'promo': promo.pk, 'is_active': True},
              after={'is_active': False})
        messages.success(request, 'Акция выключена')
    elif action == 'sort':
        for i, pk in enumerate(request.POST.getlist('order')):
            Item.objects.filter(pk=pk, category_id=item.category_id).update(sort_order=i + 1)
        bump_content_version()  # .update() не шлёт сигналы — сбросить кеш каталога вручную
        audit(request, 'item.sort', item, after={'order': request.POST.getlist('order')})
        return JsonResponse({'ok': True})
    return redirect('panel:item', item_id=item.pk)


@require_POST
def upload(request):
    """Загрузка изображения → {path, url}. Для редакторов каталога и контента."""
    user = request.user
    if not is_staff_user(user) or getattr(user, 'must_change_password', False) or not any(user.can(p) for p in (
            'catalog.edit', 'catalog.texts', 'content.edit', 'tiers.texts', 'settings.edit')):
        return JsonResponse({'error': 'Недостаточно прав'}, status=403)
    f = request.FILES.get('file')
    if f is None or f.size > 10 * 1024 * 1024:
        return JsonResponse({'error': 'Файл не подходит (JPEG/PNG/WebP/HEIC до 10 МБ)'}, status=400)
    result = process_upload(f)
    if result is None:
        return JsonResponse({'error': 'Файл не подходит (JPEG/PNG/WebP/HEIC до 10 МБ)'}, status=400)
    content, ext, width, height = result
    up = Upload(kind=Upload.KIND_IMAGE, staff=user, width=width, height=height)
    up.file.save(f'image.{ext}', ContentFile(content.read()), save=False)
    up.save()
    audit(request, 'upload.create', up, after={'path': up.file.name})
    from ..templatetags.panel import media
    return JsonResponse({'id': up.pk, 'path': up.file.name, 'url': media(up.file.name), 'width': width,
                         'height': height})


@panel_view('catalog')
def outlets_json(request):
    return JsonResponse({'items': [{'id': o.pk, 'name': o.name.get('ru')} for o in Outlet.objects.all()]})
