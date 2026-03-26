"""
Usage:
    python manage.py setup_periodic_tasks

Registers all Celery beat periodic tasks in the database using
django-celery-beat. Run this once after the first migration, and
again any time you add or change a task schedule.
"""
from django.core.management.base import BaseCommand
from django_celery_beat.models import PeriodicTask, CrontabSchedule
import json


TASKS = [
    {
        'name': 'Refresh weekly leaderboard (Sunday 23:00 UTC)',
        'task': 'engagement.refresh_weekly_leaderboard',
        'crontab': {'minute': '0', 'hour': '23', 'day_of_week': '0'},
    },
    {
        'name': 'Refresh all-time leaderboard (daily 00:30 UTC)',
        'task': 'engagement.refresh_all_time_leaderboard',
        'crontab': {'minute': '30', 'hour': '0'},
    },
    {
        'name': 'Check broken streaks (daily 00:05 UTC)',
        'task': 'engagement.check_broken_streaks',
        'crontab': {'minute': '5', 'hour': '0'},
    },
    {
        'name': 'Send streak reminder emails (daily 18:00 UTC)',
        'task': 'engagement.send_streak_reminders',
        'crontab': {'minute': '0', 'hour': '18'},
    },
]


class Command(BaseCommand):
    help = 'Register all Celery beat periodic tasks in the database'

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        for t in TASKS:
            cron_defaults = {
                'minute': t['crontab'].get('minute', '*'),
                'hour': t['crontab'].get('hour', '*'),
                'day_of_week': t['crontab'].get('day_of_week', '*'),
                'day_of_month': t['crontab'].get('day_of_month', '*'),
                'month_of_year': t['crontab'].get('month_of_year', '*'),
            }

            schedule, _ = CrontabSchedule.objects.get_or_create(**cron_defaults)

            task, created = PeriodicTask.objects.update_or_create(
                name=t['name'],
                defaults={
                    'task': t['task'],
                    'crontab': schedule,
                    'args': json.dumps([]),
                    'enabled': True,
                },
            )

            if created:
                created_count += 1
                self.stdout.write(f'  Created: {t["name"]}')
            else:
                updated_count += 1
                self.stdout.write(f'  Updated: {t["name"]}')

        self.stdout.write(self.style.SUCCESS(
            f'\nDone. {created_count} created, {updated_count} updated.'
        ))
        self.stdout.write(
            'Start the beat scheduler:\n'
            '  celery -A spiritwise beat -l info '
            '--scheduler django_celery_beat.schedulers:DatabaseScheduler'
        )
