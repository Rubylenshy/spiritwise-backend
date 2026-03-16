from django.db import models
from django.conf import settings
from apps.sermons.models import Sermon, SermonQuestion


class ActivityType(models.TextChoices):
    LISTENED = 'listened', 'Listened to sermon'
    COMPLETED = 'completed', 'Completed sermon'
    ANSWERED = 'answered', 'Answered reflection questions'
    STREAK = 'streak', 'Streak milestone'
    LOGIN = 'login', 'Daily login'


class StreakRecord(models.Model):
    """
    One row per user per day.
    Created automatically by User.record_activity().
    Used to display the weekly streak heat-map on the frontend.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='streak_records',
    )
    date = models.DateField()
    activity_type = models.CharField(
        max_length=20,
        choices=ActivityType.choices,
        default=ActivityType.LOGIN,
    )
    xp_earned = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = ('user', 'date')
        ordering = ['-date']

    def __str__(self):
        return f'{self.user.username} — {self.date}'


class QuestionAnswer(models.Model):
    """Stores a user's written answer to a reflection question."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='answers',
    )
    question = models.ForeignKey(
        SermonQuestion,
        on_delete=models.CASCADE,
        related_name='answers',
    )
    sermon = models.ForeignKey(
        Sermon,
        on_delete=models.CASCADE,
        related_name='question_answers',
    )
    answer_text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'question')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.username} → Q{self.question.order} ({self.sermon.title})'


class LeaderboardEntry(models.Model):
    """
    Weekly snapshot computed by a periodic Celery task.
    Avoids expensive GROUP BY queries on every leaderboard page load.
    """
    PERIOD_CHOICES = [('weekly', 'Weekly'), ('monthly', 'Monthly'), ('all_time', 'All Time')]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='leaderboard_entries',
    )
    period = models.CharField(max_length=10, choices=PERIOD_CHOICES, default='weekly')
    xp = models.PositiveIntegerField(default=0)
    rank = models.PositiveIntegerField(default=0)
    week_start = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['rank']
        unique_together = ('user', 'period', 'week_start')

    def __str__(self):
        return f'#{self.rank} {self.user.username} — {self.xp} XP ({self.period})'
