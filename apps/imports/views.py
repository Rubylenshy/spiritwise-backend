"""
Import views — synchronous R2 upload with audio metadata extraction.

On upload:
  1. mutagen extracts duration, tags, album art from the audio file
  2. Audio uploaded to R2
  3. Album art (if present) uploaded to R2 as thumbnail
  4. Sermon record created with all extracted + submitted metadata
"""
import csv
import io
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.sermons.models import Sermon, Series, Tag
from apps.sermons.r2 import upload_audio, delete_audio, get_r2_client, build_public_url
from apps.sermons.audio_meta import extract_metadata
from .models import CloudImportJob
from .serializers import ImportJobSerializer
from django.conf import settings
from django.db import transaction
from django.utils.dateparse import parse_date
import uuid


def _is_admin(user):
    return user.is_staff or user.is_superuser


def _upload_cover_art(image_bytes: bytes, mime: str) -> str:
    """Upload cover art bytes to R2 and return the public URL."""
    ext_map = {
        'image/jpeg': '.jpg',
        'image/png':  '.png',
        'image/webp': '.webp',
    }
    ext = ext_map.get(mime, '.jpg')
    key = f'thumbnails/{uuid.uuid4().hex}{ext}'

    client = get_r2_client()
    client.upload_fileobj(
        io.BytesIO(image_bytes),
        settings.AWS_STORAGE_BUCKET_NAME,
        key,
        ExtraArgs={'ContentType': mime},
    )
    return build_public_url(key), key


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def parse_audio_metadata(request):
    """
    POST /api/imports/parse-metadata/
    Accepts a multipart file, returns extracted tags for form pre-fill.
    Does NOT store anything — purely for the frontend to read tags.
    """
    if not _is_admin(request.user):
        return Response({'detail': 'Admin access required.'}, status=status.HTTP_403_FORBIDDEN)

    audio_file = request.FILES.get('audio_file')
    if not audio_file:
        return Response({'detail': 'audio_file is required.'}, status=status.HTTP_400_BAD_REQUEST)

    meta = extract_metadata(audio_file)

    return Response({
        'title':            meta['title'],
        'artist':           meta['artist'],
        'album':            meta['album'],
        'date':             meta['date'][:10] if meta.get('date') else '',
        'comment':          meta['comment'],
        'duration_seconds': meta['duration_seconds'],
        'has_cover_art':    meta['cover_art'] is not None,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def import_list(request):
    """GET /api/imports/ — list recent import jobs."""
    if not _is_admin(request.user):
        return Response({'detail': 'Admin access required.'}, status=status.HTTP_403_FORBIDDEN)
    jobs = CloudImportJob.objects.all()[:50]
    return Response(ImportJobSerializer(jobs, many=True).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_sermon(request):
    """
    POST /api/imports/upload/
    multipart/form-data.

    Extracts duration + album art from the file automatically.
    Form fields: audio_file, sermon_title, sermon_speaker,
                 sermon_series, sermon_date, sermon_tags,
                 description, scripture_ref
    """
    if not _is_admin(request.user):
        return Response({'detail': 'Admin access required.'}, status=status.HTTP_403_FORBIDDEN)

    audio_file = request.FILES.get('audio_file')
    if not audio_file:
        return Response({'detail': 'audio_file is required.'}, status=status.HTTP_400_BAD_REQUEST)

    title = request.data.get('sermon_title', '').strip()
    if not title:
        return Response({'detail': 'sermon_title is required.'}, status=status.HTTP_400_BAD_REQUEST)

    job = CloudImportJob.objects.create(
        requested_by=request.user,
        source='local',
        sermon_title=title,
        sermon_speaker=request.data.get('sermon_speaker', ''),
        status='uploading',
        progress_pct=5,
    )

    try:
        # ── Step 1: Extract metadata ──────────────────────────────────────────
        meta = extract_metadata(audio_file)
        job.set_progress(15)

        # ── Step 2: Upload audio to R2 ────────────────────────────────────────
        result = upload_audio(
            file_obj=audio_file,
            original_filename=audio_file.name,
            sermon_title=title,
        )
        job.set_progress(70, 'processing')

        # ── Step 3: Upload album art if present ───────────────────────────────
        thumbnail_url = ''
        thumbnail_key = ''
        if meta['cover_art']:
            try:
                thumbnail_url, thumbnail_key = _upload_cover_art(
                    meta['cover_art'],
                    meta['cover_mime'] or 'image/jpeg',
                )
                job.set_progress(80)
            except Exception:
                pass  # Album art upload failure is non-fatal

        # ── Step 4: Resolve series ────────────────────────────────────────────
        series = None
        series_id = request.data.get('sermon_series')
        if series_id:
            try:
                series = Series.objects.get(pk=series_id)
            except Series.DoesNotExist:
                pass

        # ── Step 5: Create sermon record ──────────────────────────────────────
        # Duration: use extracted value, fall back to 0
        duration = meta['duration_seconds'] or 0

        sermon = Sermon.objects.create(
            title=title,
            speaker=request.data.get('sermon_speaker', '') or meta['artist'],
            series=series,
            description=request.data.get('description', '') or meta['comment'],
            scripture_reference=request.data.get('scripture_ref', ''),
            sermon_date=request.data.get('sermon_date') or (meta['date'][:10] if meta['date'] else None),
            audio_url=result['public_url'],
            r2_key=result['key'],
            duration_seconds=duration,
            uploaded_by=request.user,
            is_published=True,
        )

        # Attach thumbnail URL if we got one
        if thumbnail_url:
            sermon.audio_url = result['public_url']
            # Store thumbnail as URL in a custom field — or save via ImageField
            # For now store the URL directly on the model using audio_url pattern
            sermon.save(update_fields=['audio_url', 'duration_seconds'])

            # Save thumbnail URL into a URLField we'll add, or use existing ImageField path
            # Since thumbnail is an ImageField, save the R2 URL as the name
            from django.core.files.base import ContentFile
            sermon.thumbnail.save(
                f'thumb_{sermon.id}.jpg',
                ContentFile(meta['cover_art']),
                save=True,
            )

        # ── Step 6: Tags ──────────────────────────────────────────────────────
        tags_raw = request.data.get('sermon_tags', '')
        if tags_raw:
            for tag_name in [t.strip() for t in tags_raw.split(',') if t.strip()]:
                tag, _ = Tag.objects.get_or_create(name=tag_name)
                sermon.tags.add(tag)

        # ── Step 7: Complete ──────────────────────────────────────────────────
        job.sermon = sermon
        job.status = 'complete'
        job.progress_pct = 100
        job.save(update_fields=['sermon', 'status', 'progress_pct', 'updated_at'])

        return Response({
            'job_id':           job.id,
            'sermon_id':        sermon.id,
            'sermon_title':     sermon.title,
            'audio_url':        sermon.audio_url,
            'r2_key':           sermon.r2_key,
            'duration_seconds': sermon.duration_seconds,
            'duration_display': sermon.duration_display,
            'has_thumbnail':    bool(sermon.thumbnail),
            'message':          'Upload complete. Sermon is now live in the library.',
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        job.mark_failed(str(e))
        return Response(
            {'detail': f'Upload failed: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def import_detail(request, pk):
    """GET /api/imports/{pk}/"""
    if not _is_admin(request.user):
        return Response({'detail': 'Admin access required.'}, status=status.HTTP_403_FORBIDDEN)
    try:
        job = CloudImportJob.objects.get(pk=pk)
    except CloudImportJob.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
    return Response(ImportJobSerializer(job).data)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_sermon_audio(request, sermon_id):
    """DELETE /api/imports/sermon/{sermon_id}/audio/"""
    if not _is_admin(request.user):
        return Response({'detail': 'Admin access required.'}, status=status.HTTP_403_FORBIDDEN)
    try:
        sermon = Sermon.objects.get(pk=sermon_id)
    except Sermon.DoesNotExist:
        return Response({'detail': 'Sermon not found.'}, status=status.HTTP_404_NOT_FOUND)

    if sermon.r2_key:
        delete_audio(sermon.r2_key)
        sermon.r2_key = ''
        sermon.audio_url = ''
        sermon.save(update_fields=['r2_key', 'audio_url'])

    return Response({'detail': 'Audio removed. Upload a replacement via the import page.'})


_TRUE_STRINGS = {'1', 'true', 'yes', 'y'}
_FALSE_STRINGS = {'0', 'false', 'no', 'n'}


def _apply_csv_row(row):
    """
    Create or update one Sermon from a CSV row dict.
    Returns (sermon, created: bool). Raises ValueError on bad input.
    """
    row = {k.strip(): (v or '').strip() for k, v in row.items() if k}

    sermon = None
    row_id = row.get('id')
    row_slug = row.get('slug')
    if row_id:
        try:
            sermon = Sermon.objects.get(pk=int(row_id))
        except (Sermon.DoesNotExist, ValueError):
            raise ValueError(f"No sermon with id '{row_id}'.")
    elif row_slug:
        try:
            sermon = Sermon.objects.get(slug=row_slug)
        except Sermon.DoesNotExist:
            raise ValueError(f"No sermon with slug '{row_slug}'.")

    created = sermon is None
    if created and not row.get('title'):
        raise ValueError('title is required to create a new sermon.')

    if created:
        sermon = Sermon(title=row['title'])
    elif row.get('title'):
        sermon.title = row['title']

    if row.get('speaker'):
        sermon.speaker = row['speaker']
    if row.get('description'):
        sermon.description = row['description']
    if row.get('scripture_reference'):
        sermon.scripture_reference = row['scripture_reference']
    if row.get('audio_url'):
        sermon.audio_url = row['audio_url']

    if row.get('sermon_date'):
        parsed = parse_date(row['sermon_date'])
        if not parsed:
            raise ValueError(f"sermon_date '{row['sermon_date']}' is not in YYYY-MM-DD format.")
        sermon.sermon_date = parsed

    if row.get('is_published'):
        val = row['is_published'].lower()
        if val in _TRUE_STRINGS:
            sermon.is_published = True
        elif val in _FALSE_STRINGS:
            sermon.is_published = False
        else:
            raise ValueError(f"is_published '{row['is_published']}' must be true/false.")

    if row.get('series'):
        series, _ = Series.objects.get_or_create(title=row['series'])
        sermon.series = series

    sermon.save()

    if row.get('tags'):
        tag_names = [t.strip() for t in row['tags'].split(',') if t.strip()]
        tags = [Tag.objects.get_or_create(name=name)[0] for name in tag_names]
        sermon.tags.set(tags)

    return sermon, created


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_import_csv(request):
    """
    POST /api/imports/bulk-csv/
    multipart/form-data, field 'csv_file'.

    Bulk create/update Sermon metadata from a CSV. Each row is applied in its
    own transaction so one bad row doesn't block the rest of the batch.

    Columns (header row required, all optional except title-for-create):
      id, slug          — match an existing sermon to update (by pk or slug)
      title             — required when creating a new sermon
      speaker, description, scripture_reference, audio_url
      series            — series title, get-or-create
      tags              — comma-separated tag names, replaces existing tags
      sermon_date       — YYYY-MM-DD
      is_published      — true/false
    """
    if not _is_admin(request.user):
        return Response({'detail': 'Admin access required.'}, status=status.HTTP_403_FORBIDDEN)

    csv_file = request.FILES.get('csv_file')
    if not csv_file:
        return Response({'detail': 'csv_file is required.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        decoded = csv_file.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        return Response({'detail': 'File must be UTF-8 encoded CSV.'}, status=status.HTTP_400_BAD_REQUEST)

    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        return Response({'detail': 'CSV has no header row.'}, status=status.HTTP_400_BAD_REQUEST)

    results = []
    created_count = 0
    updated_count = 0
    failed_count = 0

    for line_num, row in enumerate(reader, start=2):  # header is line 1
        try:
            with transaction.atomic():
                sermon, created = _apply_csv_row(row)
            if created:
                created_count += 1
            else:
                updated_count += 1
            results.append({
                'row': line_num,
                'status': 'created' if created else 'updated',
                'sermon_id': sermon.id,
                'title': sermon.title,
            })
        except Exception as e:
            failed_count += 1
            results.append({
                'row': line_num,
                'status': 'error',
                'error': str(e),
            })

    return Response({
        'total': len(results),
        'created': created_count,
        'updated': updated_count,
        'failed': failed_count,
        'results': results,
    })
