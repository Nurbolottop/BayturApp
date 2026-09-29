from rest_framework.throttling import SimpleRateThrottle


class PublicIpThrottle(SimpleRateThrottle):
    scope = 'public_ip'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class PublicDeviceThrottle(SimpleRateThrottle):
    scope = 'public_device'

    def get_cache_key(self, request, view):
        device = getattr(request._request, 'device_id', None)
        if not device:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': device}


class EventsThrottle(PublicDeviceThrottle):
    scope = 'events'


PUBLIC_THROTTLES = [PublicIpThrottle, PublicDeviceThrottle]


def client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')
