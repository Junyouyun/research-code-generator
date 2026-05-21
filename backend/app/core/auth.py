from fastapi import HTTPException, Request, status

from app.core.models import User
from app.services.auth_service import get_user_by_session_token

SESSION_COOKIE_NAME = "rc_session"


def get_current_user(request: Request) -> User:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    user = get_user_by_session_token(token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )

    return user
