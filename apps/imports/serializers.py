from rest_framework import serializers
from .models import CloudImportJob


class ImportJobSerializer(serializers.ModelSerializer):
    sermon_title_result = serializers.CharField(source='sermon.title', read_only=True)

    class Meta:
        model = CloudImportJob
        fields = [
            'id', 'source', 'status', 'progress_pct',
            'source_file_id', 'source_url',
            'sermon_title', 'sermon_speaker', 'sermon_series_id',
            'sermon_date', 'sermon_tags',
            'sermon', 'sermon_title_result',
            'error_message', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'status', 'progress_pct', 'sermon', 'error_message', 'created_at', 'updated_at']


class CreateImportJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = CloudImportJob
        fields = [
            'source', 'source_file_id', 'source_url',
            'sermon_title', 'sermon_speaker', 'sermon_series_id',
            'sermon_date', 'sermon_tags',
        ]

    def validate(self, attrs):
        source = attrs.get('source')
        if source == 'google_drive' and not attrs.get('source_file_id'):
            raise serializers.ValidationError({'source_file_id': 'Required for Google Drive imports.'})
        if source == 'url' and not attrs.get('source_url'):
            raise serializers.ValidationError({'source_url': 'Required for URL imports.'})
        return attrs
