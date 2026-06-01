"""
apps/wordlookup/views.py — WL2

Endpoints:
  POST /api/wordlookup/lookup/      → fetch verse(s) for a reference or phrase
  POST /api/wordlookup/transcribe/  → Whisper fallback for unsupported browsers
  GET  /api/wordlookup/history/     → paginated list of the user's past lookups
"""

import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from .bible_apis import fetch_verse_by_query, fetch_verse
from .models import LookupHistory
from .serializers import (
    LookupRequestSerializer,
    LookupHistorySerializer,
)

logger = logging.getLogger(__name__)

# ── Rate limiting helper ──────────────────────────────────────────────────────
# Simple Redis-backed counter — reuses the existing Upstash Redis connection.

def _whisper_rate_limit_key(user_id: int) -> str:
    from django.utils import timezone
    today = timezone.now().date().isoformat()
    return f'wordlookup:whisper_limit:{user_id}:{today}'


def _check_whisper_limit(user_id: int, limit: int = 10) -> bool:
    try:
        from django.core.cache import cache
        key = _whisper_rate_limit_key(user_id)
        current = cache.get(key, 0)
        return int(current) < limit
    except Exception:
        return True  # Redis down — allow the request


def _increment_whisper_count(user_id: int):
    try:
        from django.core.cache import cache
        key = _whisper_rate_limit_key(user_id)
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, 60 * 60 * 25)
    except Exception:
        pass  # Redis down — skip counting


# ── POST /api/wordlookup/lookup/ ──────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def lookup(request):
    """
    Accepts either an exact reference ("John 3:16") or a thematic phrase
    ("the prodigal son").  For phrase lookups the AI resolver in WL3 will
    be called; in WL2 we resolve known thematic phrases via a lightweight
    local map and call the Bible API for the rest.

    Returns up to 3 results sorted by confidence:
        [{ reference, text, version, source, confidence, match_type }, …]
    """
    serializer = LookupRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    reference = serializer.validated_data.get('reference', '').strip()
    phrase = serializer.validated_data.get('phrase', '').strip()
    versions = serializer.validated_data.get('versions', ['ESV'])

    query = reference or phrase
    results = []

    # ── Exact reference path ───────────────────────────────────────────────────
    if reference:
        for version in versions[:3]:  # cap at 3 versions per request
            verse_data = fetch_verse_by_query(reference, version=version)
            if verse_data:
                results.append({
                    **verse_data,
                    'confidence': 1.0,
                    'match_type': 'exact',
                })

    # ── Thematic / phrase path ─────────────────────────────────────────────────
    # WL2: use the same thematic map bibleParser.js uses on the frontend,
    # mirrored here so the backend can resolve it independently.
    # WL3 will replace this with the Claude AI resolver for open-ended phrases.
    elif phrase:
        resolved = _resolve_thematic_phrase(phrase)
        if resolved:
            for version in versions[:2]:
                verse_data = fetch_verse(
                    resolved['book'],
                    resolved['chapter'],
                    resolved['verse'],
                    resolved.get('verse_end'),
                    version=version,
                )
                if verse_data:
                    results.append({
                        **verse_data,
                        'confidence': resolved.get('confidence', 0.9),
                        'match_type': 'inferred',
                    })
        # WL3 note: if resolved is None here we'll call the AI resolver

    # ── Save to history (best-effort) ──────────────────────────────────────────
    if results:
        best = results[0]
        # Truncate verse text for the snippet (first 200 chars)
        snippet = best.get('text', '')[:200]
        try:
            LookupHistory.objects.create(
                user=request.user,
                query=query,
                reference_found=best.get('reference', ''),
                verse_snippet=snippet,
                version=best.get('version', 'ESV'),
                match_type=best.get('match_type', 'exact'),
            )
        except Exception as e:
            logger.warning('Failed to save lookup history: %s', e)

    return Response({
        'query': query,
        'results': results,
    })


# ── POST /api/wordlookup/transcribe/ ─────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def transcribe(request):
    """
    Whisper-powered audio transcription fallback.
    Only called when the browser doesn't support Web Speech API.

    Rate limited: 10 requests / user / day.
    Accepts: multipart/form-data with 'audio_file' field.
    Returns: { transcript: string }
    """
    if not _check_whisper_limit(request.user.id):
        return Response(
            {'detail': 'Daily transcription limit reached (10 per day). '
                       'The microphone feature works directly in Chrome and Edge '
                       'without any server-side transcription.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    audio_file = request.FILES.get('audio_file')
    if not audio_file:
        return Response(
            {'detail': 'audio_file is required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Validate file type
    allowed_types = ['audio/mpeg', 'audio/mp4', 'audio/ogg', 'audio/wav',
                     'audio/webm', 'audio/flac', 'audio/x-m4a']
    if audio_file.content_type not in allowed_types:
        return Response(
            {'detail': f'Unsupported audio format: {audio_file.content_type}'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 25 MB limit
    if audio_file.size > 25 * 1024 * 1024:
        return Response(
            {'detail': 'File too large. Maximum size is 25 MB.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        import openai
        client = openai.OpenAI()   # reads OPENAI_API_KEY from env
        response = client.audio.transcriptions.create(
            model='whisper-1',
            file=(audio_file.name, audio_file.read(), audio_file.content_type),
            response_format='text',
        )
        _increment_whisper_count(request.user.id)
        return Response({'transcript': response})

    except ImportError:
        return Response(
            {'detail': 'OpenAI package not installed. '
                       'Run: pip install openai --break-system-packages'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except Exception as e:
        logger.error('Whisper transcription failed: %s', e)
        return Response(
            {'detail': 'Transcription failed. Please try again.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


# ── GET /api/wordlookup/history/ ─────────────────────────────────────────────

class LookupHistoryPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 50


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def history(request):
    """
    GET /api/wordlookup/history/
    Returns the current user's recent lookups, newest first.
    """
    qs = LookupHistory.objects.filter(user=request.user)
    paginator = LookupHistoryPagination()
    page = paginator.paginate_queryset(qs, request)
    serializer = LookupHistorySerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)


# ── Thematic phrase resolver (WL2 version) ────────────────────────────────────
# Mirrors the THEMATIC table in bibleParser.js so the backend can resolve
# the same phrases independently.  WL3 will add AI for open-ended phrases.

_THEMATIC_MAP = [
    {'patterns': ['sermon on the mount', 'beatitudes'],
     'book': 'Matthew', 'chapter': 5, 'verse': 1, 'verse_end': 12, 'confidence': 0.95},
    {'patterns': ['prodigal son'],
     'book': 'Luke', 'chapter': 15, 'verse': 11, 'verse_end': 32, 'confidence': 0.97},
    {'patterns': ['feeding of the five thousand', 'feeding five thousand', 'fed five thousand'],
     'book': 'Matthew', 'chapter': 14, 'verse': 13, 'verse_end': 21, 'confidence': 0.95},
    {'patterns': ['good samaritan'],
     'book': 'Luke', 'chapter': 10, 'verse': 25, 'verse_end': 37, 'confidence': 0.97},
    {'patterns': ["lord's prayer", 'our father'],
     'book': 'Matthew', 'chapter': 6, 'verse': 9, 'verse_end': 13, 'confidence': 0.93},
    {'patterns': ['ten commandments'],
     'book': 'Exodus', 'chapter': 20, 'verse': 1, 'verse_end': 17, 'confidence': 0.95},
    {'patterns': ['valley of the shadow', 'shepherd psalm', 'psalm 23'],
     'book': 'Psalms', 'chapter': 23, 'verse': 1, 'verse_end': 6, 'confidence': 0.97},
    {'patterns': ['armour of god', 'armor of god'],
     'book': 'Ephesians', 'chapter': 6, 'verse': 10, 'verse_end': 18, 'confidence': 0.95},
    {'patterns': ['mustard seed'],
     'book': 'Matthew', 'chapter': 17, 'verse': 20, 'verse_end': None, 'confidence': 0.90},
    {'patterns': ['walking on water'],
     'book': 'Matthew', 'chapter': 14, 'verse': 22, 'verse_end': 33, 'confidence': 0.92},
    {'patterns': ['raising of lazarus', 'lazarus'],
     'book': 'John', 'chapter': 11, 'verse': 1, 'verse_end': 44, 'confidence': 0.88},
    {'patterns': ['great commission'],
     'book': 'Matthew', 'chapter': 28, 'verse': 16, 'verse_end': 20, 'confidence': 0.95},
    {'patterns': ['last supper'],
     'book': 'Luke', 'chapter': 22, 'verse': 14, 'verse_end': 20, 'confidence': 0.95},
    {'patterns': ['transfiguration'],
     'book': 'Matthew', 'chapter': 17, 'verse': 1, 'verse_end': 9, 'confidence': 0.95},
    {'patterns': ['resurrection'],
     'book': 'John', 'chapter': 20, 'verse': 1, 'verse_end': 18, 'confidence': 0.88},
]


def _resolve_thematic_phrase(phrase: str) -> dict | None:
    """
    Check if phrase matches any known thematic pattern.
    Returns a resolution dict or None.
    """
    phrase_lower = phrase.lower()
    for entry in _THEMATIC_MAP:
        for pattern in entry['patterns']:
            if pattern in phrase_lower:
                return {
                    'book': entry['book'],
                    'chapter': entry['chapter'],
                    'verse': entry['verse'],
                    'verse_end': entry.get('verse_end'),
                    'confidence': entry.get('confidence', 0.9),
                }
    return None
