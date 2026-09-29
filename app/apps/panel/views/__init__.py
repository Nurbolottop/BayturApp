from django.shortcuts import redirect

from ..access import forbidden, is_staff_user
from ..sections import home_url


def home(request):
    if not is_staff_user(request.user):
        return redirect('panel:login')
    if getattr(request.user, 'must_change_password', False):
        return redirect('panel:password')
    url = home_url(request.user)
    return redirect(url) if url else forbidden(request, 'У вашей роли нет доступных разделов')
