from rest_framework import serializers
from .models import Sermon, Series, Tag, SermonQuestion, ListenHistory


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['id', 'name', 'slug']


class SeriesSerializer(serializers.ModelSerializer):
    sermon_count = serializers.IntegerField(source='sermons.count', read_only=True)

    class Meta:
        model = Series
        fields = ['id', 'title', 'slug', 'description', 'cover_image', 'sermon_count', 'created_at']


class SermonQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SermonQuestion
        fields = ['id', 'text', 'order']


class SermonListSerializer(serializers.ModelSerializer):
    """Lightweight — used in library listings."""
    tags = TagSerializer(many=True, read_only=True)
    series_title = serializers.CharField(source='series.title', read_only=True)

    class Meta:
        model = Sermon
        fields = [
            'id', 'title', 'slug', 'speaker', 'series_title',
            'tags', 'duration_display', 'sermon_date', 'thumbnail',
            'play_count', 'scripture_reference',
        ]


class SermonDetailSerializer(serializers.ModelSerializer):
    """Full detail — used in the player page."""
    tags = TagSerializer(many=True, read_only=True)
    series = SeriesSerializer(read_only=True)
    questions = SermonQuestionSerializer(many=True, read_only=True)
    audio_signed_url = serializers.SerializerMethodField()
    user_progress = serializers.SerializerMethodField()
    next_sermon = serializers.SerializerMethodField()

    class Meta:
        model = Sermon
        fields = [
            'id', 'title', 'slug', 'speaker', 'series', 'tags',
            'description', 'audio_signed_url', 'duration_seconds', 'duration_display',
            'scripture_reference', 'sermon_date', 'thumbnail',
            'play_count', 'questions', 'user_progress', 'next_sermon',
        ]

    def get_audio_signed_url(self, obj):
        """
        Returns the stream URL with an embedded signed token so the
        HTML5 <audio> element can authenticate without sending headers.
        Format: /api/sermons/{id}/stream/?token=<signed>
        """
        request = self.context.get('request')

        if not request:
            return None

        if obj.r2_key or obj.audio_url:
            # Generate a short-lived signed token for this user + sermon
            from apps.sermons.stream_token import generate_stream_token
            token = generate_stream_token(request.user.id, obj.pk)
            base_url = request.build_absolute_uri(f'/api/sermons/{obj.pk}/stream/')
            return f'{base_url}?token={token}'

        # Local file fallback (dev only, no token needed)
        if obj.audio_file:
            return request.build_absolute_uri(obj.audio_file.url)

        return None

    def get_user_progress(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        try:
            history = ListenHistory.objects.get(user=request.user, sermon=obj)
            return {
                'progress_seconds': history.progress_seconds,
                'completed': history.completed,
            }
        except ListenHistory.DoesNotExist:
            return {'progress_seconds': 0, 'completed': False}

    def get_next_sermon(self, obj):
        """Next sermon in the same series, or None."""
        if not obj.series:
            return None
        next_s = (
            Sermon.objects
            .filter(series=obj.series, is_published=True)
            .exclude(pk=obj.pk)
            .order_by('sermon_date', 'created_at')
            .first()
        )
        if not next_s:
            return None
        request = self.context.get('request')
        return {
            'id': next_s.id,
            'title': next_s.title,
            'speaker': next_s.speaker,
            'duration_display': next_s.duration_display,
            'thumbnail': request.build_absolute_uri(next_s.thumbnail.url)
                if next_s.thumbnail and request else None,
        }


class ProgressUpdateSerializer(serializers.Serializer):
    progress_seconds = serializers.IntegerField(min_value=0)
    completed = serializers.BooleanField(default=False)

