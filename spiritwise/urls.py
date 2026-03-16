from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),

    # Auth
    path('api/auth/', include('apps.users.urls')),

    # Core features
    path('api/sermons/', include('apps.sermons.urls')),
    path('api/engagement/', include('apps.engagement.urls')),
    path('api/imports/', include('apps.imports.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
