from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpResponseRedirect

from .media import absolute_media_url, get_resized


def resized_image(request, path):
    """/img/<path>?w=400 → WebP нужной ширины (кешируется в хранилище; в проде перед этим стоит CDN)."""
    if '..' in path or path.startswith(('private', 'exports')):
        raise Http404
    try:
        width = int(request.GET.get('w', 0))
    except ValueError:
        width = 0
    if not default_storage.exists(path):
        raise Http404
    if not width:
        return HttpResponseRedirect(absolute_media_url(path))
    target = get_resized(path, width)
    response = FileResponse(default_storage.open(target, 'rb'), content_type='image/webp')
    response['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response
