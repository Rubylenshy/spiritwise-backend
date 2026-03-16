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

    class Meta:
        model = Sermon
        fields = [
            'id', 'title', 'slug', 'speaker', 'series', 'tags',
            'description', 'audio_signed_url', 'duration_seconds', 'duration_display',
            'scripture_reference', 'sermon_date', 'thumbnail',
            'play_count', 'questions', 'user_progress',
        ]

    def get_audio_signed_url(self, obj):
        """
        Returns a signed S3 URL if using cloud storage,
        otherwise returns the direct file URL.
        """
        request = self.context.get('request')
        from django.conf import settings

        if obj.audio_url:
            return obj.audio_url

        if obj.audio_file:
            if getattr(settings, 'USE_S3', False):
                # Generate signed URL via boto3
                import boto3
                from botocore.config import Config
                s3 = boto3.client(
                    's3',
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    region_name=settings.AWS_S3_REGION_NAME,
                    config=Config(signature_version='s3v4'),
                )
                return s3.generate_presigned_url(
                    'get_object',
                    Params={
                        'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
                        'Key': obj.audio_file.name,
                    },
                    ExpiresIn=settings.AWS_QUERYSTRING_EXPIRE,
                )
            elif request:
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


class ProgressUpdateSerializer(serializers.Serializer):
    progress_seconds = serializers.IntegerField(min_value=0)
    completed = serializers.BooleanField(default=False)
