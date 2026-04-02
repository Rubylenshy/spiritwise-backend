"""
Audio streaming via presigned R2 URLs.

Flow:
  1. Browser requests /api/sermons/{id}/stream/?token=<signed>
  2. Django validates the token (JWT or signed token)
  3. Django generates a presigned R2 URL valid for 60 seconds
  4. Django returns 302 redirect to the presigned URL
  5. Browser follows redirect — R2 handles all streaming natively
     including Range requests, seeking, Content-Length, etc.

Why redirect instead of proxy?
  - R2 handles range requests perfectly out of the box
  - No memory pressure on Django (no buffering large audio chunks)
  - Presigned URLs expire in 60s so they can't be shared
  - Seeking, buffering, and playback speed all work correctly
"""
import logging
from django.http import HttpResponseRedirect, JsonResponse
from rest_framework_simplejwt.tokens import AccessToken

from .models import Sermon
from .r2 import get_r2_client
from .stream_token import validate_stream_token
from django.conf import settings

logger = logging.getLogger(__name__)

PRESIGNED_URL_EXPIRY = 60 * 60  # 1 hour — long enough for a full sermon


def _authenticate_stream(request, sermon_id: int):
    """
    Returns the User if authenticated via Bearer JWT or ?token= param.
    Returns None if authentication fails.
    """
    # Path 1: Authorization: Bearer <jwt>
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

    # Path 2: ?token= signed param (for <audio> element)
    token = request.GET.get('token', '')
    if token:
        return validate_stream_token(token, sermon_id)

    return None


def _make_presigned_url(r2_key: str) -> str:
    """Generate a presigned R2 URL valid for PRESIGNED_URL_EXPIRY seconds."""
    client = get_r2_client()
    return client.generate_presigned_url(
        'get_object',
        Params={
            'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
            'Key': r2_key,
        },
        ExpiresIn=PRESIGNED_URL_EXPIRY,
    )


def stream_sermon(request, pk):
    """
    Plain Django view (no @api_view wrapper — DRF interferes with redirects).

    GET /api/sermons/{pk}/stream/?token=<signed_token>
    OR  GET /api/sermons/{pk}/stream/ with Authorization: Bearer <jwt>

    Returns a 302 redirect to a presigned R2 URL.
    The presigned URL supports range requests natively.
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = JsonResponse({})
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Headers'] = 'Range, Authorization'
        return response

    # Authenticate
    user = _authenticate_stream(request, pk)
    if not user:
        response = JsonResponse(
            {'detail': 'Authentication required to stream.'},
            status=401,
        )
        response['Access-Control-Allow-Origin'] = '*'
        return response

    # Fetch sermon
    try:
        sermon = Sermon.objects.get(pk=pk, is_published=True)
    except Sermon.DoesNotExist:
        return JsonResponse({'detail': 'Sermon not found.'}, status=404)

    # R2-hosted file — generate presigned URL
    if sermon.r2_key:
        try:
            presigned_url = _make_presigned_url(sermon.r2_key)
            response = HttpResponseRedirect(presigned_url)
            response['Access-Control-Allow-Origin'] = '*'
            response['Cache-Control'] = 'no-store'
            return response
        except Exception as e:
            logger.error(f'Failed to generate presigned URL for sermon {pk}: {e}')
            return JsonResponse({'detail': f'Storage error: {str(e)}'}, status=503)

    # External URL fallback (no R2 key) — redirect directly
    if sermon.audio_url:
        response = HttpResponseRedirect(sermon.audio_url)
        response['Access-Control-Allow-Origin'] = '*'
        return response

    return JsonResponse({'detail': 'No audio file available.'}, status=404)
