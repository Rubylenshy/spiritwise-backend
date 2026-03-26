from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

urlpatterns = [
    # Badges & streak freeze
    path('badges/', views.my_badges, name='auth-badges'),
    path('streak-freeze/', views.use_streak_freeze, name='auth-streak-freeze'),

    # Registration & login
    path('register/', views.register, name='auth-register'),
    path('login/', views.login, name='auth-login'),
    path('logout/', views.logout, name='auth-logout'),

    # JWT token management
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),

    # Profile
    path('me/', views.me, name='auth-me'),
    path('profile/', views.update_profile, name='auth-profile-update'),
    path('change-password/', views.change_password, name='auth-change-password'),
]
