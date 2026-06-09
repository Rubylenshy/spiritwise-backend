from django.urls import path
from . import views

urlpatterns = [
    # POST — fetch verse(s) for an exact reference or phrase (WL2+WL3)
    path('lookup/', views.lookup, name='wordlookup-lookup'),

    # POST — Whisper audio-file transcription fallback (WL1)
    path('transcribe/', views.transcribe, name='wordlookup-transcribe'),

    # GET — paginated list of the user's past lookups (WL2)
    path('history/', views.history, name='wordlookup-history'),

    # GET/POST — saved verse collection (WL4, wired here for clean URLs)
    path('saved/', views.saved_verses, name='wordlookup-saved'),
    path('saved/<int:pk>/', views.delete_saved_verse, name='wordlookup-saved-delete'),
]
