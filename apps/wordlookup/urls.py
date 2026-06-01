from django.urls import path
from . import views

urlpatterns = [
    # POST — fetch verse(s) for an exact reference or thematic phrase
    path('lookup/', views.lookup, name='wordlookup-lookup'),

    # POST — Whisper audio-file transcription fallback (rate-limited)
    path('transcribe/', views.transcribe, name='wordlookup-transcribe'),

    # GET — paginated list of the user's past lookups
    path('history/', views.history, name='wordlookup-history'),
]
