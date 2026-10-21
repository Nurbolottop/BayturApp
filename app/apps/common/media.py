"""
Картинки: в БД хранится путь в хранилище (или внешний URL), в API — абсолютный URL.
Варианты размера — ?w=400 / ?w=1200 через /img/<path> (ресайз в WebP, кеш на диске / CDN).
"""
import io
import os

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

ALLOWED_WIDTHS = (200, 400, 800, 1200, 1600)


def absolute_media_url(path):
    if not path:
        return None
    if path.startswith(('http://', 'https://')):
        return path
    url = default_storage.url(path)
    if url.startswith(('http://', 'https://')):
        return url
    return settings.PUBLIC_BASE_URL + url


def resized_path(path, width):
    base, _ = os.path.splitext(path)
    return f'resized/{width}/{base}.webp'


def get_resized(path, width):
    """Возвращает путь к варианту ширины width, создавая его при первом обращении."""
    from PIL import Image, ImageOps

    width = min(ALLOWED_WIDTHS, key=lambda w: abs(w - width))
    target = resized_path(path, width)
    if default_storage.exists(target):
        return target
    with default_storage.open(path, 'rb') as fh:
        img = Image.open(fh)
        img = ImageOps.exif_transpose(img)
        if img.width > width:
            img.thumbnail((width, width * 10))
        buf = io.BytesIO()
        if img.mode not in ('RGB', 'RGBA'):
            # прозрачность сохраняем: RGBA/LA и палитровый PNG с transparency (cutout, логотип, медаль)
            alpha = 'A' in img.getbands() or 'transparency' in img.info
            img = img.convert('RGBA' if alpha else 'RGB')
        img.save(buf, 'WEBP', quality=82)
    default_storage.save(target, ContentFile(buf.getvalue()))
    return target


def process_upload(uploaded_file, strip_exif=True, max_side=2560):
    """
    Проверяет, что это изображение (JPEG/PNG/WebP/HEIC), убирает EXIF (геолокацию),
    ограничивает размер. Возвращает (ContentFile, ext, width, height).
    PNG/WebP с прозрачностью сохраняются с альфа-каналом (cutout акций).
    """
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:  # pragma: no cover
        pass

    try:
        img = Image.open(uploaded_file)
        img.load()
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    fmt = (img.format or '').upper()
    if fmt not in ('JPEG', 'PNG', 'WEBP', 'HEIF', 'HEIC', 'MPO'):
        return None
    img = ImageOps.exif_transpose(img)
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side))
    has_alpha = img.mode in ('RGBA', 'LA', 'P') and fmt in ('PNG', 'WEBP')
    buf = io.BytesIO()
    if has_alpha:
        img = img.convert('RGBA')
        img.save(buf, 'PNG', optimize=True)
        ext = 'png'
    else:
        img = img.convert('RGB')
        img.save(buf, 'JPEG', quality=85, optimize=True)  # без exif= → метаданные не пишутся
        ext = 'jpg'
    return ContentFile(buf.getvalue()), ext, img.width, img.height


def process_avatar(uploaded_file, size=512):
    """Аватар: квадрат по центру size×size, JPEG, без EXIF. None — не изображение."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:  # pragma: no cover
        pass
    try:
        img = Image.open(uploaded_file)
        img.load()
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    if (img.format or '').upper() not in ('JPEG', 'PNG', 'WEBP', 'HEIF', 'HEIC', 'MPO'):
        return None
    img = ImageOps.exif_transpose(img).convert('RGB')
    img = ImageOps.fit(img, (size, size), method=Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=85, optimize=True)
    return ContentFile(buf.getvalue())


IMAGE_FULL, IMAGE_MEDIUM, IMAGE_THUMB = 1600, 800, 400


def _image_meta(path):
    """Размер оригинала и преобладающий цвет (#RRGGBB) — считаются один раз, путь неизменяем (новое фото — новый путь)."""
    from django.core.cache import cache
    from PIL import Image, ImageOps

    key = f'imgmeta:{path}'
    meta = cache.get(key)
    if meta is not None:
        return meta
    meta = {}
    try:
        with default_storage.open(path, 'rb') as fh:
            img = ImageOps.exif_transpose(Image.open(fh))
            meta = {'width': img.width, 'height': img.height}
            small = img.convert('RGB')
            small.thumbnail((64, 64))
            palette = small.quantize(colors=6)
            counts = sorted(palette.getcolors() or [], reverse=True)
            if counts:
                pal = palette.getpalette()
                r, g, b = pal[counts[0][1] * 3:counts[0][1] * 3 + 3]
                meta['color'] = f'#{r:02X}{g:02X}{b:02X}'
    except (OSError, ValueError):
        meta = {}
    cache.set(key, meta, None)
    return meta


def image_payload(path):
    """
    Картинка для новых экранов (/services, /showcase): {url, thumb, width, height, color} или None.
    url — WebP до 1600 px по ширине, medium — 800 px (плитки на 3x-экранах), thumb — 400 px; исходник меньше
    нужной ширины не увеличивается. width/height — размер url (для резерва места до загрузки). Прозрачность сохраняется.
    """
    if not path:
        return None
    if path.startswith(('http://', 'https://')):
        return {'url': path, 'medium': path, 'thumb': path, 'width': None, 'height': None, 'color': None}
    meta = _image_meta(path)
    w, h = meta.get('width'), meta.get('height')
    if w and h and w > IMAGE_FULL:
        w, h = IMAGE_FULL, round(h * IMAGE_FULL / w)
    from urllib.parse import quote
    base = f'{settings.PUBLIC_BASE_URL}/img/{quote(path)}'
    return {'url': f'{base}?w={IMAGE_FULL}', 'medium': f'{base}?w={IMAGE_MEDIUM}', 'thumb': f'{base}?w={IMAGE_THUMB}',
            'width': w, 'height': h,
            'color': meta.get('color')}
