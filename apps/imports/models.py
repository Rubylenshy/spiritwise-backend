from django.db import models
from django.conf import settings


class ImportSource(models.TextChoices):
    GOOGLE_DRIVE = 'google_drive', 'Google Drive'
    DROPBOX = 'dropbox', 'Dropbox'
    URL = 'url', 'Direct URL'
    LOCAL = 'local', 'Local Upload'


class ImportStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    DOWNLOADING = 'downloading', 'Downloading'
    PROCESSING = 'processing', 'Processing'
    UPLOADING = 'uploading', 'Uploading to Storage'
    COMPLETE = 'complete', 'Complete'
    FAILED = 'failed', 'Failed'


class CloudImportJob(models.Model):
    """
    Represents a single import task kicked off by an admin user.
    A Celery worker picks it up and transitions it through statuses.
    """
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='import_jobs',
    )
    source = models.CharField(max_length=20, choices=ImportSource.choices)
    status = models.CharField(
        max_length=20,
        choices=ImportStatus.choices,
        default=ImportStatus.PENDING,
    )

    # Source identifiers
    source_file_id = models.CharField(max_length=500, blank=True)  # Google Drive file ID
    source_url = models.URLField(blank=True)                        # direct URL / Dropbox

    # Sermon metadata (pre-filled by user before import)
    sermon_title = models.CharField(max_length=300, blank=True)
    sermon_speaker = models.CharField(max_length=200, blank=True)
    sermon_series_id = models.IntegerField(null=True, blank=True)
    sermon_date = models.DateField(null=True, blank=True)
    sermon_tags = models.CharField(max_length=500, blank=True)  # comma-separated tag names

    # Result
    sermon = models.OneToOneField(
        'sermons.Sermon',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='import_job',
    )
    error_message = models.TextField(blank=True)
    progress_pct = models.PositiveSmallIntegerField(default=0)  # 0-100

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.source} import — {self.sermon_title or self.source_file_id} [{self.status}]'

    def mark_failed(self, reason: str):
        self.status = ImportStatus.FAILED
        self.error_message = reason
        self.save(update_fields=['status', 'error_message', 'updated_at'])

    def set_progress(self, pct: int, status_label: str = None):
        self.progress_pct = pct
        if status_label:
            self.status = status_label
        self.save(update_fields=['progress_pct', 'status', 'updated_at'])
