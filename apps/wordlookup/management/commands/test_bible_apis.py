"""
Usage:
    python manage.py test_bible_apis

Smoke-tests the Bible API connections configured in .env.
Run this after adding BIBLE_API_KEY and ESV_API_KEY to verify
everything is wired up before testing through the UI.

Checks:
  1. api.bible — fetches John 3:16 in ESV, NIV, KJV
  2. api.esv.org — fetches Philippians 4:13 as fallback verification
  3. Redis cache — confirms a cached hit returns on the second call
  4. Thematic resolver — checks a known phrase maps to the right passage
"""
import time
from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.cache import cache


class Command(BaseCommand):
    help = 'Smoke-test Bible API connections for WordLookUp (WL2)'

    def handle(self, *args, **options):
        self.stdout.write('\n── WordLookUp WL2 — API connection test ──\n')

        # ── Key presence check ────────────────────────────────────────────────
        bible_key = getattr(settings, 'BIBLE_API_KEY', '')
        esv_key = getattr(settings, 'ESV_API_KEY', '')

        self.stdout.write('\n① Environment variables')
        if bible_key:
            self.stdout.write(self.style.SUCCESS(f'  BIBLE_API_KEY  ✓  {bible_key[:8]}…'))
        else:
            self.stdout.write(self.style.WARNING(
                '  BIBLE_API_KEY  ✗  not set — api.bible calls will be skipped'
            ))

        if esv_key:
            self.stdout.write(self.style.SUCCESS(f'  ESV_API_KEY    ✓  {esv_key[:8]}…'))
        else:
            self.stdout.write(self.style.WARNING(
                '  ESV_API_KEY    ✗  not set — ESV fallback will be skipped'
            ))

        if not bible_key and not esv_key:
            self.stdout.write(self.style.ERROR(
                '\nNeither key is set. Add at least one to .env and re-run.\n'
                'See .env.wl2.example for instructions.\n'
            ))
            return

        from apps.wordlookup.bible_apis import fetch_verse, fetch_verse_by_query

        # ── Test 1: api.bible primary ─────────────────────────────────────────
        self.stdout.write('\n② api.bible — fetching John 3:16 in ESV / NIV / KJV')

        for version in ['ESV', 'NIV', 'KJV']:
            t0 = time.perf_counter()
            result = fetch_verse('John', 3, 16, version=version)
            elapsed = (time.perf_counter() - t0) * 1000

            if result and result.get('text'):
                preview = result['text'][:60].replace('\n', ' ')
                self.stdout.write(self.style.SUCCESS(
                    f'  {version}  ✓  {elapsed:.0f}ms  source={result["source"]}'
                ))
                self.stdout.write(f'       "{preview}…"')
            elif not bible_key:
                self.stdout.write(f'  {version}  —  skipped (no key)')
            else:
                self.stdout.write(self.style.WARNING(
                    f'  {version}  ✗  no result ({elapsed:.0f}ms)'
                ))

        # ── Test 2: ESV fallback ──────────────────────────────────────────────
        self.stdout.write('\n③ ESV fallback — fetching Philippians 4:13')

        from apps.wordlookup.bible_apis import _fetch_from_esv
        t0 = time.perf_counter()
        esv_result = _fetch_from_esv('Philippians', 4, 13, None)
        elapsed = (time.perf_counter() - t0) * 1000

        if esv_result and esv_result.get('text'):
            preview = esv_result['text'][:70].replace('\n', ' ')
            self.stdout.write(self.style.SUCCESS(
                f'  ESV  ✓  {elapsed:.0f}ms  source={esv_result["source"]}'
            ))
            self.stdout.write(f'       "{preview}…"')
        elif not esv_key:
            self.stdout.write('  ESV  —  skipped (no key)')
        else:
            self.stdout.write(self.style.WARNING(f'  ESV  ✗  no result ({elapsed:.0f}ms)'))

        # ── Test 3: Redis cache ───────────────────────────────────────────────
        self.stdout.write('\n④ Redis cache — second call for John 3:16 (ESV) should be instant')

        t0 = time.perf_counter()
        cached = fetch_verse('John', 3, 16, version='ESV')
        elapsed = (time.perf_counter() - t0) * 1000

        if cached:
            if elapsed < 5:
                self.stdout.write(self.style.SUCCESS(
                    f'  Cache  ✓  {elapsed:.1f}ms  (cache hit confirmed)'
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f'  Cache  ?  {elapsed:.0f}ms  (slower than expected — '
                    f'check Redis connection)'
                ))
        else:
            self.stdout.write('  Cache  —  skipped (no verse result to cache)')

        # ── Test 4: Thematic resolver ─────────────────────────────────────────
        self.stdout.write('\n⑤ Thematic resolver — phrase → Bible reference')

        from apps.wordlookup.views import _resolve_thematic_phrase

        phrases = [
            ('the prodigal son',      'Luke 15'),
            ('sermon on the mount',   'Matthew 5'),
            ('the good samaritan',    'Luke 10'),
            ('armour of god',         'Ephesians 6'),
            ('completely unknown xyz', None),
        ]

        for phrase, expected_prefix in phrases:
            resolved = _resolve_thematic_phrase(phrase)
            if expected_prefix is None:
                if resolved is None:
                    self.stdout.write(self.style.SUCCESS(
                        f'  "{phrase}"  ✓  correctly returned None'
                    ))
                else:
                    self.stdout.write(self.style.WARNING(
                        f'  "{phrase}"  ?  unexpectedly resolved to '
                        f'{resolved["book"]} {resolved["chapter"]}'
                    ))
            elif resolved:
                ref = f'{resolved["book"]} {resolved["chapter"]}'
                if ref.startswith(expected_prefix):
                    self.stdout.write(self.style.SUCCESS(
                        f'  "{phrase}"  ✓  → {ref} '
                        f'(confidence {resolved["confidence"]})'
                    ))
                else:
                    self.stdout.write(self.style.WARNING(
                        f'  "{phrase}"  ?  expected {expected_prefix}, got {ref}'
                    ))
            else:
                self.stdout.write(self.style.WARNING(
                    f'  "{phrase}"  ✗  not resolved (expected {expected_prefix})'
                ))

        # ── Test 5: Full lookup endpoint simulation ───────────────────────────
        self.stdout.write('\n⑥ Full lookup simulation — query string parsing')

        test_queries = [
            'John 3:16',
            'Romans 8:28',
            'Psalm 23:1',
            '1 Corinthians 13:4',
            'Philippians 4:13',
        ]

        for q in test_queries:
            result = fetch_verse_by_query(q, version='ESV')
            if result and result.get('text'):
                preview = result['text'][:50].replace('\n', ' ')
                self.stdout.write(self.style.SUCCESS(
                    f'  "{q}"  ✓  → {result["reference"]}'
                ))
                self.stdout.write(f'       "{preview}…"')
            else:
                self.stdout.write(self.style.WARNING(
                    f'  "{q}"  ✗  no result returned'
                ))

        # ── Summary ───────────────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS('\n── Test complete ──\n'))
        self.stdout.write('Next steps:')
        self.stdout.write('  python manage.py migrate')
        self.stdout.write('  python manage.py runserver')
        self.stdout.write('  → Open /wordlookup and tap a reference\n')
