"""
Row Level Security for the Supabase database.

Supabase exposes every table in the `public` schema through its auto-generated
Data API (PostgREST) to anyone holding the project's anon key. The app never
uses that API — all access goes through Django — so every table gets RLS
enabled with no policies, which denies the anon/authenticated roles entirely.

Django connects as the table owner (`postgres`), and owners bypass RLS, so the
app is unaffected. This runs after every `migrate` (Fly's release command), so
tables added by future migrations are covered automatically.
"""
from django.db import connection

_ENABLE_RLS_SQL = """
DO $$
DECLARE r record;
BEGIN
    FOR r IN
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND NOT c.relrowsecurity
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', r.relname);
    END LOOP;
END $$;
"""


def enable_rls(**kwargs):
    if connection.vendor != 'postgresql':
        return  # SQLite in local dev has no RLS
    with connection.cursor() as cursor:
        cursor.execute(_ENABLE_RLS_SQL)
