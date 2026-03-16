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
        """
        today = timezone.now().date()

        if self.last_active_date == today:
            return  # Already recorded today

        if self.last_active_date and (today - self.last_active_date).days == 1:
            self.current_streak += 1
        else:
            # Streak broken (or first activity ever)
            self.current_streak = 1

        if self.current_streak > self.longest_streak:
            self.longest_streak = self.current_streak

        self.last_active_date = today
        self.save(update_fields=['current_streak', 'longest_streak', 'last_active_date'])

    def award_xp(self, points: int, reason: str = ''):
        self.xp_points += points
        self.save(update_fields=['xp_points'])
        XPTransaction.objects.create(user=self, points=points, reason=reason)


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
