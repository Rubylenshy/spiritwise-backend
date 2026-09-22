"""
Celery (and django-celery-beat / django-celery-results) was removed, so those
apps no longer run their own migrations. Drop the tables they left behind and
forget their migration history, so re-adding the packages later starts clean.
Irreversible by design — reversing is a no-op.
"""
from django.db import migrations

CELERY_APPS = ('django_celery_beat', 'django_celery_results')


def drop_celery_tables(apps, schema_editor):
    connection = schema_editor.connection
    tables = [t for t in connection.introspection.table_names() if t.startswith(CELERY_APPS)]
    cascade = ' CASCADE' if connection.vendor == 'postgresql' else ''
    with connection.cursor() as cursor:
        for table in tables:
            cursor.execute(f'DROP TABLE IF EXISTS {schema_editor.quote_name(table)}{cascade}')
        cursor.execute(
            'DELETE FROM django_migrations WHERE app IN (%s, %s)', CELERY_APPS,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('engagement', '0002_remove_leaderboardentry'),
    ]

    operations = [
        migrations.RunPython(drop_celery_tables, migrations.RunPython.noop),
    ]
