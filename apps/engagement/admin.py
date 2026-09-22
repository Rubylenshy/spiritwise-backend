from django.contrib import admin
from .models import StreakRecord, QuestionAnswer


@admin.register(StreakRecord)
class StreakRecordAdmin(admin.ModelAdmin):
    list_display = ['user', 'date', 'activity_type', 'xp_earned']
    list_filter = ['activity_type', 'date']
    search_fields = ['user__username']
    date_hierarchy = 'date'


@admin.register(QuestionAnswer)
class QuestionAnswerAdmin(admin.ModelAdmin):
    list_display = ['user', 'sermon', 'question', 'created_at']
    search_fields = ['user__username', 'sermon__title']
    readonly_fields = ['created_at', 'updated_at']

