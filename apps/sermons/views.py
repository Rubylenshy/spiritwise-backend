from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from .models import Sermon, Series, Tag, ListenHistory
from .serializers import (
    SermonListSerializer,
    SermonDetailSerializer,
    SeriesSerializer,
    TagSerializer,
    ProgressUpdateSerializer,
)


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

    was_completed = history.completed
    history.progress_seconds = serializer.validated_data['progress_seconds']
    history.completed = serializer.validated_data['completed']
    history.save()

    # Award XP only on first completion
    xp_awarded = 0
    if history.completed and not was_completed:
        xp_awarded = 50
        request.user.award_xp(xp_awarded, reason=f'Completed sermon: {sermon.title}')
        request.user.record_activity()

    return Response({
        'progress_seconds': history.progress_seconds,
        'completed': history.completed,
        'xp_awarded': xp_awarded,
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
