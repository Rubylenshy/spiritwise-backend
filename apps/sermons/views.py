from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from apps.users.serializers import reward_payload
from .models import Sermon, Series, Tag, ListenHistory
from .serializers import (
    SermonListSerializer,
    SermonDetailSerializer,
    SeriesSerializer,
    TagSerializer,
    ProgressUpdateSerializer,
)

# Fraction of a sermon that must be played for it to count as completed.
# Keep in sync with COMPLETION_THRESHOLD in the frontend's AudioContext.jsx.
COMPLETION_THRESHOLD = 0.9


class SermonPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


# ── Sermons ───────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sermon_list(request):
    """
    GET /api/sermons/
    Query params: q, tag, series, speaker, page
    """
    qs = Sermon.objects.filter(is_published=True).prefetch_related('tags').select_related('series')

    q = request.query_params.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q) |
            Q(speaker__icontains=q) |
            Q(series__title__icontains=q) |
            Q(scripture_reference__icontains=q)
        )

    tag = request.query_params.get('tag', '').strip()
    if tag:
        qs = qs.filter(tags__slug=tag)

    series_id = request.query_params.get('series')
    if series_id:
        qs = qs.filter(series_id=series_id)

    speaker = request.query_params.get('speaker', '').strip()
    if speaker:
        qs = qs.filter(speaker__icontains=speaker)

    paginator = SermonPagination()
    page = paginator.paginate_queryset(qs, request)
    serializer = SermonListSerializer(page, many=True, context={'request': request})
    return paginator.get_paginated_response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sermon_detail(request, pk):
    """
    GET /api/sermons/<pk>/
    Returns full sermon data including signed audio URL.
    """
    try:
        sermon = (
            Sermon.objects
            .filter(is_published=True)
            .prefetch_related('tags', 'questions')
            .select_related('series')
            .get(pk=pk)
        )
    except Sermon.DoesNotExist:
        return Response({'detail': 'Sermon not found.'}, status=status.HTTP_404_NOT_FOUND)

    # Increment play count (best-effort)
    Sermon.objects.filter(pk=pk).update(play_count=sermon.play_count + 1)

    serializer = SermonDetailSerializer(sermon, context={'request': request})
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_progress(request, pk):
    """
    POST /api/sermons/<pk>/progress/
    Body: { progress_seconds, completed }
    Awards XP on first completion.

    A sermon counts as completed once 90% of it has been played. Completion
    is sticky: later syncs (e.g. re-listening from the start) never clear it,
    so the 50 XP is paid once per user per sermon.
    """
    try:
        sermon = Sermon.objects.get(pk=pk, is_published=True)
    except Sermon.DoesNotExist:
        return Response({'detail': 'Sermon not found.'}, status=status.HTTP_404_NOT_FOUND)

    serializer = ProgressUpdateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    history, created = ListenHistory.objects.get_or_create(
        user=request.user, sermon=sermon
    )

    progress_seconds = serializer.validated_data['progress_seconds']
    reached_threshold = (
        not sermon.duration_seconds
        or progress_seconds >= sermon.duration_seconds * COMPLETION_THRESHOLD
    )

    was_completed = history.completed
    history.progress_seconds = progress_seconds
    history.completed = was_completed or (
        serializer.validated_data['completed'] and reached_threshold
    )
    history.save()

    # Award XP only on first completion
    user = request.user
    xp_awarded = 0
    new_badges = []
    if history.completed and not was_completed:
        xp_awarded = 50
        new_badges += user.award_xp(xp_awarded, reason=f'Completed sermon: {sermon.title}')
        new_badges += user.record_activity('completed')
        completed_count = ListenHistory.objects.filter(user=user, completed=True).count()
        new_badges += user.award_badges('sermons', completed_count)

    return Response({
        'progress_seconds': history.progress_seconds,
        'completed': history.completed,
        **reward_payload(user, xp_awarded, new_badges),
    })


# ── Series ────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def series_list(request):
    """GET /api/sermons/series/"""
    qs = Series.objects.prefetch_related('sermons')
    serializer = SeriesSerializer(qs, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def series_detail(request, pk):
    """GET /api/sermons/series/<pk>/"""
    try:
        s = Series.objects.prefetch_related('sermons__tags').get(pk=pk)
    except Series.DoesNotExist:
        return Response({'detail': 'Series not found.'}, status=status.HTTP_404_NOT_FOUND)

    data = SeriesSerializer(s).data
    data['sermons'] = SermonListSerializer(
        s.sermons.filter(is_published=True), many=True, context={'request': request}
    ).data
    return Response(data)


# ── Tags ──────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def tag_list(request):
    """GET /api/sermons/tags/"""
    tags = Tag.objects.all()
    return Response(TagSerializer(tags, many=True).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_stream_token(request, pk):
    """
    GET /api/sermons/{pk}/stream-token/
    Returns a short-lived signed token the frontend uses to build
    an authenticated stream URL for the <audio> element.
    """
    try:
        Sermon.objects.get(pk=pk, is_published=True)
    except Sermon.DoesNotExist:
        return Response({'detail': 'Sermon not found.'}, status=status.HTTP_404_NOT_FOUND)

    from apps.sermons.stream_token import generate_stream_token
    token = generate_stream_token(request.user.id, pk)

    return Response({'token': token, 'sermon_id': pk})
