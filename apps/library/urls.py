from django.urls import path
from . import views

urlpatterns = [
    path('favorites/', views.favorite_list, name='favorite-list'),
    path('favorites/<int:sermon_id>/', views.favorite_detail, name='favorite-detail'),

    path('playlists/', views.playlist_list, name='playlist-list'),
    path('playlists/<int:pk>/', views.playlist_detail, name='playlist-detail'),
    path('playlists/<int:pk>/items/', views.playlist_items, name='playlist-items'),
    path('playlists/<int:pk>/items/<int:sermon_id>/', views.playlist_item_detail, name='playlist-item-detail'),
    path('playlists/<int:pk>/items/<int:sermon_id>/move/', views.playlist_item_move, name='playlist-item-move'),
]
