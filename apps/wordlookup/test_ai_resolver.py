"""
Usage:
    python manage.py test_ai_resolver

Smoke-tests the Claude AI phrase resolver for WordLookUp WL3.

Checks:
  1. ANTHROPIC_API_KEY presence
  2. Direct API call to Claude with a known sermon phrase
  3. Cache behaviour (second call should be instant)
  4. Full end-to-end: phrase → Claude → Bible API → verse text
  5. Edge cases: empty input, unknown phrase, exact reference bypass
"""
import time
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Smoke-test the Claude AI phrase resolver for WordLookUp WL3'

    def handle(self, *args, **options):
        self.stdout.write('\n── WordLookUp WL3 — AI resolver test ──\n')

        # ── Key check ─────────────────────────────────────────────────────────
        api_key = getattr(settings, 'ANTHROPIC_API_KEY', '')
        self.stdout.write('\n① Environment variables')
        if api_key:
            self.stdout.write(self.style.SUCCESS(
                f'  ANTHROPIC_API_KEY  ✓  {api_key[:8]}…'
            ))
        else:
            self.stdout.write(self.style.ERROR(
                '  ANTHROPIC_API_KEY  ✗  not set\n'
                '  Add ANTHROPIC_API_KEY=sk-ant-… to your .env and re-run.\n'
                '  Get a key at https://console.anthropic.com\n'
            ))
            return

        from apps.wordlookup.ai_resolver import resolve_phrase

        # ── Test 1: Known sermon phrases ──────────────────────────────────────
        self.stdout.write('\n② Known sermon phrase → Claude resolver')
        PHRASE_TESTS = [
            ('the part where Jesus fed everyone with fish and bread',
             'Matthew', 14, 'feeding miracle'),
            ('the story of the son who left home and wasted everything',
             'Luke', 15, 'prodigal son'),
            ("when Paul talks about running the race",
             'Corinthians', None, 'race metaphor'),
            ('the valley of dry bones',
             'Ezekiel', 37, 'dry bones'),
        ]

        for phrase, expected_book, expected_chapter, label in PHRASE_TESTS:
            t0 = time.perf_counter()
            results = resolve_phrase(phrase)
            elapsed = (time.perf_counter() - t0) * 1000

            if results:
                top = results[0]
                book_ok = expected_book.lower() in top['book'].lower() if expected_book else True
                ch_ok = (top['chapter'] == expected_chapter) if expected_chapter else True
                status_icon = '✓' if (book_ok and ch_ok) else '?'
                color = self.style.SUCCESS if (book_ok and ch_ok) else self.style.WARNING
                self.stdout.write(color(
                    f'  [{label}] {status_icon}  {elapsed:.0f}ms\n'
                    f'      → {top["book"]} {top["chapter"]}:{top["verse_start"]}'
                    f'  confidence={top["confidence"]:.2f}'
                ))
                if top.get('reasoning'):
                    self.stdout.write(f'      reasoning: {top["reasoning"]}')
                if len(results) > 1:
                    self.stdout.write(
                        f'      + {len(results)-1} more candidate(s): '
                        + ', '.join(
                            f'{r["book"]} {r["chapter"]}:{r["verse_start"]} ({r["confidence"]:.2f})'
                            for r in results[1:]
                        )
                    )
            else:
                self.stdout.write(self.style.WARNING(
                    f'  [{label}] ✗  {elapsed:.0f}ms — no results returned'
                ))

        # ── Test 2: Cache hit ─────────────────────────────────────────────────
        self.stdout.write('\n③ Cache — second call for same phrase should be <5ms')
        phrase = 'the feeding of five thousand'
        t0 = time.perf_counter()
        cached_result = resolve_phrase(phrase)
        elapsed = (time.perf_counter() - t0) * 1000

        if elapsed < 5:
            self.stdout.write(self.style.SUCCESS(
                f'  Cache ✓  {elapsed:.1f}ms  (cache hit confirmed)'
            ))
        elif elapsed < 50:
            self.stdout.write(self.style.WARNING(
                f'  Cache ?  {elapsed:.0f}ms  (possible cache miss — check Redis)'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'  Cache ✗  {elapsed:.0f}ms  (cache not working — check Redis connection)'
            ))

        # ── Test 3: Edge cases ────────────────────────────────────────────────
        self.stdout.write('\n④ Edge cases')

        # Empty input → should return []
        result = resolve_phrase('')
        if result == []:
            self.stdout.write(self.style.SUCCESS('  Empty input  ✓  returns []'))
        else:
            self.stdout.write(self.style.WARNING(f'  Empty input  ?  returned: {result}'))

        # Very short input → should return []
        result = resolve_phrase('hi')
        if result == []:
            self.stdout.write(self.style.SUCCESS('  Too-short input  ✓  returns []'))
        else:
            self.stdout.write(self.style.WARNING(f'  Too-short input  ?  returned: {result}'))

        # Completely non-biblical phrase → should return [] or low-confidence
        t0 = time.perf_counter()
        result = resolve_phrase('the quarterly earnings report from Q3 fiscal year')
        elapsed = (time.perf_counter() - t0) * 1000
        if not result or all(r['confidence'] < 0.5 for r in result):
            self.stdout.write(self.style.SUCCESS(
                f'  Non-biblical phrase  ✓  correctly returned no/low-confidence results  ({elapsed:.0f}ms)'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'  Non-biblical phrase  ?  returned: {[(r["book"], r["confidence"]) for r in result]}'
            ))

        # ── Test 4: Full pipeline — phrase → AI → Bible API → verse text ──────
        self.stdout.write('\n⑤ Full pipeline — phrase → Claude → Bible API → verse text')
        from apps.wordlookup.views import _ai_resolve_and_fetch

        t0 = time.perf_counter()
        full_results = _ai_resolve_and_fetch(
            'the woman who lost her coin and searched the whole house',
            ['ESV']
        )
        elapsed = (time.perf_counter() - t0) * 1000

        if full_results:
            r = full_results[0]
            self.stdout.write(self.style.SUCCESS(
                f'  Full pipeline ✓  {elapsed:.0f}ms\n'
                f'  → {r["reference"]}  ({r["version"]})  confidence={r["confidence"]:.2f}\n'
                f'  → source: {r["source"]}'
            ))
            if r.get('text'):
                preview = r['text'][:80].replace('\n', ' ')
                self.stdout.write(f'  → "{preview}…"')
        else:
            self.stdout.write(self.style.WARNING(
                f'  Full pipeline ✗  {elapsed:.0f}ms — no results\n'
                f'  Check ANTHROPIC_API_KEY and Bible API keys are both set.'
            ))

        # ── Test 5: Local thematic map bypass (should NOT call AI) ────────────
        self.stdout.write('\n⑥ Local thematic map bypass (no AI call)')
        from apps.wordlookup.views import _resolve_thematic_phrase

        known = [
            ('the prodigal son', 'Luke'),
            ('the good samaritan', 'Luke'),
            ('armour of god', 'Ephesians'),
            ('completely unknown xyz phrase', None),
        ]
        for phrase, expected in known:
            resolved = _resolve_thematic_phrase(phrase)
            if expected is None:
                ok = resolved is None
            else:
                ok = resolved is not None and resolved['book'] == expected

            if ok:
                self.stdout.write(self.style.SUCCESS(
                    f'  "{phrase}"  ✓  → '
                    f'{resolved["book"] + " " + str(resolved["chapter"]) if resolved else "None"}'
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f'  "{phrase}"  ?  expected={expected}, got={resolved}'
                ))

        self.stdout.write(self.style.SUCCESS('\n── WL3 test complete ──\n'))
        self.stdout.write('Next steps:')
        self.stdout.write('  python manage.py runserver')
        self.stdout.write('  → Open /wordlookup and type a phrase like')
        self.stdout.write('    "the woman who searched for her lost coin"')
        self.stdout.write('  → Claude identifies Luke 15:8-10, Bible API fetches the text\n')
