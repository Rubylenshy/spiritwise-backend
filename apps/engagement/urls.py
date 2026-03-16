from django.urls import path
from . import views

urlpatterns = [
    path('stats/', views.stats, name='engagement-stats'),
    path('log/', views.log_activity, name='engagement-log'),
    path('answers/', views.question_answers, name='engagement-answers'),
    path('leaderboard/', views.leaderboard, name='engagement-leaderboard'),
]
