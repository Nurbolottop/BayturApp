from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.common.views_media import resized_image
from apps.members import web as members_web

urlpatterns = [
    path('api/v1/', include('core.api_urls')),
    path('api/v1/schema', SpectacularAPIView.as_view(), name='schema'),
    path('api/v1/docs', SpectacularSwaggerView.as_view(url_name='schema'), name='docs'),
    path('img/<path:path>', resized_image, name='resized-image'),
    # публичная страница удаления аккаунта без приложения (требование Google Play)
    path('account/delete', members_web.delete_account, name='account-delete'),
    path('legal/<slug:kind>', members_web.legal_page, name='legal-page'),
    path('panel/', include('apps.panel.urls')),
    # технический Django admin — только для разработчиков
    path('django-admin/', admin.site.urls),
]

if settings.DEBUG:
    from django.conf.urls.static import static
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
