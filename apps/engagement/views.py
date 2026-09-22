from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.sermons.models import ListenHistory
from .models import StreakRecord, QuestionAnswer, ActivityType
from .serializers import (
    EngagementStatsSerializer,
    LogActivitySerializer,
    QuestionAnswerSerializer,
    StreakRecordSerializer,
)

User = get_user_model()


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def stats(request):
    """
    GET /api/engagement/stats/
    Returns the current user's full engagement dashboard data.
    """
    user = request.user
    today = timezone.now().date()

    # Minutes listened today (sum of progress on sermons last updated today)
    from django.db.models import Sum
    today_history = ListenHistory.objects.filter(
        user=user,
        last_listened__date=today,
    ).aggregate(total=Sum('progress_seconds'))
    minutes_today = (today_history['total'] or 0) // 60

    sermons_completed = ListenHistory.objects.filter(user=user, completed=True).count()

    last_7 = StreakRecord.objects.filter(user=user).order_by('-date')[:7]

    from apps.users.models import UserBadge
    recent_badges = list(
        UserBadge.objects.filter(user=user)
        .select_related('badge')
        .order_by('-earned_at')[:5]
        .values('badge__name', 'badge__icon', 'badge__description', 'earned_at')
    )

    data = {
        'current_streak': user.live_streak,
        'longest_streak': user.longest_streak,
        'xp_points': user.xp_points,
        'daily_goal_minutes': user.daily_goal_minutes,
        'minutes_today': minutes_today,
        'sermons_completed': sermons_completed,
        'last_7_days': StreakRecordSerializer(last_7, many=True).data,
        'streak_freeze_available': user.streak_freeze_available,
        'streak_freeze_earned_at': user.streak_freeze_earned_at,
        'recent_badges': [
            {
                'name': b['badge__name'],
                'icon': b['badge__icon'],
                'description': b['badge__description'],
                'earned_at': str(b['earned_at']),
            }
            for b in recent_badges
        ],
    }
    return Response(EngagementStatsSerializer(data).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def log_activity(request):
    """
    POST /api/engagement/log/
    Body: { activity_type, xp_earned?, date? }
    Records a StreakRecord row and updates the user streak.
    """
    serializer = LogActivitySerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    date = serializer.validated_data.get('date') or timezone.now().date()
    xp = serializer.validated_data['xp_earned']

    StreakRecord.objects.update_or_create(
        user=user,
        date=date,
        defaults={
            'activity_type': serializer.validated_data['activity_type'],
            'xp_earned': xp,
        },
    )

    user.record_activity()

    if xp:
        user.award_xp(xp, reason=f'Activity: {serializer.validated_data["activity_type"]}')

    return Response({
        'current_streak': user.current_streak,
        'xp_points': user.xp_points,
    })


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def question_answers(request):
    """
    GET  /api/engagement/answers/          — list current user's answers
    POST /api/engagement/answers/          — save an answer, award 10 XP
    Body: { question, sermon, answer_text }
    """
    if request.method == 'GET':
        answers = QuestionAnswer.objects.filter(user=request.user).select_related('question', 'sermon')
        return Response(QuestionAnswerSerializer(answers, many=True).data)

    serializer = QuestionAnswerSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    answer, created = QuestionAnswer.objects.update_or_create(
        user=request.user,
        question=serializer.validated_data['question'],
        defaults={
            'sermon': serializer.validated_data['sermon'],
            'answer_text': serializer.validated_data['answer_text'],
        },
    )

    xp_awarded = 0
    if created:
        xp_awarded = 10
        request.user.award_xp(xp_awarded, reason='Reflection question answered')
        request.user.record_activity()

    return Response({
        **QuestionAnswerSerializer(answer).data,
        'xp_awarded': xp_awarded,
    }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


def _period_start(period, today):
    """First day counted for a leaderboard period; None means all time."""
    if period == 'weekly':
        return today - timedelta(days=today.weekday())  # Monday
    if period == 'monthly':
        return today.replace(day=1)
    return None


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def leaderboard(request):
    """
    GET /api/engagement/leaderboard/?period=weekly|monthly|all_time
    Returns the top 50 users for the period, computed live: weekly/monthly sum
    the XP ledger since the period start, all-time uses user.xp_points.
    Tied XP shares a rank (1, 2, 2, 4).
    """
    period = request.query_params.get('period', 'weekly')
    if period not in ('weekly', 'monthly', 'all_time'):
        period = 'weekly'

    start = _period_start(period, timezone.now().date())
    users = User.objects.filter(is_active=True)
    if start:
        users = users.annotate(period_xp=Coalesce(
            Sum('xp_transactions__points', filter=Q(xp_transactions__created_at__date__gte=start)), 0,
        ))
    else:
        users = users.annotate(period_xp=F('xp_points'))
    ranked = users.filter(period_xp__gt=0)

    entries = []
    for i, user in enumerate(ranked.order_by('-period_xp', 'id')[:50]):
        rank = entries[-1]['rank'] if entries and entries[-1]['xp'] == user.period_xp else i + 1
        entries.append({
            'rank': rank,
            'user_id': user.id,
            'username': user.username,
            'streak': user.live_streak,
            'xp': user.period_xp,
            'period': period,
            'week_start': start,
        })

    my_xp = ranked.filter(pk=request.user.pk).values_list('period_xp', flat=True).first()
    my_rank = ranked.filter(period_xp__gt=my_xp).count() + 1 if my_xp else None

    return Response({
        'period': period,
        'my_rank': my_rank,
        'my_xp': my_xp or 0,
        'entries': entries,
    })
