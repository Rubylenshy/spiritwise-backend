"""
Health check for Fly's HTTP checks.

Implemented as middleware (placed first in MIDDLEWARE) rather than a URL route
so it answers before ALLOWED_HOSTS validation — Fly's checker hits the machine's
private address, whose Host header isn't in ALLOWED_HOSTS and would otherwise
get a 400. It also skips auth, CORS, and throttling.
"""

from django.db import connection
from django.http import JsonResponse

HEALTH_PATH = '/api/health/'


class HealthCheckMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path != HEALTH_PATH:
            return self.get_response(request)

        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
        except Exception:
            return JsonResponse({'status': 'error', 'database': 'unreachable'}, status=503)

        return JsonResponse({'status': 'ok'})
