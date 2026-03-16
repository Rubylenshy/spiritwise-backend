from django.contrib import admin
from .models import Sermon, Series, Tag, SermonQuestion, ListenHistory


@admin.register(Series)
class SeriesAdmin(admin.ModelAdmin):
    list_display = ['title', 'created_at']
    prepopulated_fields = {'slug': ('title',)}
    search_fields = ['title']


class SermonQuestionInline(admin.TabularInline):
    model = SermonQuestion
    extra = 1
    ordering = ['order']


@admin.register(Sermon)
class SermonAdmin(admin.ModelAdmin):
    list_display = ['title', 'speaker', 'series', 'duration_display', 'sermon_date', 'is_published', 'play_count']
    list_filter = ['is_published', 'series', 'tags']
    search_fields = ['title', 'speaker', 'scripture_reference']
    prepopulated_fields = {'slug': ('title',)}
    filter_horizontal = ['tags']
    inlines = [SermonQuestionInline]
    readonly_fields = ['play_count', 'created_at', 'updated_at']

    fieldsets = (
        ('Content', {'fields': ('title', 'slug', 'speaker', 'series', 'tags', 'description', 'scripture_reference')}),
        ('Audio', {'fields': ('audio_file', 'audio_url', 'duration_seconds')}),
        ('Media', {'fields': ('thumbnail',)}),
        ('Publishing', {'fields': ('is_published', 'sermon_date', 'play_count', 'created_at', 'updated_at')}),
    )


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(ListenHistory)
class ListenHistoryAdmin(admin.ModelAdmin):
    list_display = ['user', 'sermon', 'progress_seconds', 'completed', 'last_listened']
    list_filter = ['completed']
    search_fields = ['user__username', 'sermon__title']
