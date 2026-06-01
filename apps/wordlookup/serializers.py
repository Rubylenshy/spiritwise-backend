from rest_framework import serializers
from .models import LookupHistory, SavedVerse


class LookupRequestSerializer(serializers.Serializer):
    """
    Body for POST /api/wordlookup/lookup/

    Either 'reference' (exact, e.g. "John 3:16") or 'phrase' (thematic,
    e.g. "the prodigal son") must be supplied.  'versions' is optional —
    defaults to ['ESV'].
    """
    reference = serializers.CharField(max_length=300, required=False, allow_blank=True)
    phrase = serializers.CharField(max_length=500, required=False, allow_blank=True)
    versions = serializers.ListField(
        child=serializers.ChoiceField(choices=['ESV', 'NIV', 'KJV', 'NKJV', 'NLT']),
        required=False,
        default=['ESV'],
        max_length=5,
    )

    def validate(self, attrs):
        if not attrs.get('reference') and not attrs.get('phrase'):
            raise serializers.ValidationError(
                'Either "reference" or "phrase" is required.'
            )
        return attrs


class VerseResultSerializer(serializers.Serializer):
    """Single verse result returned inside the lookup response."""
    reference = serializers.CharField()
    text = serializers.CharField()
    version = serializers.CharField()
    source = serializers.CharField()
    confidence = serializers.FloatField(default=1.0)
    match_type = serializers.ChoiceField(choices=['exact', 'inferred'], default='exact')


class LookupResponseSerializer(serializers.Serializer):
    """Full response for POST /api/wordlookup/lookup/"""
    query = serializers.CharField()
    results = VerseResultSerializer(many=True)


class LookupHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = LookupHistory
        fields = [
            'id', 'query', 'reference_found', 'verse_snippet',
            'version', 'match_type', 'created_at',
        ]
        read_only_fields = fields


class TranscribeResponseSerializer(serializers.Serializer):
    transcript = serializers.CharField()


class SavedVerseSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedVerse
        fields = ['id', 'reference', 'verse_text', 'version', 'note_text', 'created_at']
        read_only_fields = ['id', 'created_at']
