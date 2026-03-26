from django.urls import path
from . import views
from .streaming import stream_sermon

urlpatterns = [
    path('', views.sermon_list, name='sermon-list'),
    path('<int:pk>/', views.sermon_detail, name='sermon-detail'),
    path('<int:pk>/progress/', views.update_progress, name='sermon-progress'),
    path('<int:pk>/stream/', stream_sermon, name='sermon-stream'),
    path('<int:pk>/stream-token/', views.get_stream_token, name='sermon-stream-token'),

    path('series/', views.series_list, name='series-list'),
    path('series/<int:pk>/', views.series_detail, name='series-detail'),

    path('tags/', views.tag_list, name='tag-list'),
]
