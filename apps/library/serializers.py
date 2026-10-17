from rest_framework import serializers

from apps.sermons.serializers import SermonListSerializer
from .models import COVER_SCAN, COVER_THUMBNAILS, Playlist, PlaylistItem, cover_items


class PlaylistSerializer(serializers.ModelSerializer):
    item_count = serializers.IntegerField(read_only=True, default=0)
    # Only present when the list was requested with ?sermon=<id>
    has_sermon = serializers.BooleanField(read_only=True, required=False)
    # Up to 4 distinct thumbnails from the first items, for the cover mosaic
    cover_thumbnails = serializers.SerializerMethodField()

    class Meta:
        model = Playlist
        fields = ['id', 'name', 'item_count', 'has_sermon', 'cover_thumbnails', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_cover_thumbnails(self, obj):
        # with_cover_items() prefetches these; otherwise query directly
        items = getattr(obj, 'cover_items', None)
        if items is None:
            items = cover_items().filter(playlist=obj)[:COVER_SCAN]
        request = self.context.get('request')
        seen, urls = set(), []
        for item in items:
            thumb = item.sermon.thumbnail
            if thumb.name in seen:
                continue
            seen.add(thumb.name)
            urls.append(request.build_absolute_uri(thumb.url) if request else thumb.url)
            if len(urls) == COVER_THUMBNAILS:
                break
        return urls

    def validate_name(self, value):
        value = ' '.join(value.split())
        if not value:
            raise serializers.ValidationError('Playlist name cannot be blank.')
        return value


class PlaylistItemSerializer(serializers.ModelSerializer):
    sermon = SermonListSerializer(read_only=True)

    class Meta:
        model = PlaylistItem
        fields = ['id', 'position', 'added_at', 'sermon']
