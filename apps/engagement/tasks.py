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
    Runs daily at 00:05 UTC.
    For each user with an active streak who missed yesterday:
    - If they have a freeze available, consume it silently (streak survives)
    - Otherwise reset streak to 0
    """
    from django.utils.timezone import now
    yesterday = now().date() - timezone.timedelta(days=1)
    two_days_ago = now().date() - timezone.timedelta(days=2)

    at_risk = User.objects.filter(
        current_streak__gt=0
    ).exclude(
        last_active_date__gte=yesterday
    )

    frozen = 0
    reset = 0

    for user in at_risk:
        if user.streak_freeze_available and user.last_active_date and user.last_active_date >= two_days_ago:
            # Grace day used automatically
            user.streak_freeze_available = False
            user.last_active_date = yesterday  # bridge the gap
            user.save(update_fields=['streak_freeze_available', 'last_active_date'])
            frozen += 1
        else:
            user.current_streak = 0
            user.save(update_fields=['current_streak'])
            reset += 1

    return f'Streaks: {frozen} protected by freeze, {reset} reset'


@shared_task(name='engagement.send_streak_reminders')
def send_streak_reminders():
    """
    Runs daily at 6pm UTC.
    Sends a reminder email to users who have a streak > 0 but
    haven't been active today.
    """
    from django.core.mail import send_mass_mail
    from django.utils.timezone import now

    today = now().date()

    at_risk = User.objects.filter(
        current_streak__gt=0,
        email_reminders=True,
        is_active=True,
    ).exclude(last_active_date=today)

    messages = []
    for user in at_risk:
        subject = f'🔥 Your {user.current_streak}-day streak needs you today'
        body = (
            f"Hi {user.first_name or user.username},\n\n"
            f"You're on a {user.current_streak}-day streak — don't break it!\n"
            f"Listen to a sermon today to keep your streak going.\n\n"
            f"Open SpiritWise → http://localhost:5173\n\n"
            f"— The SpiritWise team\n\n"
            f"To unsubscribe from reminders, visit your profile settings."
        )
        messages.append((subject, body, 'noreply@spiritwise.app', [user.email]))

    if messages:
        send_mass_mail(messages, fail_silently=True)

    return f'Sent {len(messages)} reminder emails'
