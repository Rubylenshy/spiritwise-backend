"""
Usage:
    python manage.py seed_badges

Creates the standard XP and streak milestone badges.
Safe to run multiple times (uses get_or_create).
"""
from django.core.management.base import BaseCommand
from apps.users.models import Badge


BADGES = [
    # XP milestones
    {'name': 'First steps',       'description': 'Earn your first 100 XP',            'icon': '🌱', 'trigger': 'xp',     'threshold': 100},
    {'name': 'Rising spirit',     'description': 'Earn 500 XP',                        'icon': '🔆', 'trigger': 'xp',     'threshold': 500},
    {'name': 'Faithful seeker',   'description': 'Earn 1,000 XP',                      'icon': '📖', 'trigger': 'xp',     'threshold': 1000},
    {'name': 'Word keeper',       'description': 'Earn 2,500 XP',                      'icon': '🕊️', 'trigger': 'xp',     'threshold': 2500},
    {'name': 'Pillar of faith',   'description': 'Earn 5,000 XP',                      'icon': '🏛️', 'trigger': 'xp',     'threshold': 5000},
    {'name': 'Champion',          'description': 'Earn 10,000 XP',                     'icon': '👑', 'trigger': 'xp',     'threshold': 10000},

    # Streak milestones
    {'name': 'First week',        'description': 'Maintain a 7-day streak',            'icon': '🔥', 'trigger': 'streak', 'threshold': 7},
    {'name': 'Fortnight',         'description': 'Maintain a 14-day streak',           'icon': '⚡', 'trigger': 'streak', 'threshold': 14},
    {'name': 'Month of faith',    'description': 'Maintain a 30-day streak',           'icon': '🌕', 'trigger': 'streak', 'threshold': 30},
    {'name': 'Unstoppable',       'description': 'Maintain a 60-day streak',           'icon': '💎', 'trigger': 'streak', 'threshold': 60},
    {'name': 'Year of the Word',  'description': 'Maintain a 365-day streak',          'icon': '✨', 'trigger': 'streak', 'threshold': 365},

    # Sermons completed
    {'name': 'First listen',      'description': 'Complete your first sermon',         'icon': '🎧', 'trigger': 'sermons', 'threshold': 1},
    {'name': 'Dedicated',         'description': 'Complete 10 sermons',                'icon': '📻', 'trigger': 'sermons', 'threshold': 10},
    {'name': 'Devoted',           'description': 'Complete 25 sermons',                'icon': '🎙️', 'trigger': 'sermons', 'threshold': 25},
    {'name': 'Scholar',           'description': 'Complete 50 sermons',                'icon': '🎓', 'trigger': 'sermons', 'threshold': 50},
]


class Command(BaseCommand):
    help = 'Seed the database with XP and streak milestone badges'

    def handle(self, *args, **options):
        created = 0
        for b in BADGES:
            _, was_created = Badge.objects.get_or_create(
                name=b['name'],
                defaults={
                    'description': b['description'],
                    'icon': b['icon'],
                    'trigger': b['trigger'],
                    'threshold': b['threshold'],
                },
            )
            status = 'created' if was_created else 'exists'
            self.stdout.write(f'  {b["icon"]} {b["name"]} — {status}')
            if was_created:
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f'\nDone. {created} new badges created, {len(BADGES) - created} already existed.'
        ))
