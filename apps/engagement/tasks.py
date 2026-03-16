from celery import shared_task
from django.utils import timezone
from django.db.models import Sum
from django.contrib.auth import get_user_model

User = get_user_model()


@shared_task(name='engagement.refresh_weekly_leaderboard')
def refresh_weekly_leaderboard():
    """
    Recomputes the weekly leaderboard snapshot.
    Scheduled to run every Sunday night via django-celery-beat.
    """
    from .models import LeaderboardEntry
    from apps.users.models import XPTransaction

    today = timezone.now().date()
    week_start = today - timezone.timedelta(days=today.weekday())  # Monday

    # Sum XP transactions created this week per user
    weekly_xp = (
        XPTransaction.objects
        .filter(created_at__date__gte=week_start)
        .values('user')
        .annotate(total_xp=Sum('points'))
        .order_by('-total_xp')
    )

    LeaderboardEntry.objects.filter(period='weekly', week_start=week_start).delete()

    entries = []
    for rank, row in enumerate(weekly_xp, start=1):
        entries.append(LeaderboardEntry(
            user_id=row['user'],
            period='weekly',
            xp=row['total_xp'],
            rank=rank,
            week_start=week_start,
        ))

    LeaderboardEntry.objects.bulk_create(entries)
    return f'Leaderboard refreshed: {len(entries)} entries for week starting {week_start}'


@shared_task(name='engagement.refresh_all_time_leaderboard')
def refresh_all_time_leaderboard():
    """Updates the all-time leaderboard from user.xp_points."""
    from .models import LeaderboardEntry

    users_by_xp = User.objects.order_by('-xp_points').values('id', 'xp_points')

    LeaderboardEntry.objects.filter(period='all_time').delete()

    entries = [
        LeaderboardEntry(
            user_id=row['id'],
            period='all_time',
            xp=row['xp_points'],
            rank=rank,
        )
        for rank, row in enumerate(users_by_xp, start=1)
    ]
    LeaderboardEntry.objects.bulk_create(entries)
    return f'All-time leaderboard refreshed: {len(entries)} entries'


@shared_task(name='engagement.check_broken_streaks')
def check_broken_streaks():
    """
    Runs daily to reset streaks for users who missed yesterday.
    """
    from django.utils.timezone import now
    yesterday = now().date() - timezone.timedelta(days=1)

    broken = User.objects.filter(
        current_streak__gt=0
    ).exclude(
        last_active_date__gte=yesterday
    )

    count = broken.count()
    broken.update(current_streak=0)
    return f'Reset streaks for {count} users'
