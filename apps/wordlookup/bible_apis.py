"""
bible_apis.py — WL2

Fetches Bible verse text from external APIs.
All keys stay server-side — never exposed to the frontend.

Primary:   api.bible  (70+ translations, free tier: 5 000 req/day)
Fallback:  api.esv.org (ESV only, reliable, free)

Results are cached in Redis for 24 hours so identical lookups never
hit the external API twice.

Usage:
    from apps.wordlookup.bible_apis import fetch_verse

    result = fetch_verse('John', 3, 16, version='ESV')
    # {
    #   'reference': 'John 3:16',
    #   'text':      '"For God so loved the world…"',
    #   'version':   'ESV',
    #   'copyright': '…',
    #   'source':    'api.bible',
    # }
"""

import json
import logging

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# ── Version → api.bible Bible ID mapping ─────────────────────────────────────
# Each translation has a fixed ID in the api.bible catalogue.
# https://scripture.api.bible/livedocs#/Bibles/getBibles
APIBIBLE_IDS = {
    'ESV':  '9879dbb7cfe39e4d-01',   # English Standard Version
    'NIV':  '78a9f6124f344018-01',   # New International Version
    'KJV':  'de4e12af7f28f599-02',   # King James Version
    'NKJV': '114d2021543d9247-01',   # New King James Version
    'NLT':  '65eec8e0b60e656b-01',   # New Living Translation
    'NCV':  '3b16b62b0f7b45c1-01',   # New Century Version (good fallback)
}
DEFAULT_VERSION = 'ESV'

# Cache TTL: 24 hours (verses don't change)
CACHE_TTL = 60 * 60 * 24


# ── Internal helpers ──────────────────────────────────────────────────────────

def _cache_key(book: str, chapter: int, verse_start: int,
               verse_end: int | None, version: str) -> str:
    parts = [book.lower().replace(' ', '_'), str(chapter),
             str(verse_start), str(verse_end or ''), version.upper()]
    return 'wordlookup:verse:' + ':'.join(parts)


def _apibible_verse_id(book: str, chapter: int, verse: int) -> str:
    """
    api.bible uses a canonical verse ID format: BOOKCHAPTERVERSE
    where BOOK is a 3-letter uppercase abbreviation.
    E.g. John 3:16 → JHN.3.16
    """
    BOOK_CODES = {
        'Genesis': 'GEN', 'Exodus': 'EXO', 'Leviticus': 'LEV',
        'Numbers': 'NUM', 'Deuteronomy': 'DEU', 'Joshua': 'JOS',
        'Judges': 'JDG', 'Ruth': 'RUT', '1 Samuel': '1SA',
        '2 Samuel': '2SA', '1 Kings': '1KI', '2 Kings': '2KI',
        '1 Chronicles': '1CH', '2 Chronicles': '2CH', 'Ezra': 'EZR',
        'Nehemiah': 'NEH', 'Esther': 'EST', 'Job': 'JOB',
        'Psalms': 'PSA', 'Proverbs': 'PRO', 'Ecclesiastes': 'ECC',
        'Song of Solomon': 'SNG', 'Isaiah': 'ISA', 'Jeremiah': 'JER',
        'Lamentations': 'LAM', 'Ezekiel': 'EZK', 'Daniel': 'DAN',
        'Hosea': 'HOS', 'Joel': 'JOL', 'Amos': 'AMO', 'Obadiah': 'OBA',
        'Jonah': 'JON', 'Micah': 'MIC', 'Nahum': 'NAM', 'Habakkuk': 'HAB',
        'Zephaniah': 'ZEP', 'Haggai': 'HAG', 'Zechariah': 'ZEC',
        'Malachi': 'MAL', 'Matthew': 'MAT', 'Mark': 'MRK', 'Luke': 'LUK',
        'John': 'JHN', 'Acts': 'ACT', 'Romans': 'ROM',
        '1 Corinthians': '1CO', '2 Corinthians': '2CO',
        'Galatians': 'GAL', 'Ephesians': 'EPH', 'Philippians': 'PHP',
        'Colossians': 'COL', '1 Thessalonians': '1TH',
        '2 Thessalonians': '2TH', '1 Timothy': '1TI', '2 Timothy': '2TI',
        'Titus': 'TIT', 'Philemon': 'PHM', 'Hebrews': 'HEB',
        'James': 'JAS', '1 Peter': '1PE', '2 Peter': '2PE',
        '1 John': '1JN', '2 John': '2JN', '3 John': '3JN',
        'Jude': 'JUD', 'Revelation': 'REV',
    }
    code = BOOK_CODES.get(book, book[:3].upper())
    return f'{code}.{chapter}.{verse}'


def _clean_verse_text(text: str) -> str:
    """
    Strip HTML-like markup that api.bible embeds in passages.
    e.g. <verse number="16">For God…</verse>
    """
    import re
    # Remove XML/HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Collapse whitespace
    text = ' '.join(text.split())
    return text.strip()


# ── Primary: api.bible ────────────────────────────────────────────────────────

def _fetch_from_apibible(book: str, chapter: int, verse_start: int,
                          verse_end: int | None, version: str) -> dict | None:
    """
    Fetch a verse or range from api.bible.
    Returns a result dict or None on any error.
    """
    api_key = getattr(settings, 'BIBLE_API_KEY', '')
    if not api_key:
        logger.warning('BIBLE_API_KEY not set — skipping api.bible')
        return None

    bible_id = APIBIBLE_IDS.get(version.upper(), APIBIBLE_IDS[DEFAULT_VERSION])

    # Build the passage ID — ranges use a dash: JHN.3.16-JHN.3.17
    start_id = _apibible_verse_id(book, chapter, verse_start)
    if verse_end and verse_end != verse_start:
        end_id = _apibible_verse_id(book, chapter, verse_end)
        passage_id = f'{start_id}-{end_id}'
        endpoint = f'https://api.scripture.api.bible/v1/bibles/{bible_id}/passages/{passage_id}'
    else:
        endpoint = f'https://api.scripture.api.bible/v1/bibles/{bible_id}/verses/{start_id}'

    try:
        resp = requests.get(
            endpoint,
            headers={'api-key': api_key},
            params={'content-type': 'text', 'include-verse-numbers': False,
                    'include-chapter-numbers': False},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json().get('data', {})

        raw_content = data.get('content', '')
        text = _clean_verse_text(raw_content)
        reference = data.get('reference', f'{book} {chapter}:{verse_start}')
        copyright_info = data.get('copyright', '')

        if not text:
            return None

        return {
            'reference': reference,
            'text': text,
            'version': version.upper(),
            'copyright': copyright_info,
            'source': 'api.bible',
        }

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response else 0
        logger.warning('api.bible HTTP %s for %s %s:%s (%s)',
                       status, book, chapter, verse_start, version)
        return None
    except Exception as e:
        logger.warning('api.bible error: %s', e)
        return None


# ── Fallback: ESV API ─────────────────────────────────────────────────────────

def _fetch_from_esv(book: str, chapter: int, verse_start: int,
                    verse_end: int | None) -> dict | None:
    """
    Fetch from api.esv.org — ESV only, but reliable.
    Returns a result dict or None on any error.
    """
    api_key = getattr(settings, 'ESV_API_KEY', '')
    if not api_key:
        logger.warning('ESV_API_KEY not set — skipping ESV fallback')
        return None

    if verse_end and verse_end != verse_start:
        passage = f'{book} {chapter}:{verse_start}-{verse_end}'
    else:
        passage = f'{book} {chapter}:{verse_start}'

    try:
        resp = requests.get(
            'https://api.esv.org/v3/passage/text/',
            headers={'Authorization': f'Token {api_key}'},
            params={
                'q': passage,
                'include-headings': False,
                'include-footnotes': False,
                'include-verse-numbers': False,
                'include-short-copyright': False,
                'include-passage-references': False,
            },
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()

        passages = data.get('passages', [])
        if not passages:
            return None

        text = passages[0].strip()
        if not text:
            return None

        canonical = data.get('canonical', passage)

        return {
            'reference': canonical,
            'text': text,
            'version': 'ESV',
            'copyright': 'Scripture quotations are from the ESV® Bible, copyright © 2001 by Crossway.',
            'source': 'api.esv.org',
        }

    except Exception as e:
        logger.warning('ESV API error for %s: %s', passage, e)
        return None


# ── Public interface ──────────────────────────────────────────────────────────

def fetch_verse(book: str, chapter: int, verse_start: int,
                verse_end: int | None = None,
                version: str = DEFAULT_VERSION) -> dict | None:
    """
    Fetch a Bible verse or range, with Redis caching and ESV fallback.

    Returns:
        {
            'reference': str,   e.g. 'John 3:16'
            'text':      str,   the verse text
            'version':   str,   e.g. 'ESV'
            'copyright': str,
            'source':    str,   'api.bible' | 'api.esv.org'
        }
        or None if all sources fail.
    """
    version = version.upper()
    cache_key = _cache_key(book, chapter, verse_start, verse_end, version)

    # ── Cache hit ──────────────────────────────────────────────────────────────
    cached = cache.get(cache_key)
    if cached:
        return json.loads(cached)

    # ── Try primary (api.bible) ────────────────────────────────────────────────
    result = _fetch_from_apibible(book, chapter, verse_start, verse_end, version)

    # ── Fallback to ESV if primary failed or returned empty ───────────────────
    if not result:
        result = _fetch_from_esv(book, chapter, verse_start, verse_end)

    # ── Cache and return ───────────────────────────────────────────────────────
    if result:
        cache.set(cache_key, json.dumps(result), CACHE_TTL)

    return result


def fetch_verse_by_query(query: str, version: str = DEFAULT_VERSION) -> dict | None:
    """
    Convenience wrapper: parse a query string like 'John 3:16' or
    'Philippians 4:13' and call fetch_verse.

    Returns the same dict as fetch_verse, or None.
    """
    import re

    # Normalise ordinal books: "1 Corinthians" → "1 Corinthians"
    query = query.strip()

    # Pattern: BookName Chapter:Verse[-VerseEnd]
    m = re.match(
        r'^((?:\d\s+)?[A-Za-z ]+?)\s+(\d+)(?:[:.]\s*(\d+)(?:\s*[-–]\s*(\d+))?)?$',
        query
    )
    if not m:
        return None

    book = m.group(1).strip()
    chapter = int(m.group(2))
    verse_start = int(m.group(3)) if m.group(3) else 1
    verse_end = int(m.group(4)) if m.group(4) else None

    return fetch_verse(book, chapter, verse_start, verse_end, version)
