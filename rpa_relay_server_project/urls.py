# django-rpa-relay-standalone/rpa_relay_server_project/urls.py
from django.contrib import admin
from django.urls import path, include

# Import settings and static for serving static files in development
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('relay_server.urls')),
    path('o/', include('oauth2_provider.urls', namespace='oauth2_provider')),
    path('', include('remote_control_app.urls')),
]
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)