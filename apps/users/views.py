from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer

from .serializers import (
    RegisterSerializer,
    AuthResponseSerializer,
    UserPublicSerializer,
    ProfileUpdateSerializer,
    ChangePasswordSerializer,
)

User = get_user_model()


# ── Refresh-token cookie ──────────────────────────────────────────────────────

def _set_refresh_cookie(response, refresh):
    cookie = settings.REFRESH_COOKIE
    response.set_cookie(
        cookie['key'], refresh,
        max_age=int(settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds()),
        path=cookie['path'], httponly=cookie['httponly'],
        secure=cookie['secure'], samesite=cookie['samesite'],
    )
    return response


def _clear_refresh_cookie(response):
    cookie = settings.REFRESH_COOKIE
    response.delete_cookie(cookie['key'], path=cookie['path'], samesite=cookie['samesite'])
    return response


def _auth_response(user, http_status=status.HTTP_200_OK):
    """{ access, user } in the body; the refresh token only as a cookie."""
    data = AuthResponseSerializer.from_user(user)
    refresh = data.pop('refresh')
    return _set_refresh_cookie(Response(data, status=http_status), refresh)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def register(request):
    """
    POST /api/auth/register/
    Body: { username, email, password, confirm_password, first_name?, last_name? }
    Returns: { access, user } and sets the refresh cookie.
    """
    serializer = RegisterSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = serializer.save()
    return _auth_response(user, status.HTTP_201_CREATED)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def login(request):
    """
    POST /api/auth/login/
    Body: { username, password } — username may also be the email.
    Returns: { access, user } and sets the refresh cookie.
    """
    username = request.data.get('username', '').strip()
    password = request.data.get('password', '')

    if not username or not password:
        return Response(
            {'detail': 'Username and password are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Allow login with email too; usernames match case-insensitively so
    # accounts created before usernames were lowercased still resolve.
    user_obj = (
        User.objects.filter(email__iexact=username).first()
        or User.objects.filter(username=username).first()
        or User.objects.filter(username__iexact=username).first()
    )
    if user_obj:
        username = user_obj.username

    from django.contrib.auth import authenticate
    user = authenticate(request, username=username, password=password)

    if not user:
        return Response(
            {'detail': 'Invalid credentials. Please try again.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if not user.is_active:
        return Response(
            {'detail': 'This account has been deactivated.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Record activity for streak tracking
    user.record_activity()

    return _auth_response(user)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me(request):
    """
    GET /api/auth/me/
    Returns the currently authenticated user.
    """
    return Response(UserPublicSerializer(request.user).data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_profile(request):
    """
    PATCH /api/auth/profile/
    Accepts both JSON and multipart/form-data (for avatar upload).
    """
    from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
    # Re-parse if multipart (avatar upload)
    if hasattr(request, 'FILES') and request.FILES:
        parser = MultiPartParser()

    serializer = ProfileUpdateSerializer(
        request.user, data=request.data, partial=True
    )
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    serializer.save()
    # Refresh from DB to get updated avatar URL
    request.user.refresh_from_db()
    return Response(UserPublicSerializer(request.user, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_avatar(request):
    """
    POST /api/auth/avatar/
    multipart/form-data with avatar field.
    Replaces the user's profile image.
    """
    avatar_file = request.FILES.get('avatar')
    if not avatar_file:
        return Response({'detail': 'avatar file is required.'}, status=status.HTTP_400_BAD_REQUEST)

    # Validate it's an image
    allowed_types = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
    if avatar_file.content_type not in allowed_types:
        return Response(
            {'detail': 'Invalid image format. Use JPEG, PNG, or WebP.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Max 5MB
    if avatar_file.size > 5 * 1024 * 1024:
        return Response(
            {'detail': 'Image too large. Maximum size is 5MB.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = request.user
    # Delete old avatar if exists
    if user.avatar:
        try:
            user.avatar.delete(save=False)
        except Exception:
            pass

    import uuid, os
    ext = os.path.splitext(avatar_file.name)[1] or '.jpg'
    filename = f'{uuid.uuid4().hex}{ext}'
    user.avatar.save(filename, avatar_file, save=True)
    user.refresh_from_db()

    return Response(UserPublicSerializer(user, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    """
    POST /api/auth/change-password/
    Body: { old_password, new_password }
    """
    serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    request.user.set_password(serializer.validated_data['new_password'])
    request.user.save()
    return Response({'detail': 'Password updated successfully.'})


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def token_refresh(request):
    """
    POST /api/auth/token/refresh/
    Reads the refresh cookie, rotates it and returns { access }.
    """
    refresh = request.COOKIES.get(settings.REFRESH_COOKIE['key'])
    if not refresh:
        return Response({'detail': 'No refresh token.'}, status=status.HTTP_401_UNAUTHORIZED)

    serializer = TokenRefreshSerializer(data={'refresh': refresh})
    try:
        serializer.is_valid(raise_exception=True)
    except (TokenError, InvalidToken):
        return _clear_refresh_cookie(Response(
            {'detail': 'Session expired. Please log in again.'},
            status=status.HTTP_401_UNAUTHORIZED,
        ))

    data = serializer.validated_data
    response = Response({'access': data['access']})
    if 'refresh' in data:  # ROTATE_REFRESH_TOKENS
        _set_refresh_cookie(response, data['refresh'])
    return response


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def logout(request):
    """
    POST /api/auth/logout/
    Blacklists the refresh cookie and clears it. AllowAny so it still works
    after the access token has expired; always succeeds.
    """
    refresh = request.COOKIES.get(settings.REFRESH_COOKIE['key'])
    if refresh:
        try:
            RefreshToken(refresh).blacklist()
        except TokenError:
            pass  # Already expired or blacklisted — nothing left to revoke
    return _clear_refresh_cookie(
        Response({'detail': 'Successfully logged out.'}, status=status.HTTP_200_OK)
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_badges(request):
    """
    GET /api/auth/badges/
    Returns the current user's earned badges in reverse-chronological order.
    """
    from apps.users.models import UserBadge
    from .serializers import UserBadgeSerializer
    badges = UserBadge.objects.filter(user=request.user).select_related('badge')
    return Response(UserBadgeSerializer(badges, many=True).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def use_streak_freeze(request):
    """
    POST /api/auth/streak-freeze/
    Manually activates a streak freeze if one is available.
    (Automatic use happens in record_activity — this lets users see
    and manually confirm they have a freeze available.)
    """
    user = request.user
    if not user.streak_freeze_available:
        return Response(
            {'detail': 'No streak freeze available. Reach a 7-day streak to earn one.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return Response({
        'streak_freeze_available': True,
        'streak_freeze_earned_at': user.streak_freeze_earned_at,
        'message': 'Your streak freeze is active. It will automatically protect your streak if you miss a day.',
    })
