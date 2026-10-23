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


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def register(request):
    """
    POST /api/auth/register/
    Body: { username, email, password, confirm_password, first_name?, last_name? }
    Returns: { access, refresh, user }
    """
    serializer = RegisterSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = serializer.save()
    return Response(AuthResponseSerializer.from_user(user, request), status=status.HTTP_201_CREATED)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def login(request):
    """
    POST /api/auth/login/
    Body: { username, password } — username may also be the email.
    Returns: { access, refresh, user }
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

    return Response(AuthResponseSerializer.from_user(user, request))


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def google_login(request):
    """
    POST /api/auth/google/
    Body: { credential } — the ID token from Google Identity Services.
    Signs in the account with that verified email, creating one on first use.
    Returns: { access, refresh, user, created }
    """
    from django.conf import settings
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    if not settings.GOOGLE_OAUTH_CLIENT_ID:
        return Response(
            {'detail': 'Google sign-in is not configured.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    credential = request.data.get('credential', '')
    if not credential:
        return Response({'detail': 'credential is required.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        # Checks the signature, expiry, issuer and that it was issued to our client
        claims = id_token.verify_oauth2_token(
            credential, google_requests.Request(), settings.GOOGLE_OAUTH_CLIENT_ID,
        )
    except ValueError:
        return Response(
            {'detail': 'Google sign-in failed. Please try again.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    email = (claims.get('email') or '').lower()
    if not email or not claims.get('email_verified'):
        return Response(
            {'detail': 'Your Google account has no verified email address.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    user = User.objects.filter(email__iexact=email).first()
    created = user is None
    if created:
        user = User(
            username=_unique_username(email.split('@')[0]),
            email=email,
            first_name=(claims.get('given_name') or '')[:150],
            last_name=(claims.get('family_name') or '')[:150],
        )
        user.set_unusable_password()  # Google-only until they set a password
        user.save()

    if not user.is_active:
        return Response(
            {'detail': 'This account has been deactivated.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    user.record_activity()
    return Response(
        {**AuthResponseSerializer.from_user(user, request), 'created': created},
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


def _unique_username(seed: str) -> str:
    """A free lowercase username derived from `seed` (an email's local part)."""
    import re
    base = re.sub(r'[^\w.+-]', '', seed.lower())[:140] or 'user'
    username, n = base, 1
    while User.objects.filter(username__iexact=username).exists():
        n += 1
        username = f'{base}{n}'
    return username


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me(request):
    """
    GET /api/auth/me/
    Returns the currently authenticated user.

    The app calls this on every load, so it also counts as the day's visit for
    the streak — a session restored from a stored token never hits login.
    """
    request.user.record_activity('login')
    return Response(UserPublicSerializer(request.user, context={'request': request}).data)


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


@api_view(['POST', 'DELETE'])
@permission_classes([IsAuthenticated])
def upload_avatar(request):
    """
    POST   /api/auth/avatar/ — multipart/form-data with an `avatar` field;
           replaces the user's profile image (the client crops it first).
    DELETE /api/auth/avatar/ — removes the profile image.
    Both return the updated user.
    """
    user = request.user

    if request.method == 'DELETE':
        _delete_avatar_file(user)
        user.avatar = None
        user.save(update_fields=['avatar'])
        return Response(UserPublicSerializer(user, context={'request': request}).data)

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

    _delete_avatar_file(user)

    import uuid, os
    ext = os.path.splitext(avatar_file.name)[1] or '.jpg'
    filename = f'{uuid.uuid4().hex}{ext}'
    user.avatar.save(filename, avatar_file, save=False)
    user.save(update_fields=['avatar'])

    return Response(UserPublicSerializer(user, context={'request': request}).data)


def _delete_avatar_file(user):
    """Best-effort removal of the stored avatar file; the field is left to the caller."""
    if user.avatar:
        try:
            user.avatar.delete(save=False)
        except Exception:
            pass


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
    request.user.save(update_fields=['password'])
    return Response({'detail': 'Password updated successfully.'})


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def token_refresh(request):
    """
    POST /api/auth/token/refresh/
    Body: { refresh }
    Returns { access, refresh } — the refresh token rotates and the old one
    is blacklisted, so clients must keep the new one.
    """
    serializer = TokenRefreshSerializer(data={'refresh': request.data.get('refresh', '')})
    try:
        serializer.is_valid(raise_exception=True)
    except (TokenError, InvalidToken):
        return Response(
            {'detail': 'Session expired. Please log in again.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    return Response(serializer.validated_data)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def logout(request):
    """
    POST /api/auth/logout/
    Body: { refresh }
    Blacklists the refresh token. AllowAny so it still works after the access
    token has expired; always succeeds.
    """
    refresh = request.data.get('refresh')
    if refresh:
        try:
            RefreshToken(refresh).blacklist()
        except TokenError:
            pass  # Already expired or blacklisted — nothing left to revoke
    return Response({'detail': 'Successfully logged out.'})


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
