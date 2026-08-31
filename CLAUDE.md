# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SpiritWise — Django 5 + Django REST Framework backend for a sermon-listening / Bible-study app. JWT auth (SimpleJWT), PostgreSQL, Celery + Redis for background work, Cloudflare R2 for audio storage.

The frontend (React + Vite + Tailwind, calling this API from `http://localhost:5173` in dev per `CORS_ALLOWED_ORIGINS`) lives in a sibling repo at [`../spiritwise`](../spiritwise) — see [`../spiritwise/CLAUDE.md`](../spiritwise/CLAUDE.md) for its conventions.

## Commands

```bash
# Setup
python -m venv venv && venv\Scripts\activate   # Windows
pip install -r requirements.txt
cp .env.example .env                            # then set SECRET_KEY, DATABASE_URL

# Dev server
python manage.py migrate
python manage.py runserver                      # http://localhost:8000/api/

# Celery (needed for Drive imports + leaderboard refresh + streak reset)
celery -A spiritwise worker -l info
celery -A spiritwise beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler

# Seed sample data
python manage.py seed_data

# WordLookUp diagnostics (management commands, not pytest)
python manage.py test_ai_resolver     # smoke-tests the Claude phrase resolver
python manage.py test_bible_apis      # smoke-tests scripture.api.bible / api.esv.org
```

There is no pytest/unittest suite wired up — `apps/wordlookup/test_ai_resolver.py` and the `test_ai_resolver`/`test_bible_apis` management commands are manual smoke-test scripts run via `manage.py`, not `manage.py test`.

## Architecture

Four-app split under `apps/`, each owning its own `models.py` / `serializers.py` / `views.py` / `urls.py`, mounted in [spiritwise/urls.py](spiritwise/urls.py) under `/api/<app>/`:

- **users** — custom `User` model (`AUTH_USER_MODEL = 'users.User'`), JWT register/login/logout/refresh, `XPTransaction`.
- **sermons** — `Sermon`, `Series`, `Tag`, `SermonQuestion`, `ListenHistory`. Audio is served through a signed-URL indirection, not directly: `SermonDetailSerializer.get_audio_signed_url()` ([apps/sermons/serializers.py](apps/sermons/serializers.py)) calls `apps/sermons/stream_token.py` to mint a short-lived token, and the client fetches `/api/sermons/<id>/stream/?token=...` rather than the R2 URL directly. Falls back to the raw `audio_url`/`audio_file.url` if token generation fails.
- **engagement** — streaks, XP, reflection answers, leaderboard. `tasks.py` has the Celery jobs (leaderboard refresh, streak reset) that require `celery beat` running to fire on schedule.
- **imports** — admin-only pipeline: `CloudImportJob` model, Celery task chain that pulls from Google Drive, uploads to R2, and creates a `Sermon`.
- **wordlookup** ("WordLookUp" feature, in-progress — see WL1–WL4 markers below) — Bible reference/phrase lookup, history, saved verses, Whisper transcription fallback.

### WordLookUp lookup pipeline (apps/wordlookup/views.py)

`POST /api/wordlookup/lookup/` branches on whether the request carries an exact `reference` or a `phrase`:
1. **Exact reference** → straight to the Bible API (`fetch_verse_by_query` in [bible_apis.py](apps/wordlookup/bible_apis.py)), `confidence=1.0`, `match_type='exact'`.
2. **Thematic phrase** → first checked against the hardcoded `_THEMATIC_MAP` in views.py (free, zero-latency pattern matching for well-known passages like "prodigal son", "sermon on the mount").
3. If the local map misses, falls through to `_ai_resolve_and_fetch`, which dynamically imports `apps/wordlookup/ai_resolver.py` (Claude-based) — **this module does not exist yet**; the import is wrapped in try/except so the endpoint degrades to an empty result set rather than erroring. The design intent (per the docstring) is that Claude only ever returns *references*, never verse text, so actual scripture always comes from the Bible API — this prevents hallucinated scripture and should be preserved if/when `ai_resolver.py` is implemented.

Feature progress is tracked inline via `WL1`/`WL2`/`WL3`/`WL4` comment tags in code and commit messages — check the tag on a block before assuming a feature is fully wired (e.g. `saved_verses`/`delete_saved_verse` views exist as WL4 stubs already routed in [urls.py](apps/wordlookup/urls.py) even though WL3 is the current milestone).

### Config

All settings are environment-driven via `python-decouple` in [spiritwise/settings.py](spiritwise/settings.py) — there are no separate dev/prod settings modules. Notable env-gated behavior:
- `USE_S3=True` switches `STORAGES['default']` to `S3Boto3Storage` (R2-backed); R2 credentials are loaded unconditionally regardless of this flag since the sermon stream view also uses boto3 directly.
- Redis cache backend auto-switches to `RedisCache` only when `REDIS_URL` points somewhere other than localhost (i.e. in production/Upstash); local dev uses `LocMemCache`.
- `BIBLE_API_KEY` / `ESV_API_KEY` (scripture APIs) and `OPENAI_API_KEY` (Whisper fallback) are optional — endpoints degrade gracefully when unset.
