from django.db.models import Count, Q
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from apps.library.models import with_favorited
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
    Query params: q, tag, series, speaker (exact, case-insensitive), page, page_size
    """
    qs = with_favorited(
        Sermon.objects.filter(is_published=True).prefetch_related('tags').select_related('series'),
        request.user,
    )

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
        qs = qs.filter(speaker__iexact=speaker)

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
            with_favorited(Sermon.objects.filter(is_published=True), request.user)
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
    """
    GET /api/sermons/series/
    Series with at least one published sermon. ?all=1 includes empty ones
    (the import page needs them to pick from).
    """
    qs = Series.objects.annotate(
        published_count=Count('sermons', filter=Q(sermons__is_published=True))
    )
    if request.query_params.get('all') != '1':
        qs = qs.filter(published_count__gt=0)
    serializer = SeriesSerializer(qs, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def series_detail(request, pk):
    """
    GET /api/sermons/series/<pk>/
    Series metadata only — page through its sermons with /sermons/?series=<pk>.
    """
    try:
        s = Series.objects.get(pk=pk)
    except Series.DoesNotExist:
        return Response({'detail': 'Series not found.'}, status=status.HTTP_404_NOT_FOUND)
    return Response(SeriesSerializer(s).data)


# ── Speakers ──────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def speaker_list(request):
    """
    GET /api/sermons/speakers/
    [{ name, sermon_count }] across published sermons, alphabetical.
    """
    rows = (
        Sermon.objects.filter(is_published=True)
        .exclude(speaker='')
        .values('speaker')
        .annotate(sermon_count=Count('id'))
        .order_by('speaker')
    )
    return Response([{'name': r['speaker'], 'sermon_count': r['sermon_count']} for r in rows])


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
