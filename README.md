# SpiritWise — Django Backend

REST API backend for SpiritWise, built with Django 5 + Django REST Framework + SimpleJWT.

## Tech stack

| Tool | Purpose |
|---|---|
| Django 5 | Web framework |
| Django REST Framework | API layer |
| SimpleJWT | JWT access + refresh tokens |
| PostgreSQL | Primary database |
| Celery + Redis | Background task queue |
| django-storages + boto3 | S3 audio file storage |
| Google API Client | Drive import |

---

## Quick start

### 1. Create & activate a virtual environment

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env — at minimum set DATABASE_URL and SECRET_KEY
```

### 4. Run migrations

```bash
python manage.py migrate
```

### 5. Create a superuser

```bash
python manage.py createsuperuser
```

### 6. Seed sample data (optional)

```bash
python manage.py seed_data
```

### 7. Start the dev server

```bash
python manage.py runserver
```

API is now live at **http://localhost:8000/api/**

---

## Running Celery (for imports & leaderboard tasks)

```bash
# In a separate terminal:
celery -A spiritwise worker -l info

# Beat scheduler (periodic tasks):
celery -A spiritwise beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

---

## API Reference

### Auth  `POST /api/auth/`

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/auth/register/` | Public | Register + get tokens |
| POST | `/auth/login/` | Public | Login + get tokens |
| POST | `/auth/logout/` | Bearer | Blacklist refresh token |
| POST | `/auth/token/refresh/` | — | Refresh access token |
| GET | `/auth/me/` | Bearer | Current user |
| PATCH | `/auth/profile/` | Bearer | Update profile |
| POST | `/auth/change-password/` | Bearer | Change password |

### Sermons  `GET /api/sermons/`

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/sermons/` | Bearer | List (search: `q`, `tag`, `series`, `speaker`) |
| GET | `/sermons/<id>/` | Bearer | Full detail + signed audio URL |
| POST | `/sermons/<id>/progress/` | Bearer | Update play progress |
| GET | `/sermons/series/` | Bearer | All series |
| GET | `/sermons/series/<id>/` | Bearer | Series + its sermons |
| GET | `/sermons/tags/` | Bearer | All tags |

### Engagement  `/api/engagement/`

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/engagement/stats/` | Bearer | Streak, XP, daily goal |
| POST | `/engagement/log/` | Bearer | Log an activity |
| GET | `/engagement/answers/` | Bearer | User's reflection answers |
| POST | `/engagement/answers/` | Bearer | Submit an answer (+10 XP) |
| GET | `/engagement/leaderboard/?period=weekly` | Bearer | Top 50 + your rank |

### Imports  `/api/imports/`  *(admin only)*

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/imports/` | Admin | List all jobs |
| POST | `/imports/` | Admin | Queue a new import job |
| GET | `/imports/<id>/` | Admin | Poll job progress |

---

## Project structure

```
spiritwise-backend/
├── spiritwise/
│   ├── settings.py         # All config (env-driven)
│   ├── urls.py             # Root URL router
│   ├── celery.py           # Celery app
│   └── wsgi.py
├── apps/
│   ├── users/              # Custom User model + JWT auth endpoints
│   │   ├── models.py       # User, XPTransaction
│   │   ├── serializers.py
│   │   ├── views.py        # register, login, me, profile, logout
│   │   └── urls.py
│   ├── sermons/            # Sermon library
│   │   ├── models.py       # Sermon, Series, Tag, SermonQuestion, ListenHistory
│   │   ├── serializers.py  # signed URL generation, user progress
│   │   ├── views.py        # list, detail, progress update
│   │   └── urls.py
│   ├── engagement/         # Streaks, XP, leaderboard
│   │   ├── models.py       # StreakRecord, QuestionAnswer, LeaderboardEntry
│   │   ├── views.py        # stats, log, answers, leaderboard
│   │   ├── tasks.py        # Celery: leaderboard refresh, streak reset
│   │   └── management/commands/seed_data.py
│   └── imports/            # Cloud import pipeline
│       ├── models.py       # CloudImportJob
│       ├── tasks.py        # Celery: Drive download → S3 → Sermon
│       ├── views.py
│       └── urls.py
├── .env.example
├── manage.py
└── requirements.txt
```

---

## Deployment checklist

- [ ] Set `DEBUG=False` and a strong `SECRET_KEY`
- [ ] Set `DATABASE_URL` to your production PostgreSQL instance
- [ ] Set `ALLOWED_HOSTS` to your domain
- [ ] Set `CORS_ALLOWED_ORIGINS` to your frontend domain
- [ ] Set `USE_S3=True` and fill in AWS credentials
- [ ] Run `python manage.py collectstatic`
- [ ] Set up Celery worker + beat as system services
- [ ] Configure periodic tasks in Django admin under **Periodic Tasks**
