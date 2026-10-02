from django.utils.text import slugify

_TRANSLIT = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюяңөү',
                     ['a', 'b', 'v', 'g', 'd', 'e', 'e', 'zh', 'z', 'i', 'y', 'k', 'l', 'm', 'n', 'o', 'p', 'r', 's',
                      't', 'u', 'f', 'h', 'ts', 'ch', 'sh', 'sch', '', 'y', '', 'e', 'yu', 'ya', 'n', 'o', 'u']))


def slug_from_title(title, model, max_length=80, fallback='item'):
    """Латинский slug из названия (кириллица транслитерируется), уникальный для модели."""
    text = ''.join(_TRANSLIT.get(ch, ch) for ch in (title or '').lower())
    base = (slugify(text) or fallback)[:max_length - 4].strip('-')
    slug, n = base, 2
    while model.objects.filter(pk=slug).exists():
        slug, n = f'{base}-{n}', n + 1
    return slug
