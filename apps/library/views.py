"""
Library — the user's favorites and playlists. Everything here is private to
request.user; other users' playlists 404 rather than 403.
"""
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, Max, OuterRef
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.sermons.models import Sermon
from apps.sermons.serializers import SermonListSerializer
from .models import Favorite, Playlist, PlaylistItem
from .serializers import PlaylistItemSerializer, PlaylistSerializer


class LibraryPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


def _published_sermon(pk):
    try:
        return Sermon.objects.filter(pk=int(pk), is_published=True).first()
    except (TypeError, ValueError):
        return None


# ── Favorites ─────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def favorite_list(request):
    """GET /api/library/favorites/ — the user's favorited sermons, newest first."""
    favorites = (
        Favorite.objects
        .filter(user=request.user, sermon__is_published=True)
        .select_related('sermon__series')
        .prefetch_related('sermon__tags')
    )
    paginator = LibraryPagination()
    page = paginator.paginate_queryset(favorites, request)
    sermons = []
    for fav in page:
        fav.sermon.is_favorited = True
        sermons.append(fav.sermon)
    data = SermonListSerializer(sermons, many=True, context={'request': request}).data
    return paginator.get_paginated_response(data)


@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def favorite_detail(request, sermon_id):
    """
    PUT    /api/library/favorites/<sermon_id>/ — favorite (idempotent)
    DELETE /api/library/favorites/<sermon_id>/ — unfavorite (idempotent)
    """
    if request.method == 'DELETE':
        Favorite.objects.filter(user=request.user, sermon_id=sermon_id).delete()
        return Response({'sermon_id': sermon_id, 'is_favorited': False})

    sermon = _published_sermon(sermon_id)
    if not sermon:
        return Response({'detail': 'Sermon not found.'}, status=status.HTTP_404_NOT_FOUND)
    Favorite.objects.get_or_create(user=request.user, sermon=sermon)
    return Response({'sermon_id': sermon_id, 'is_favorited': True})


# ── Playlists ─────────────────────────────────────────────────────────────────

def _user_playlists(user):
    return Playlist.objects.filter(user=user).annotate(item_count=Count('items'))


def _get_playlist(request, pk):
    return _user_playlists(request.user).filter(pk=pk).first()


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def playlist_list(request):
    """
    GET  /api/library/playlists/[?sermon=<id>] — all of the user's playlists;
         with ?sermon, each carries has_sermon for "Add to playlist" menus.
    POST /api/library/playlists/ { name, sermon_id? } — create, optionally
         with a first sermon.
    """
    if request.method == 'GET':
        qs = _user_playlists(request.user)
        sermon_id = request.query_params.get('sermon')
        if sermon_id and sermon_id.isdigit():
            qs = qs.annotate(has_sermon=Exists(
                PlaylistItem.objects.filter(playlist=OuterRef('pk'), sermon_id=int(sermon_id))
            ))
        return Response(PlaylistSerializer(qs, many=True).data)

    serializer = PlaylistSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    sermon = None
    if request.data.get('sermon_id'):
        sermon = _published_sermon(request.data['sermon_id'])
        if not sermon:
            return Response({'detail': 'Sermon not found.'}, status=status.HTTP_404_NOT_FOUND)

    with transaction.atomic():
        playlist = serializer.save(user=request.user)
        if sermon:
            PlaylistItem.objects.create(playlist=playlist, sermon=sermon, position=1)
    return Response(
        PlaylistSerializer(_get_playlist(request, playlist.pk)).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def playlist_detail(request, pk):
    """GET / PATCH { name } / DELETE /api/library/playlists/<pk>/"""
    playlist = _get_playlist(request, pk)
    if not playlist:
        return Response({'detail': 'Playlist not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'DELETE':
        playlist.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    if request.method == 'PATCH':
        serializer = PlaylistSerializer(playlist, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()

    return Response(PlaylistSerializer(playlist).data)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def playlist_items(request, pk):
    """
    GET  /api/library/playlists/<pk>/items/ — paginated, in playlist order
    POST /api/library/playlists/<pk>/items/ { sermon_id } — append (no duplicates)
    """
    playlist = _get_playlist(request, pk)
    if not playlist:
        return Response({'detail': 'Playlist not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        items = (
            playlist.items
            .filter(sermon__is_published=True)
            .select_related('sermon__series')
            .prefetch_related('sermon__tags')
            .annotate(sermon_is_favorited=Exists(
                Favorite.objects.filter(user=request.user, sermon=OuterRef('sermon'))
            ))
        )
        paginator = LibraryPagination()
        page = paginator.paginate_queryset(items, request)
        for item in page:
            item.sermon.is_favorited = item.sermon_is_favorited
        data = PlaylistItemSerializer(page, many=True, context={'request': request}).data
        return paginator.get_paginated_response(data)

    sermon = _published_sermon(request.data.get('sermon_id'))
    if not sermon:
        return Response({'detail': 'Sermon not found.'}, status=status.HTTP_404_NOT_FOUND)

    existing = playlist.items.filter(sermon=sermon).first()
    if existing:
        return Response(PlaylistItemSerializer(existing, context={'request': request}).data)

    try:
        with transaction.atomic():
            last = playlist.items.aggregate(m=Max('position'))['m'] or 0
            item = PlaylistItem.objects.create(playlist=playlist, sermon=sermon, position=last + 1)
            playlist.save(update_fields=['updated_at'])
    except IntegrityError:  # a concurrent add of the same sermon won
        item = playlist.items.get(sermon=sermon)
    return Response(
        PlaylistItemSerializer(item, context={'request': request}).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def playlist_item_detail(request, pk, sermon_id):
    """DELETE /api/library/playlists/<pk>/items/<sermon_id>/"""
    playlist = _get_playlist(request, pk)
    if not playlist:
        return Response({'detail': 'Playlist not found.'}, status=status.HTTP_404_NOT_FOUND)
    if playlist.items.filter(sermon_id=sermon_id).delete()[0]:
        playlist.save(update_fields=['updated_at'])
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def playlist_item_move(request, pk, sermon_id):
    """
    POST /api/library/playlists/<pk>/items/<sermon_id>/move/ { direction: 'up' | 'down' }
    Swaps the item with its neighbour. Moving past either end is a no-op.
    """
    direction = request.data.get('direction')
    if direction not in ('up', 'down'):
        return Response({'detail': "direction must be 'up' or 'down'."}, status=status.HTTP_400_BAD_REQUEST)

    playlist = _get_playlist(request, pk)
    if not playlist:
        return Response({'detail': 'Playlist not found.'}, status=status.HTTP_404_NOT_FOUND)

    with transaction.atomic():
        items = playlist.items.select_for_update()
        item = items.filter(sermon_id=sermon_id).first()
        if not item:
            return Response({'detail': 'Sermon is not in this playlist.'}, status=status.HTTP_404_NOT_FOUND)

        if direction == 'up':
            neighbour = items.filter(position__lt=item.position).order_by('-position').first()
        else:
            neighbour = items.filter(position__gt=item.position).order_by('position').first()

        if neighbour:
            item.position, neighbour.position = neighbour.position, item.position
            PlaylistItem.objects.bulk_update([item, neighbour], ['position'])
            playlist.save(update_fields=['updated_at'])

    return Response({'detail': 'Moved.' if neighbour else 'Already at the end.'})
