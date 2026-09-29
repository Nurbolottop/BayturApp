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
            img = img.convert('RGBA' if 'A' in img.getbands() else 'RGB')
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
