"""
Контекст клиентского API:
- язык контента из Accept-Language;
- X-Device-Id (анонимный UUID установки) → request.device_id;
- X-App-Version + X-Platform ниже минимальной → 426 update_required;
- техработы → 503 maintenance (кроме /app/config и админки).
"""
import json
import uuid

from django.http import JsonResponse

from .errors import message_for
from .i18n import parse_accept_language, set_language
from .versions import is_below

API_PREFIX = '/api/v1/'
EXEMPT = ('/api/v1/app/config', '/api/v1/admin/', '/api/v1/staff/', '/api/v1/payments/webhooks/',
          '/api/v1/schema', '/api/v1/docs')


def _error(code, status, extra=None):
    body = {'code': code, 'message': message_for(code)}
    if extra:
        body.update(extra)
    return JsonResponse({'error': body}, status=status, json_dumps_params={'ensure_ascii': False})


class ApiContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        set_language(parse_accept_language(request.headers.get('Accept-Language')))
        device = request.headers.get('X-Device-Id', '').strip()
        try:
            request.device_id = str(uuid.UUID(device)) if device else None
        except ValueError:
            request.device_id = None
        request.platform = (request.headers.get('X-Platform') or '').lower() or None
        request.app_version = request.headers.get('X-App-Version') or None

        if request.path.startswith(API_PREFIX) and not request.path.startswith(EXEMPT):
            from .models import ProgramSettings
            ps = ProgramSettings.get()
            if ps.maintenance:
                from .i18n import tr
                return _error('maintenance', 503, {'details': tr(ps.maintenance_message) or None})
            minimum = {'ios': ps.min_version_ios, 'android': ps.min_version_android}.get(request.platform)
            if minimum and is_below(request.app_version, minimum):
                return _error('update_required', 426, {'minVersion': minimum})
        return self.get_response(request)
