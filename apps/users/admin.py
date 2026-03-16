from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, XPTransaction


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['username', 'email', 'first_name', 'xp_points', 'current_streak', 'is_staff']
    list_filter = ['is_staff', 'is_active']
    search_fields = ['username', 'email', 'first_name', 'last_name']

    fieldsets = BaseUserAdmin.fieldsets + (
        ('Engagement', {
            'fields': ('xp_points', 'current_streak', 'longest_streak', 'last_active_date', 'daily_goal_minutes'),
        }),
        ('Media', {'fields': ('avatar',)}),
    )


@admin.register(XPTransaction)
class XPTransactionAdmin(admin.ModelAdmin):
    list_display = ['user', 'points', 'reason', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__username', 'reason']
    readonly_fields = ['created_at']
