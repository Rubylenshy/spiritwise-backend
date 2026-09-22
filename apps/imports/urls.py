from django.urls import path
from . import views

urlpatterns = [
    path('', views.import_list, name='import-list'),
    path('upload/', views.upload_sermon, name='import-upload'),
    path('presign/', views.presign_upload, name='import-presign'),
    path('finalize/', views.finalize_upload, name='import-finalize'),
    path('bulk-csv/', views.bulk_import_csv, name='import-bulk-csv'),
    path('parse-metadata/', views.parse_audio_metadata, name='import-parse-metadata'),
    path('<int:pk>/', views.import_detail, name='import-detail'),
    path('sermon/<int:sermon_id>/audio/', views.delete_sermon_audio, name='import-delete-audio'),
]
