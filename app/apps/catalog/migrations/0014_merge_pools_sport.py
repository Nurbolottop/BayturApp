"""
Главный экран курорта: «Бассейны» + «Спорт» → «Развлечения», «Пляж» — новым разделом в конце.

- Услуги курорта из «Бассейнов» и «Спорта» переносятся в «Развлечения».
- «Бассейны» и «Спорт» скрываются из приложения курорта (in_resort_app=False), но не удаляются:
  «Спорт» — раздел прайса «Тоо-Ашуу» и Суусамыра (скипасс, прокат, трансферы), старые заявки и история
  хранят свои категории.
- Сторис «Бассейнов» становится сторис «Развлечений», слайды «Спорта» добавляются в неё; сторис «Спорта» —
  в черновик. Кнопка «Открыть в каталоге» у статей ведёт в «Развлечения».
"""
from django.db import migrations

L = lambda ru, ky, en: {'ru': ru, 'ky': ky, 'en': en}  # noqa: E731
RESORT = 'resort'


def forward(apps, schema_editor):
    Category = apps.get_model('catalog', 'Category')
    Item = apps.get_model('catalog', 'Item')
    Story = apps.get_model('content', 'Story')
    StorySlide = apps.get_model('content', 'StorySlide')
    Article = apps.get_model('content', 'Article')

    src = {c.pk: c for c in Category.objects.filter(pk__in=['pools', 'sport'])}
    base = src.get('sport') or src.get('pools')
    rules = {'rate': base.rate, 'max_points_share': base.max_points_share, 'methods': base.methods} if base else \
        {'rate': '0.10', 'max_points_share': '1.00', 'methods': ['cash', 'elqr']}
    pools_sort = src['pools'].sort_order if 'pools' in src else 4
    ent, _ = Category.objects.get_or_create(pk='entertainment', defaults={
        'title': L('Развлечения', 'Көңүл ачуу', 'Entertainment'), 'sort_order': pools_sort,
        'cover': (src['pools'].cover if 'pools' in src else ''), 'is_active': True, 'in_resort_app': True, **rules})
    last = max([c.sort_order for c in Category.objects.all()] + [0])
    Category.objects.get_or_create(pk='beach', defaults={
        'title': L('Пляж', 'Пляж', 'Beach'), 'sort_order': last + 1, 'cover': '', 'is_active': True,
        'in_resort_app': True, **rules})

    Item.objects.filter(venue_id=RESORT, category_id__in=['pools', 'sport']).update(category=ent)
    Category.objects.filter(pk__in=['pools', 'sport']).update(in_resort_app=False)
    # скрытые разделы — после видимых (чтобы не мешали порядку в списках админки)
    Category.objects.filter(pk='pools').update(sort_order=last + 2)
    Category.objects.filter(pk='sport').update(sort_order=last + 3)

    stories = {s.category_id: s for s in Story.objects.filter(category_id__in=['pools', 'sport', 'entertainment'])}
    target = stories.get('entertainment')
    if target is None and 'pools' in stories:
        target = stories.pop('pools')
        target.category_id = 'entertainment'
        target.title = L('Развлечения', 'Көңүл ачуу', 'Entertainment')
        target.save(update_fields=['category', 'title'])
    elif target is None and 'sport' in stories:
        target = stories.pop('sport')
        target.category_id = 'entertainment'
        target.title = L('Развлечения', 'Көңүл ачуу', 'Entertainment')
        target.save(update_fields=['category', 'title'])
    if target is not None:
        order = max([s.sort_order for s in StorySlide.objects.filter(story=target)] + [0])
        for key in ('pools', 'sport'):
            old = stories.get(key)
            if old is None:
                continue
            for slide in StorySlide.objects.filter(story=old).order_by('sort_order', 'id'):
                order += 1
                slide.story = target
                slide.sort_order = order
                slide.save(update_fields=['story', 'sort_order'])
            old.status = 'draft'
            old.save(update_fields=['status'])

    Article.objects.filter(category_id__in=['pools', 'sport']).update(category=ent)


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0013_categories_entertainment_beach'),
        ('content', '0002_modes'),
    ]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
