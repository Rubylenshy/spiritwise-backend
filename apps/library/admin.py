from django.contrib import admin
from .models import Favorite, Playlist, PlaylistItem


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ['user', 'sermon', 'created_at']
    search_fields = ['user__username', 'sermon__title']


class PlaylistItemInline(admin.TabularInline):
    model = PlaylistItem
    extra = 0
    ordering = ['position']


@admin.register(Playlist)
class PlaylistAdmin(admin.ModelAdmin):
    list_display = ['name', 'user', 'updated_at']
    search_fields = ['name', 'user__username']
    inlines = [PlaylistItemInline]
