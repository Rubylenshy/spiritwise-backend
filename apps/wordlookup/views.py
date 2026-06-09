"""
apps/wordlookup/views.py — WL3

Changes from WL2:
  ✓ Phrase lookups now fall through to the AI resolver when the local
    thematic map doesn't match (WL3 core feature)
  ✓ Lookup endpoint returns up to 3 results sorted by confidence
  ✓ Each result carries confidence (0.0–1.0) and match_type
    ("exact" | "inferred")
  ✓ Saved verses endpoints added (WL3 stub, fully wired in WL4)

Endpoints:
  POST /api/wordlookup/lookup/      → fetch verse(s) for a reference or phrase
  POST /api/wordlookup/transcribe/  → Whisper fallback for unsupported browsers
  GET  /api/wordlookup/history/     → paginated list of the user's past lookups
  POST /api/wordlookup/saved/       → bookmark a verse (WL4)
  GET  /api/wordlookup/saved/       → list saved verses (WL4)
"""

import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from .bible_apis import fetch_verse_by_query, fetch_verse
from .models import LookupHistory, SavedVerse
from .serializers import (
    LookupRequestSerializer,
    LookupHistorySerializer,
    SavedVerseSerializer,
)

logger = logging.getLogger(__name__)


# ── Rate limiting helper ──────────────────────────────────────────────────────

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
        return True


def _increment_whisper_count(user_id: int):
    try:
        from django.core.cache import cache
        key = _whisper_rate_limit_key(user_id)
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, 60 * 60 * 25)
    except Exception:
        pass


# ── POST /api/wordlookup/lookup/ ──────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def lookup(request):
    """
    WL3: Full lookup pipeline.

    For exact references → Bible API directly (instant, no AI).
    For phrases → try local thematic map first (free, zero-latency),
                  then fall through to Claude AI resolver if unmatched.

    Returns up to 3 results sorted by confidence:
        {
            query: str,
            results: [{
                reference, text, version, source,
                confidence, match_type: "exact"|"inferred"
            }]
        }
    """
    serializer = LookupRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    reference = serializer.validated_data.get('reference', '').strip()
    phrase = serializer.validated_data.get('phrase', '').strip()
    versions = serializer.validated_data.get('versions', ['ESV'])

    query = reference or phrase
    results = []

    # ── Path 1: Exact reference ────────────────────────────────────────────────
    if reference:
        for version in versions[:3]:
            verse_data = fetch_verse_by_query(reference, version=version)
            if verse_data:
                results.append({
                    **verse_data,
                    'confidence': 1.0,
                    'match_type': 'exact',
                })

    # ── Path 2: Thematic phrase ────────────────────────────────────────────────
    elif phrase:
        # Step 1: Try the local thematic map (instant, free)
        resolved = _resolve_thematic_phrase(phrase)

        if resolved:
            # Local map matched — fetch from Bible API
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

        else:
            # Step 2: Local map didn't match — call Claude AI resolver (WL3)
            results = _ai_resolve_and_fetch(phrase, versions)

    # ── Save to history (best-effort) ──────────────────────────────────────────
    if results:
        best = results[0]
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


def _ai_resolve_and_fetch(phrase: str, versions: list[str]) -> list[dict]:
    """
    WL3 core: Call Claude to identify passage(s), then fetch actual verse text.

    Claude returns references (never verse text).
    The Bible API fetches the actual words.
    This prevents hallucinated scripture.
    """
    try:
        from .ai_resolver import resolve_phrase
        candidates = resolve_phrase(phrase)
    except Exception as e:
        logger.error('AI resolver import/call failed: %s', e)
        return []

    results = []

    for candidate in candidates[:3]:
        book = candidate['book']
        chapter = candidate['chapter']
        verse_start = candidate['verse_start']
        verse_end = candidate.get('verse_end')
        confidence = candidate['confidence']

        # Try each requested version; break on first success per candidate
        fetched = False
        for version in versions[:2]:
            verse_data = fetch_verse(book, chapter, verse_start, verse_end, version=version)
            if verse_data:
                results.append({
                    **verse_data,
                    'confidence': confidence,
                    'match_type': 'inferred',
                    'ai_reasoning': candidate.get('reasoning', ''),
                })
                fetched = True
                break

        # If primary version failed, try ESV as universal fallback
        if not fetched:
            verse_data = fetch_verse(book, chapter, verse_start, verse_end, version='ESV')
            if verse_data:
                results.append({
                    **verse_data,
                    'confidence': confidence * 0.85,  # slight penalty for version mismatch
                    'match_type': 'inferred',
                    'ai_reasoning': candidate.get('reasoning', ''),
                })

    return results


# ── POST /api/wordlookup/transcribe/ ─────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def transcribe(request):
    """
    Whisper-powered audio transcription fallback.
    Only called when the browser doesn't support Web Speech API.
    Rate limited: 10 requests / user / day.
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

    allowed_types = ['audio/mpeg', 'audio/mp4', 'audio/ogg', 'audio/wav',
                     'audio/webm', 'audio/flac', 'audio/x-m4a']
    if audio_file.content_type not in allowed_types:
        return Response(
            {'detail': f'Unsupported audio format: {audio_file.content_type}'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if audio_file.size > 25 * 1024 * 1024:
        return Response(
            {'detail': 'File too large. Maximum size is 25 MB.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        import openai
        client = openai.OpenAI()
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


# ── POST/GET /api/wordlookup/saved/ ──────────────────────────────────────────
# WL4 feature — endpoints are wired here so the URL routing is ready.

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def saved_verses(request):
    """
    GET  /api/wordlookup/saved/ — list bookmarked verses
    POST /api/wordlookup/saved/ — bookmark a new verse
    Body: { reference, verse_text, version, note_text? }
    """
    if request.method == 'GET':
        qs = SavedVerse.objects.filter(user=request.user)
        serializer = SavedVerseSerializer(qs, many=True)
        return Response(serializer.data)

    # POST — save a verse
    serializer = SavedVerseSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    try:
        verse, created = SavedVerse.objects.get_or_create(
            user=request.user,
            reference=serializer.validated_data['reference'],
            version=serializer.validated_data.get('version', 'ESV'),
            defaults={
                'verse_text': serializer.validated_data.get('verse_text', ''),
                'note_text': serializer.validated_data.get('note_text', ''),
            },
        )
    except Exception as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        SavedVerseSerializer(verse).data,
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_saved_verse(request, pk):
    """DELETE /api/wordlookup/saved/{pk}/"""
    try:
        verse = SavedVerse.objects.get(pk=pk, user=request.user)
    except SavedVerse.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
    verse.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# ── Thematic phrase resolver (local map — WL2, unchanged) ─────────────────────

_THEMATIC_MAP = [
    {'patterns': ['sermon on the mount', 'beatitudes'],
     'book': 'Matthew', 'chapter': 5, 'verse': 1, 'verse_end': 12, 'confidence': 0.95},
    {'patterns': ['prodigal son'],
     'book': 'Luke', 'chapter': 15, 'verse': 11, 'verse_end': 32, 'confidence': 0.97},
    {'patterns': ['feeding of the five thousand', 'feeding five thousand', 'fed five thousand'],
     'book': 'Matthew', 'chapter': 14, 'verse': 13, 'verse_end': 21, 'confidence': 0.95},
    {'patterns': ['good samaritan'],
     'book': 'Luke', 'chapter': 10, 'verse': 25, 'verse_end': 37, 'confidence': 0.97},
    {"patterns": ["lord's prayer", 'our father'],
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
