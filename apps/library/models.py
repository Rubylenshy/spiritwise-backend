from django.conf import settings
from django.db import models
from django.db.models import Exists, OuterRef

from apps.sermons.models import Sermon


class Favorite(models.Model):
    """A sermon the user has hearted."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='favorites'
    )
    sermon = models.ForeignKey(Sermon, on_delete=models.CASCADE, related_name='favorited_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'sermon')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.username} ♥ {self.sermon.title}'


class Playlist(models.Model):
    """A private, ordered list of sermons owned by one user."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='playlists'
    )
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f'{self.user.username}: {self.name}'


class PlaylistItem(models.Model):
    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE, related_name='items')
    sermon = models.ForeignKey(Sermon, on_delete=models.CASCADE, related_name='playlist_items')
    # Sparse: removals leave gaps, reordering swaps neighbours' values.
    position = models.PositiveIntegerField()
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('playlist', 'sermon')
        ordering = ['position']

    def __str__(self):
        return f'{self.playlist.name} #{self.position}: {self.sermon.title}'


def with_favorited(queryset, user):
    """Annotate a Sermon queryset with is_favorited for this user."""
    return queryset.annotate(
        is_favorited=Exists(Favorite.objects.filter(user=user, sermon=OuterRef('pk')))
    )
