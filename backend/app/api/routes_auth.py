from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.core.auth import SESSION_COOKIE_NAME, get_current_user
from app.core.models import User
from app.core.schemas import AuthRequest, AuthResponse, RegisterRequest, UserResponse
from app.services.auth_service import (
    SESSION_DAYS,
    authenticate_user,
    create_session,
    create_user,
    delete_session,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse)
def register(payload: RegisterRequest, response: Response) -> AuthResponse:
    try:
        user = create_user(
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    _set_session_cookie(response, create_session(user.user_id))
    return AuthResponse(user=_to_user_response(user))


@router.post("/login", response_model=AuthResponse)
def login(payload: AuthRequest, response: Response) -> AuthResponse:
    user = authenticate_user(payload.email, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_email_or_password",
        )

    _set_session_cookie(response, create_session(user.user_id))
    return AuthResponse(user=_to_user_response(user))


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        delete_session(token)

    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        samesite="lax",
    )
    return {"ok": True}


@router.get("/me", response_model=AuthResponse)
def me(current_user: User = Depends(get_current_user)) -> AuthResponse:
    return AuthResponse(user=_to_user_response(current_user))


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(
        user_id=user.user_id,
        email=user.email,
        display_name=user.display_name,
        avatar_initial=user.avatar_initial,
        plan=user.plan,
    )
