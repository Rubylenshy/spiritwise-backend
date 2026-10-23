from django.urls import path
from . import manage_views, views
from .streaming import stream_sermon

urlpatterns = [
    path('', views.sermon_list, name='sermon-list'),
    path('<int:pk>/', views.sermon_detail, name='sermon-detail'),
    path('<int:pk>/progress/', views.update_progress, name='sermon-progress'),
    path('<int:pk>/stream/', stream_sermon, name='sermon-stream'),
    path('<int:pk>/stream-token/', views.get_stream_token, name='sermon-stream-token'),

    path('series/', views.series_list, name='series-list'),
    path('series/<int:pk>/', views.series_detail, name='series-detail'),

    path('speakers/', views.speaker_list, name='speaker-list'),
    path('tags/', views.tag_list, name='tag-list'),

    # Admin dashboard — staff only
    path('manage/sermons/', manage_views.sermon_list, name='manage-sermon-list'),
    path('manage/sermons/<int:pk>/', manage_views.sermon_detail, name='manage-sermon-detail'),
    path('manage/series/', manage_views.series_list, name='manage-series-list'),
    path('manage/series/<int:pk>/', manage_views.series_detail, name='manage-series-detail'),
    path('manage/tags/', manage_views.tag_list, name='manage-tag-list'),
    path('manage/tags/<int:pk>/', manage_views.tag_detail, name='manage-tag-detail'),
]
