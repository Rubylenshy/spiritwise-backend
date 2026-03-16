import io
import os
import tempfile

from celery import shared_task
from django.core.files.base import ContentFile

from .models import CloudImportJob, ImportStatus


@shared_task(bind=True, name='imports.process_import_job', max_retries=3)
def process_import_job(self, job_id: int):
    """
    Main import pipeline:
    1. Fetch the CloudImportJob
    2. Download audio from source (Google Drive / URL)
    3. Save to Django storage (local or S3)
    4. Create the Sermon record
    5. Update the job as COMPLETE
    """
    try:
        job = CloudImportJob.objects.get(pk=job_id)
    except CloudImportJob.DoesNotExist:
        return f'Job {job_id} not found'

    try:
        if job.source == 'google_drive':
            audio_content, filename = _download_from_drive(job)
        elif job.source == 'url':
            audio_content, filename = _download_from_url(job)
        else:
            job.mark_failed(f'Unsupported source: {job.source}')
            return

        job.set_progress(60, ImportStatus.UPLOADING)
        _create_sermon(job, audio_content, filename)
        job.status = ImportStatus.COMPLETE
        job.progress_pct = 100
        job.save(update_fields=['status', 'progress_pct', 'updated_at'])

    except Exception as exc:
        job.mark_failed(str(exc))
        raise self.retry(exc=exc, countdown=30)


def _download_from_drive(job: 'CloudImportJob'):
    """
    Download a file from Google Drive using a service account or
    OAuth credentials stored in environment variables.
    """
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    from google.oauth2 import service_account
    import json, os

    job.set_progress(10, ImportStatus.DOWNLOADING)

    creds_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if not creds_json:
        raise ValueError('GOOGLE_SERVICE_ACCOUNT_JSON env var is not set')

    credentials = service_account.Credentials.from_service_account_info(
        json.loads(creds_json),
        scopes=['https://www.googleapis.com/auth/drive.readonly'],
    )

    service = build('drive', 'v3', credentials=credentials)

    # Get file metadata for the filename
    meta = service.files().get(fileId=job.source_file_id, fields='name,mimeType').execute()
    filename = meta.get('name', f'sermon_{job.pk}.mp3')

    # Download
    request = service.files().get_media(fileId=job.source_file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)

    done = False
    while not done:
        status_obj, done = downloader.next_chunk()
        pct = int(status_obj.progress() * 50) + 10  # maps 0-100% download to 10-60% overall
        job.set_progress(pct)

    buffer.seek(0)
    return buffer.read(), filename


def _download_from_url(job: 'CloudImportJob'):
    import urllib.request

    job.set_progress(10, ImportStatus.DOWNLOADING)

    url = job.source_url
    filename = url.split('/')[-1].split('?')[0] or 'sermon.mp3'

    with urllib.request.urlopen(url) as response:
        content = response.read()

    job.set_progress(55)
    return content, filename


def _create_sermon(job: 'CloudImportJob', audio_bytes: bytes, filename: str):
    """Create the Sermon record and attach the audio file."""
    from apps.sermons.models import Sermon, Series, Tag

    series = None
    if job.sermon_series_id:
        try:
            series = Series.objects.get(pk=job.sermon_series_id)
        except Series.DoesNotExist:
            pass

    sermon = Sermon.objects.create(
        title=job.sermon_title or filename,
        speaker=job.sermon_speaker or '',
        series=series,
        sermon_date=job.sermon_date,
        uploaded_by=job.requested_by,
        is_published=False,  # admin must review before publishing
    )

    # Attach audio
    sermon.audio_file.save(filename, ContentFile(audio_bytes), save=True)

    # Tags
    if job.sermon_tags:
        for tag_name in [t.strip() for t in job.sermon_tags.split(',') if t.strip()]:
            tag, _ = Tag.objects.get_or_create(name=tag_name)
            sermon.tags.add(tag)

    job.sermon = sermon
    job.save(update_fields=['sermon', 'updated_at'])
