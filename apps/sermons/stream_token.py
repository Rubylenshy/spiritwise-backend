"""
Short-lived stream tokens for audio elements.

The HTML5 <audio> element cannot send Authorization headers.
Solution: generate a signed token (valid 2 hours) that encodes
the user ID and sermon ID, append it as ?token= to the stream URL.

The stream endpoint accepts EITHER:
  - Authorization: Bearer <jwt>   (API calls)
  - ?token=<signed_token>         (audio element)
"""
from django.core import signing
from django.contrib.auth import get_user_model

User = get_user_model()

SALT = 'spiritwise-stream-token'
MAX_AGE = 60 * 60 * 2  # 2 hours


def generate_stream_token(user_id: int, sermon_id: int) -> str:
    """Generate a signed token valid for 2 hours."""
    return signing.dumps(
        {'uid': user_id, 'sid': sermon_id},
        salt=SALT,
    )


def validate_stream_token(token: str, sermon_id: int):
    """
    Validate a stream token.
    Returns the User if valid, None if invalid/expired.
    """
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE)
        if data.get('sid') != sermon_id:
            return None
        return User.objects.get(pk=data['uid'])
    except (signing.BadSignature, signing.SignatureExpired, User.DoesNotExist):
        return None
