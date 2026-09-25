from rest_framework import serializers

from apps.sermons.serializers import SermonListSerializer
from .models import Playlist, PlaylistItem


class PlaylistSerializer(serializers.ModelSerializer):
    item_count = serializers.IntegerField(read_only=True, default=0)
    # Only present when the list was requested with ?sermon=<id>
    has_sermon = serializers.BooleanField(read_only=True, required=False)

    class Meta:
        model = Playlist
        fields = ['id', 'name', 'item_count', 'has_sermon', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

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
