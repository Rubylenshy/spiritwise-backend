from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """
    Extended user model adding engagement tracking fields.
    USERNAME_FIELD stays 'username'; email is also required.
    """

    email = models.EmailField(unique=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)

    # Engagement
    xp_points = models.PositiveIntegerField(default=0)
    current_streak = models.PositiveIntegerField(default=0)
    longest_streak = models.PositiveIntegerField(default=0)
    last_active_date = models.DateField(null=True, blank=True)

    # Preferences
    daily_goal_minutes = models.PositiveSmallIntegerField(default=30)
    email_reminders = models.BooleanField(default=True)

    # Streak freeze — one grace day available after a 7-day streak
    streak_freeze_available = models.BooleanField(default=False)
    streak_freeze_earned_at = models.DateField(null=True, blank=True)

    REQUIRED_FIELDS = ['email', 'first_name']

    class Meta:
        verbose_name = 'user'
        verbose_name_plural = 'users'
        ordering = ['-date_joined']

    def __str__(self):
        return self.username

    # ── Streak logic ─────────────────────────────────────────────────────────

    def record_activity(self):
        """
        Call this whenever a user completes a meaningful engagement action.
        Increments the streak if they're active on consecutive days.
        Awards a streak freeze at every 7-day milestone.
        """
        today = timezone.now().date()

        if self.last_active_date == today:
            return  # Already recorded today

        days_gap = (today - self.last_active_date).days if self.last_active_date else None

        if days_gap == 1:
            self.current_streak += 1
        elif days_gap == 2 and self.streak_freeze_available:
            # Grace day used — protect the streak
            self.current_streak += 1
            self.streak_freeze_available = False
        else:
            # Streak broken or first activity ever
            self.current_streak = 1

        if self.current_streak > self.longest_streak:
            self.longest_streak = self.current_streak

        # Award a freeze at every 7-day streak milestone
        if self.current_streak % 7 == 0 and not self.streak_freeze_available:
            self.streak_freeze_available = True
            self.streak_freeze_earned_at = today

        self.last_active_date = today
        self.save(update_fields=[
            'current_streak', 'longest_streak', 'last_active_date',
            'streak_freeze_available', 'streak_freeze_earned_at',
        ])

    def award_xp(self, points: int, reason: str = ''):
        self.xp_points += points
        self.save(update_fields=['xp_points'])
        XPTransaction.objects.create(user=self, points=points, reason=reason)
        self._check_xp_badges()

    def _check_xp_badges(self):
        """Award any XP-threshold badges the user has newly crossed."""
        try:
            thresholds = Badge.objects.filter(trigger='xp', threshold__lte=self.xp_points)
            already_earned = UserBadge.objects.filter(
                user=self, badge__trigger='xp'
            ).values_list('badge_id', flat=True)
            for badge in thresholds:
                if badge.id not in already_earned:
                    UserBadge.objects.create(user=self, badge=badge)
        except Exception:
            pass  # Never block XP award due to badge errors

    def check_streak_badges(self):
        """Call after record_activity() to award streak milestones."""
        try:
            thresholds = Badge.objects.filter(trigger='streak', threshold__lte=self.current_streak)
            already_earned = UserBadge.objects.filter(
                user=self, badge__trigger='streak'
            ).values_list('badge_id', flat=True)
            for badge in thresholds:
                if badge.id not in already_earned:
                    UserBadge.objects.create(user=self, badge=badge)
        except Exception:
            pass


class XPTransaction(models.Model):
    """Immutable ledger of every XP award."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='xp_transactions')
    points = models.IntegerField()
    reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.username} +{self.points} ({self.reason})'


class Badge(models.Model):
    """A badge that can be earned by reaching an XP or streak milestone."""

    TRIGGER_CHOICES = [
        ('xp', 'XP milestone'),
        ('streak', 'Streak milestone'),
        ('sermons', 'Sermons completed'),
    ]

    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=200)
    icon = models.CharField(max_length=10, default='✦')  # emoji or symbol
    trigger = models.CharField(max_length=20, choices=TRIGGER_CHOICES, default='xp')
    threshold = models.PositiveIntegerField()  # e.g. 100 for "earn 100 XP"

    class Meta:
        ordering = ['trigger', 'threshold']

    def __str__(self):
        return f'{self.icon} {self.name} ({self.trigger} >= {self.threshold})'


class UserBadge(models.Model):
    """Awarded once per user per badge — immutable."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='badges')
    badge = models.ForeignKey(Badge, on_delete=models.CASCADE, related_name='holders')
    earned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'badge')
        ordering = ['-earned_at']

    def __str__(self):
        return f'{self.user.username} — {self.badge.name}'
