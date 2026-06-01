from django.contrib import admin
from .models import LookupHistory, SavedVerse


@admin.register(LookupHistory)
class LookupHistoryAdmin(admin.ModelAdmin):
    list_display = ['user', 'query', 'reference_found', 'version', 'match_type', 'created_at']
    list_filter = ['version', 'match_type']
    search_fields = ['user__username', 'query', 'reference_found']
    readonly_fields = ['created_at']
    date_hierarchy = 'created_at'


@admin.register(SavedVerse)
class SavedVerseAdmin(admin.ModelAdmin):
    list_display = ['user', 'reference', 'version', 'created_at']
    list_filter = ['version']
    search_fields = ['user__username', 'reference']
    readonly_fields = ['created_at']
