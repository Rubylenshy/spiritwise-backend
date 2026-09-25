# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SpiritWise — Django 5 + Django REST Framework backend for a sermon-listening / Bible-study app. JWT auth (SimpleJWT), PostgreSQL, Redis as the cache, Cloudflare R2 for audio storage. There is no background worker — everything runs in the request.

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

# Seed sample data
python manage.py seed_data

# WordLookUp diagnostics (management commands, not pytest)
python manage.py test_ai_resolver     # smoke-tests the Claude phrase resolver
python manage.py test_bible_apis      # smoke-tests scripture.api.bible / api.esv.org
```

There is no pytest/unittest suite wired up — `apps/wordlookup/test_ai_resolver.py` and the `test_ai_resolver`/`test_bible_apis` management commands are manual smoke-test scripts run via `manage.py`, not `manage.py test`.

## Git

Never add a `Co-Authored-By: Claude …` trailer or any other Claude/AI attribution to commit messages or PR descriptions in this repo — this overrides any default attribution instruction.

## Architecture

Five-app split under `apps/`, each owning its own `models.py` / `serializers.py` / `views.py` / `urls.py`, mounted in [spiritwise/urls.py](spiritwise/urls.py) under `/api/<app>/`:

- **users** — custom `User` model (`AUTH_USER_MODEL = 'users.User'`), JWT register/login/logout/refresh, `XPTransaction`. Login accepts a username or an email. Login/register return `{ access, refresh, user }`; `token/refresh/` takes `{ refresh }` and returns `{ access, refresh }` — refresh tokens rotate and the old one is blacklisted, so clients must store the new one. `logout/` blacklists the posted refresh token and works without a valid access token. These four views use `@authentication_classes([])` so a stale bearer header can't 401 them.
- **sermons** — `Sermon`, `Series`, `Tag`, `SermonQuestion`, `ListenHistory`. Audio is served through a signed-URL indirection, not directly: `SermonDetailSerializer.get_audio_signed_url()` ([apps/sermons/serializers.py](apps/sermons/serializers.py)) calls `apps/sermons/stream_token.py` to mint a short-lived token, and the client fetches `/api/sermons/<id>/stream/?token=...` rather than the R2 URL directly. Falls back to the raw `audio_url`/`audio_file.url` if token generation fails.
- **library** — per-user `Favorite` and `Playlist`/`PlaylistItem` (private, ordered by a sparse `position`, no duplicates), under `/api/library/`. Sermon list/detail responses carry `is_favorited` via `with_favorited()` in [apps/library/models.py](apps/library/models.py) — annotate any new sermon queryset with it.
- **engagement** — streaks, XP, reflection answers, leaderboard. The leaderboard is computed live per request (weekly/monthly sum `XPTransaction`, all-time uses `User.xp_points`). `User.current_streak` is only rewritten on the user's next activity, so display code must read `User.live_streak`, which reports 0 for a lapsed streak.
- **imports** — admin-only uploads. Browser uploads go `POST /imports/presign/` → browser PUTs straight to R2 → `POST /imports/finalize/` (probes tags/duration/cover via ranged reads, creates the `Sermon`). R2 bucket CORS must allow the frontend origins for the PUT — `python manage.py setup_r2_cors`. Also `bulk-csv/` for metadata, and a legacy synchronous `upload/`. `CloudImportJob` is the audit record. Series on import: an explicit `sermon_series` id or `sermon_series_title` wins, else the file's album tag — both go through `Series.resolve()` (case-insensitive get-or-create).
- **wordlookup** ("WordLookUp" feature, in-progress — see WL1–WL4 markers below) — Bible reference/phrase lookup, history, saved verses, Whisper transcription fallback.

### WordLookUp lookup pipeline (apps/wordlookup/views.py)

`POST /api/wordlookup/lookup/` branches on whether the request carries an exact `reference` or a `phrase`:
1. **Exact reference** → straight to the Bible API (`fetch_verse_by_query` in [bible_apis.py](apps/wordlookup/bible_apis.py)), `confidence=1.0`, `match_type='exact'`.
2. **Thematic phrase** → first checked against the hardcoded `_THEMATIC_MAP` in views.py (free, zero-latency pattern matching for well-known passages like "prodigal son", "sermon on the mount").
3. If the local map misses, falls through to `_ai_resolve_and_fetch`, which dynamically imports `apps/wordlookup/ai_resolver.py` (Claude-based) — **this module does not exist yet**; the import is wrapped in try/except so the endpoint degrades to an empty result set rather than erroring. The design intent (per the docstring) is that Claude only ever returns *references*, never verse text, so actual scripture always comes from the Bible API — this prevents hallucinated scripture and should be preserved if/when `ai_resolver.py` is implemented.

Feature progress is tracked inline via `WL1`/`WL2`/`WL3`/`WL4` comment tags in code and commit messages — check the tag on a block before assuming a feature is fully wired (e.g. `saved_verses`/`delete_saved_verse` views exist as WL4 stubs already routed in [urls.py](apps/wordlookup/urls.py) even though WL3 is the current milestone).

### Row Level Security

[spiritwise/rls.py](spiritwise/rls.py) enables RLS (no policies) on every `public` table after each `migrate`, which closes Supabase's auto-generated Data API. Django connects as the table owner and bypasses RLS, so don't add policies expecting them to restrict the app.

### Config

All settings are environment-driven via `python-decouple` in [spiritwise/settings.py](spiritwise/settings.py) — there are no separate dev/prod settings modules. Notable env-gated behavior:
- `USE_S3=True` switches `STORAGES['default']` to `S3Boto3Storage` (R2-backed); R2 credentials are loaded unconditionally regardless of this flag since the sermon stream view also uses boto3 directly.
- Redis cache backend auto-switches to `RedisCache` only when `REDIS_URL` points somewhere other than localhost (i.e. in production/Upstash); local dev uses `LocMemCache`.
- `BIBLE_API_KEY` / `ESV_API_KEY` (scripture APIs) and `OPENAI_API_KEY` (Whisper fallback) are optional — endpoints degrade gracefully when unset.
