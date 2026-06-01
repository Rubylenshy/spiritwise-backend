from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LookupHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('query', models.CharField(max_length=300)),
                ('reference_found', models.CharField(blank=True, max_length=200)),
                ('verse_snippet', models.TextField(blank=True)),
                ('version', models.CharField(default='ESV', max_length=20)),
                ('match_type', models.CharField(default='exact', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='wordlookup_history',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-created_at'],
                'verbose_name_plural': 'lookup histories',
            },
        ),
        migrations.CreateModel(
            name='SavedVerse',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('reference', models.CharField(max_length=200)),
                ('verse_text', models.TextField()),
                ('version', models.CharField(default='ESV', max_length=20)),
                ('note_text', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='saved_verses',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-created_at'],
                'unique_together': {('user', 'reference', 'version')},
            },
        ),
    ]
