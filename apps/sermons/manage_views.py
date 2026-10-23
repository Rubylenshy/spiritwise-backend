"""
Admin dashboard endpoints — staff-only editing of sermons, series and tags,
mounted under /api/sermons/manage/. Unlike the listener endpoints these see
unpublished sermons and empty series.
"""
from django.db.models import Count, Q
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from .models import Sermon, Series, Tag
from .serializers import SermonManageSerializer, SeriesManageSerializer, TagManageSerializer
from .views import SermonPagination


def _detail(request, obj, serializer_class, refetch):
    """Shared GET/PATCH/DELETE for one object; `refetch` reloads it with its annotations."""
    context = {'request': request}
    if request.method == 'DELETE':
        obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    if request.method == 'PATCH':
        serializer = serializer_class(obj, data=request.data, partial=True, context=context)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        obj = refetch(obj.pk)
    return Response(serializer_class(obj, context=context).data)


def _create(request, serializer_class, refetch):
    serializer = serializer_class(data=request.data, context={'request': request})
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    obj = refetch(serializer.save().pk)
    return Response(serializer_class(obj, context={'request': request}).data, status=status.HTTP_201_CREATED)


# ── Sermons ───────────────────────────────────────────────────────────────────

def _sermons():
    return Sermon.objects.select_related('series').prefetch_related('tags')


@api_view(['GET'])
@permission_classes([IsAdminUser])
def sermon_list(request):
    """
    GET /api/sermons/manage/sermons/?q=&status=published|draft&page=&page_size=
    Newest uploads first, so a fresh import is at the top.
    """
    qs = _sermons().order_by('-created_at')

    q = request.query_params.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q) | Q(speaker__icontains=q) | Q(series__title__icontains=q)
        )
    state = request.query_params.get('status')
    if state == 'published':
        qs = qs.filter(is_published=True)
    elif state == 'draft':
        qs = qs.filter(is_published=False)

    paginator = SermonPagination()
    page = paginator.paginate_queryset(qs, request)
    serializer = SermonManageSerializer(page, many=True, context={'request': request})
    return paginator.get_paginated_response(serializer.data)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAdminUser])
def sermon_detail(request, pk):
    """
    GET/PATCH /api/sermons/manage/sermons/<pk>/
    PATCH takes any of title, speaker, series (id or null), tag_ids, description,
    scripture_reference, sermon_date, is_published. Audio stays as uploaded;
    unpublish rather than delete.
    """
    try:
        sermon = _sermons().get(pk=pk)
    except Sermon.DoesNotExist:
        return Response({'detail': 'Sermon not found.'}, status=status.HTTP_404_NOT_FOUND)
    return _detail(request, sermon, SermonManageSerializer, lambda pk: _sermons().get(pk=pk))


# ── Series ────────────────────────────────────────────────────────────────────

def _series():
    return Series.objects.annotate(sermon_count=Count('sermons')).order_by('title')


@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser])
def series_list(request):
    """GET/POST /api/sermons/manage/series/ — every series, with its total sermon count."""
    if request.method == 'POST':
        return _create(request, SeriesManageSerializer, lambda pk: _series().get(pk=pk))
    return Response(SeriesManageSerializer(_series(), many=True, context={'request': request}).data)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def series_detail(request, pk):
    """GET/PATCH/DELETE /api/sermons/manage/series/<pk>/ — deleting leaves its sermons unassigned."""
    try:
        series = _series().get(pk=pk)
    except Series.DoesNotExist:
        return Response({'detail': 'Series not found.'}, status=status.HTTP_404_NOT_FOUND)
    return _detail(request, series, SeriesManageSerializer, lambda pk: _series().get(pk=pk))


# ── Tags ──────────────────────────────────────────────────────────────────────

def _tags():
    return Tag.objects.annotate(sermon_count=Count('sermons')).order_by('name')


@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser])
def tag_list(request):
    """GET/POST /api/sermons/manage/tags/ — every tag, with its sermon count."""
    if request.method == 'POST':
        return _create(request, TagManageSerializer, lambda pk: _tags().get(pk=pk))
    return Response(TagManageSerializer(_tags(), many=True).data)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def tag_detail(request, pk):
    """GET/PATCH/DELETE /api/sermons/manage/tags/<pk>/ — deleting removes it from its sermons."""
    try:
        tag = _tags().get(pk=pk)
    except Tag.DoesNotExist:
        return Response({'detail': 'Tag not found.'}, status=status.HTTP_404_NOT_FOUND)
    return _detail(request, tag, TagManageSerializer, lambda pk: _tags().get(pk=pk))
