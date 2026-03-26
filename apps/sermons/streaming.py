"""
Spotify-style audio streaming through Django.

Authentication: two paths both supported —
  1. Authorization: Bearer <jwt>  (API calls, e.g. fetch())
  2. ?token=<signed_token>        (HTML5 <audio> element, which can't send headers)

Range requests enable instant seeking without re-downloading.
"""
import re
import requests as http_requests
from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import AccessToken

from .models import Sermon
from .r2 import get_object_range, get_object_metadata
from .stream_token import validate_stream_token

CHUNK_SIZE = 1024 * 512  # 512 KB


def _authenticate_stream(request, sermon_id: int):
    """
    Try to authenticate via Bearer token OR ?token= query param.
    Returns the User if authenticated, None otherwise.
    """
    # Path 1: standard Bearer JWT
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if auth_header.startswith('Bearer '):
        try:
            token_str = auth_header.split(' ')[1]
            access_token = AccessToken(token_str)
            from django.contrib.auth import get_user_model
            User = get_user_model()
            return User.objects.get(pk=access_token['user_id'])
        except Exception:
            pass

    # Path 2: signed ?token= query param (for <audio> element)
    token = request.GET.get('token', '')
    if token:
        return validate_stream_token(token, sermon_id)

    return None


def _parse_range_header(range_header: str, file_size: int) -> tuple:
    if not range_header:
        return 0, min(CHUNK_SIZE - 1, file_size - 1)

    match = re.match(r'bytes=(\d+)-(\d*)', range_header)
    if not match:
        return 0, min(CHUNK_SIZE - 1, file_size - 1)

    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else min(start + CHUNK_SIZE - 1, file_size - 1)
    end = min(end, file_size - 1)
    return start, end


def _proxy_external_url(url: str, request) -> HttpResponse:
    """Proxy an external audio URL through Django, forwarding Range headers."""
    headers = {}
    range_header = request.META.get('HTTP_RANGE', '')
    if range_header:
        headers['Range'] = range_header

    try:
        r = http_requests.get(url, headers=headers, stream=True, timeout=15)
        response = HttpResponse(
            r.content,
            status=r.status_code if r.status_code in (200, 206) else 200,
            content_type=r.headers.get('Content-Type', 'audio/mpeg'),
        )
        for h in ('Content-Length', 'Content-Range', 'Accept-Ranges'):
            if h in r.headers:
                response[h] = r.headers[h]
        response['Accept-Ranges'] = 'bytes'
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Expose-Headers'] = 'Content-Range, Content-Length, Accept-Ranges'
        return response
    except Exception as e:
        return HttpResponse(f'Stream error: {e}', status=503)


@api_view(['GET'])
@permission_classes([AllowAny])
def stream_sermon(request, pk):
    """
    GET /api/sermons/{pk}/stream/?token=<signed_token>
    OR  GET /api/sermons/{pk}/stream/ with Authorization: Bearer <jwt>

    Streams audio from R2 with full range request / seeking support.
    """
    # Authenticate via either method
    user = _authenticate_stream(request, pk)
    if not user:
        return Response(
            {'detail': 'Authentication required to stream.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    try:
        sermon = Sermon.objects.get(pk=pk, is_published=True)
    except Sermon.DoesNotExist:
        return Response({'detail': 'Sermon not found.'}, status=status.HTTP_404_NOT_FOUND)

    r2_key = sermon.r2_key

    # No R2 key — try proxying audio_url directly
    if not r2_key:
        if sermon.audio_url:
            return _proxy_external_url(sermon.audio_url, request)
        return Response(
            {'detail': 'No audio file available for this sermon.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Get file size from R2
    try:
        meta = get_object_metadata(r2_key)
    except Exception as e:
        return Response(
            {'detail': f'Audio file not accessible: {str(e)}'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    file_size = meta['size']
    content_type = meta['content_type']

    range_header = request.META.get('HTTP_RANGE', '')
    start, end = _parse_range_header(range_header, file_size)
    chunk_size = end - start + 1

    try:
        content, _, _ = get_object_range(r2_key, start, end)
    except Exception as e:
        return Response(
            {'detail': f'Streaming error: {str(e)}'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    response_status = 206 if range_header else 200
    response = HttpResponse(content, status=response_status, content_type=content_type)
    response['Content-Length'] = chunk_size
    response['Content-Range'] = f'bytes {start}-{end}/{file_size}'
    response['Accept-Ranges'] = 'bytes'
    response['Cache-Control'] = 'no-cache'
    response['Access-Control-Allow-Origin'] = '*'
    response['Access-Control-Allow-Headers'] = 'Range, Authorization'
    response['Access-Control-Expose-Headers'] = 'Content-Range, Content-Length, Accept-Ranges'

    return response
