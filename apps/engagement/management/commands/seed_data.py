"""
Usage:
    python manage.py seed_data

Seeds the database with sample series, sermons, tags, and questions
so the frontend has something to render during development.
"""
from django.core.management.base import BaseCommand
from apps.sermons.models import Series, Sermon, Tag, SermonQuestion


TAGS = ['Faith', 'Worship', 'Strength', 'Grace', 'Prayer', 'Hope', 'Wisdom']

SERIES_DATA = [
    {'title': 'Foundations', 'description': 'Building your life on the Word of God.'},
    {'title': 'Overflow', 'description': 'Living a life of abundance and gratitude.'},
    {'title': 'Grace Series', 'description': 'Understanding God\'s unmerited favour.'},
]

SERMONS_DATA = [
    {
        'title': 'Walking in Purpose',
        'speaker': 'Pastor James Adeyemi',
        'series': 'Foundations',
        'tags': ['Faith', 'Wisdom'],
        'duration_seconds': 2482,
        'scripture_reference': 'Jeremiah 29:11',
        'description': 'In this message we explore what it truly means to live a life of purpose — not defined by circumstance, but anchored in God\'s calling.',
        'questions': [
            'What is one area of your life where you feel God is calling you to walk in greater purpose?',
            'How does gratitude shape the way we pursue our calling?',
            'What practical step can you take this week to align your actions with your God-given purpose?',
        ],
    },
    {
        'title': 'The Power of Gratitude',
        'speaker': 'Rev. Chinwe Obi',
        'series': 'Overflow',
        'tags': ['Worship', 'Hope'],
        'duration_seconds': 2290,
        'scripture_reference': '1 Thessalonians 5:18',
        'description': 'Gratitude is not merely a feeling — it is a spiritual discipline that transforms perspective and opens doors.',
        'questions': [
            'How has gratitude changed a difficult season in your life?',
            'Name three things today that you can thank God for that you usually take for granted.',
        ],
    },
    {
        'title': 'Renewed Strength',
        'speaker': 'Pastor James Adeyemi',
        'series': 'Foundations',
        'tags': ['Strength', 'Faith'],
        'duration_seconds': 3124,
        'scripture_reference': 'Isaiah 40:31',
        'description': 'When we feel weary, God promises to renew our strength. This message unpacks what it means to wait on the Lord.',
        'questions': [
            'In what area of life are you most in need of renewed strength right now?',
            'What does "waiting on the Lord" look like practically for you?',
            'How can you encourage someone in your community who is feeling weary?',
        ],
    },
    {
        'title': 'Bold Faith',
        'speaker': 'Rev. Chinwe Obi',
        'series': 'Overflow',
        'tags': ['Faith'],
        'duration_seconds': 2695,
        'scripture_reference': 'Hebrews 11:1',
        'description': 'Faith is the substance of things hoped for. This sermon calls us to step boldly into the promises of God.',
        'questions': [
            'Where is God asking you to step out in bold faith right now?',
            'What fears are holding you back from fully trusting God?',
        ],
    },
    {
        'title': 'Grace in the Valley',
        'speaker': 'Deacon Samuel Tunde',
        'series': 'Grace Series',
        'tags': ['Grace', 'Hope'],
        'duration_seconds': 2172,
        'scripture_reference': 'Psalm 23:4',
        'description': 'Even in our darkest valleys, God\'s grace sustains us. A message of deep comfort and hope.',
        'questions': [
            'Describe a "valley" season in your life. How did you experience God\'s grace in it?',
            'How can the promise of Psalm 23 reshape how you face current challenges?',
        ],
    },
    {
        'title': 'The Armour of God',
        'speaker': 'Pastor James Adeyemi',
        'series': 'Foundations',
        'tags': ['Strength', 'Prayer'],
        'duration_seconds': 2970,
        'scripture_reference': 'Ephesians 6:10-18',
        'description': 'We are in a spiritual battle. This sermon gives a practical breakdown of each piece of the armour of God.',
        'questions': [
            'Which piece of the armour do you feel you most need to put on right now?',
            'How does daily prayer function as your weapon in spiritual warfare?',
        ],
    },
]


class Command(BaseCommand):
    help = 'Seed the database with sample sermons, series, and tags'

    def handle(self, *args, **options):
        self.stdout.write('Seeding tags...')
        tags = {}
        for name in TAGS:
            tag, _ = Tag.objects.get_or_create(name=name)
            tags[name] = tag

        self.stdout.write('Seeding series...')
        series_map = {}
        for s in SERIES_DATA:
            obj, _ = Series.objects.get_or_create(title=s['title'], defaults={'description': s['description']})
            series_map[s['title']] = obj

        self.stdout.write('Seeding sermons...')
        for data in SERMONS_DATA:
            sermon, created = Sermon.objects.get_or_create(
                title=data['title'],
                defaults={
                    'speaker': data['speaker'],
                    'series': series_map.get(data['series']),
                    'duration_seconds': data['duration_seconds'],
                    'scripture_reference': data['scripture_reference'],
                    'description': data['description'],
                    'is_published': True,
                },
            )
            for tag_name in data['tags']:
                sermon.tags.add(tags[tag_name])

            if created:
                for i, q_text in enumerate(data['questions'], start=1):
                    SermonQuestion.objects.create(sermon=sermon, text=q_text, order=i)

            status = 'created' if created else 'already exists'
            self.stdout.write(f'  {sermon.title} — {status}')

        self.stdout.write(self.style.SUCCESS(
            f'\nDone! {len(SERMONS_DATA)} sermons, {len(SERIES_DATA)} series, {len(TAGS)} tags.'
        ))
