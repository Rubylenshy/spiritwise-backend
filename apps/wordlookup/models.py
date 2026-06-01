from django.db import models
from django.conf import settings


class LookupHistory(models.Model):
    """
    Records every Bible reference lookup a user performs.
    Used for the "Recent lookups" panel on the WordLookUp page (WL3).
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wordlookup_history',
    )
    # The raw query the user triggered (e.g. "John 3:16" or "prodigal son")
    query = models.CharField(max_length=300)
    # The canonical reference that was resolved (e.g. "John 3:16")
    reference_found = models.CharField(max_length=200, blank=True)
    # A snippet of the verse text for display in history list
    verse_snippet = models.TextField(blank=True)
    # Which Bible version was fetched
    version = models.CharField(max_length=20, default='ESV')
    # 'exact' | 'inferred'
    match_type = models.CharField(max_length=20, default='exact')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'lookup histories'

    def __str__(self):
        return f'{self.user.username} → {self.query} ({self.reference_found})'


class SavedVerse(models.Model):
    """
    A verse the user has bookmarked from a lookup result.
    Built out in WL4 — model lives here so migrations are clean.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='saved_verses',
    )
    reference = models.CharField(max_length=200)
    verse_text = models.TextField()
    version = models.CharField(max_length=20, default='ESV')
    # Optional personal note the user adds when saving
    note_text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('user', 'reference', 'version')

    def __str__(self):
        return f'{self.user.username} — {self.reference} ({self.version})'
