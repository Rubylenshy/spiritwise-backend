from django.db import models
from django.conf import settings
from django.utils.text import slugify


class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(unique=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class Series(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, blank=True)
    description = models.TextField(blank=True)
    cover_image = models.ImageField(upload_to='series/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    class Meta:
        verbose_name_plural = 'series'
        ordering = ['-created_at']


class Sermon(models.Model):
    title = models.CharField(max_length=300)
    slug = models.SlugField(unique=True, blank=True)
    speaker = models.CharField(max_length=200)
    series = models.ForeignKey(
        Series, on_delete=models.SET_NULL, null=True, blank=True, related_name='sermons'
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name='sermons')
    description = models.TextField(blank=True)

    # Audio
    audio_file = models.FileField(upload_to='sermons/audio/', blank=True, null=True)
    audio_url = models.URLField(blank=True)  # external URL fallback
    duration_seconds = models.PositiveIntegerField(default=0)

    # Metadata
    scripture_reference = models.CharField(max_length=200, blank=True)
    sermon_date = models.DateField(null=True, blank=True)
    thumbnail = models.ImageField(upload_to='sermons/thumbnails/', blank=True, null=True)

    # Stats
    play_count = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='uploaded_sermons',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            while Sermon.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base_slug}-{counter}'
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def duration_display(self):
        m, s = divmod(self.duration_seconds, 60)
        return f'{m}:{s:02d}'

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['-sermon_date', '-created_at']


class SermonQuestion(models.Model):
    """Reflection questions shown to users after ~80% of a sermon."""

    sermon = models.ForeignKey(Sermon, on_delete=models.CASCADE, related_name='questions')
    text = models.TextField()
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f'{self.sermon.title}: Q{self.order}'


class ListenHistory(models.Model):
    """Tracks per-user listen progress on each sermon."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='listen_history'
    )
    sermon = models.ForeignKey(Sermon, on_delete=models.CASCADE, related_name='listeners')
    progress_seconds = models.PositiveIntegerField(default=0)
    completed = models.BooleanField(default=False)
    last_listened = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'sermon')
        ordering = ['-last_listened']

    def __str__(self):
        return f'{self.user.username} → {self.sermon.title}'
