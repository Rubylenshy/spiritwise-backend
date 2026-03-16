from django.contrib import admin
from .models import CloudImportJob


@admin.register(CloudImportJob)
class CloudImportJobAdmin(admin.ModelAdmin):
    list_display = ['id', 'source', 'sermon_title', 'sermon_speaker', 'status', 'progress_pct', 'requested_by', 'created_at']
    list_filter = ['source', 'status']
    search_fields = ['sermon_title', 'sermon_speaker', 'source_file_id']
    readonly_fields = ['status', 'progress_pct', 'sermon', 'error_message', 'created_at', 'updated_at']
