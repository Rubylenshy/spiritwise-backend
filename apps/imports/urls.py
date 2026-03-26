from django.urls import path
from . import views

urlpatterns = [
    path('', views.import_list, name='import-list'),
    path('upload/', views.upload_sermon, name='import-upload'),
    path('parse-metadata/', views.parse_audio_metadata, name='import-parse-metadata'),
    path('<int:pk>/', views.import_detail, name='import-detail'),
    path('sermon/<int:sermon_id>/audio/', views.delete_sermon_audio, name='import-delete-audio'),
]
