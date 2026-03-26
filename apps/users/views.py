from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from .serializers import (
    RegisterSerializer,
    AuthResponseSerializer,
    UserPublicSerializer,
    ProfileUpdateSerializer,
    ChangePasswordSerializer,
)

User = get_user_model()


@api_view(['POST'])
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
    return Response(
        AuthResponseSerializer.from_user(user),
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    """
    POST /api/auth/login/
    Body: { username, password }
    Returns: { access, refresh, user }
    """
    username = request.data.get('username', '').strip()
    password = request.data.get('password', '')

    if not username or not password:
        return Response(
            {'detail': 'Username and password are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Allow login with email too
    try:
        user_obj = User.objects.get(email__iexact=username)
        username = user_obj.username
    except User.DoesNotExist:
        pass

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

    return Response(AuthResponseSerializer.from_user(user))


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
    Update first_name, last_name, avatar, daily_goal_minutes.
    """
    serializer = ProfileUpdateSerializer(
        request.user, data=request.data, partial=True
    )
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    serializer.save()
    return Response(UserPublicSerializer(request.user).data)


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
@permission_classes([IsAuthenticated])
def logout(request):
    """
    POST /api/auth/logout/
    Body: { refresh }
    Blacklists the refresh token.
    """
    refresh_token = request.data.get('refresh')
    if not refresh_token:
        return Response(
            {'detail': 'Refresh token is required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        token = RefreshToken(refresh_token)
        token.blacklist()
    except TokenError:
        return Response(
            {'detail': 'Invalid or expired token.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return Response({'detail': 'Successfully logged out.'}, status=status.HTTP_205_RESET_CONTENT)


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
