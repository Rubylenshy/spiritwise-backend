from rest_framework import serializers
from apps.users.serializers import UserPublicSerializer
from .models import StreakRecord, QuestionAnswer, LeaderboardEntry


class StreakRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = StreakRecord
        fields = ['date', 'activity_type', 'xp_earned']


class EngagementStatsSerializer(serializers.Serializer):
    """Aggregated stats returned by GET /api/engagement/stats/"""
    current_streak = serializers.IntegerField()
    longest_streak = serializers.IntegerField()
    xp_points = serializers.IntegerField()
    daily_goal_minutes = serializers.IntegerField()
    minutes_today = serializers.IntegerField()
    sermons_completed = serializers.IntegerField()
    last_7_days = StreakRecordSerializer(many=True)


class LogActivitySerializer(serializers.Serializer):
    activity_type = serializers.ChoiceField(choices=['listened', 'completed', 'answered', 'login'])
    xp_earned = serializers.IntegerField(min_value=0, default=0)
    date = serializers.DateField(required=False)


class QuestionAnswerSerializer(serializers.ModelSerializer):
    question_text = serializers.CharField(source='question.text', read_only=True)
    sermon_title = serializers.CharField(source='sermon.title', read_only=True)

    class Meta:
        model = QuestionAnswer
        fields = ['id', 'question', 'question_text', 'sermon', 'sermon_title', 'answer_text', 'created_at']
        read_only_fields = ['id', 'created_at', 'question_text', 'sermon_title']


class LeaderboardEntrySerializer(serializers.ModelSerializer):
    user = UserPublicSerializer(read_only=True)

    class Meta:
        model = LeaderboardEntry
        fields = ['rank', 'user', 'xp', 'period', 'week_start']
