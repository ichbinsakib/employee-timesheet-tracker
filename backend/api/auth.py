from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.auth import security
from backend.auth.deps import current_user
from backend.database.session import get_db
from backend.models import AccessLog, User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


def _user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "role": u.role}


def _log(db: Session, request: Request, event: str, username: str | None) -> None:
    db.add(AccessLog(username=username, ip=security.client_ip(request), via=security.access_channel(request),
                     event=event, method=request.method, path=request.url.path))
    db.commit()


def _set_cookie(response: Response, request: Request, token: str) -> None:
    from backend.config import settings
    response.set_cookie(security.COOKIE_NAME, token, httponly=True, samesite="strict",
                        secure=security.cookie_secure(request), max_age=settings.session_hours * 3600, path="/")


@router.get("/status")
def status(request: Request, db: Session = Depends(get_db)):
    no_users = (db.scalar(select(func.count(User.id))) or 0) == 0
    return {"setup_required": no_users, "can_setup_here": no_users and security.is_local_request(request),
            "channel": security.access_channel(request), "https": security.is_https(request)}


@router.post("/setup")
def first_run_setup(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    """Create the first administrator. Only allowed from the desktop itself and only once."""
    if db.scalar(select(func.count(User.id))):
        raise HTTPException(409, "Setup has already been completed.")
    if not security.is_local_request(request):
        raise HTTPException(403, "The first administrator can only be created on the desktop (http://localhost).")
    if len(body.username.strip()) < 3:
        raise HTTPException(400, "Username must be at least 3 characters.")
    if err := security.validate_new_password(body.password):
        raise HTTPException(400, err)
    user = User(username=body.username.strip(), password_hash=security.hash_password(body.password), role="admin")
    db.add(user)
    db.commit()
    _set_cookie(response, request, security.create_session(db, user, request))
    _log(db, request, "setup", user.username)
    return _user_out(user)


@router.post("/login")
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    key = security.client_ip(request)
    if security.throttle.blocked(key):
        _log(db, request, "login_blocked", body.username[:100])
        raise HTTPException(429, "Too many failed sign-in attempts. Try again in 15 minutes.")
    user = db.scalar(select(User).where(func.lower(User.username) == body.username.strip().lower()))
    if user is None or not user.active or not security.verify_password(body.password, user.password_hash):
        security.throttle.fail(key)
        _log(db, request, "login_failed", body.username[:100])
        raise HTTPException(401, "Incorrect username or password.")
    security.throttle.reset(key)
    _set_cookie(response, request, security.create_session(db, user, request))
    _log(db, request, "login_ok", user.username)
    return _user_out(user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    user = security.session_user(db, request.cookies.get(security.COOKIE_NAME))
    security.end_session(db, request.cookies.get(security.COOKIE_NAME))
    response.delete_cookie(security.COOKIE_NAME, path="/")
    _log(db, request, "logout", user.username if user else None)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return _user_out(user)


@router.post("/password")
def change_password(body: PasswordChange, request: Request, response: Response,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    user = db.get(User, user.id)
    if not security.verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect.")
    if err := security.validate_new_password(body.new_password):
        raise HTTPException(400, err)
    user.password_hash = security.hash_password(body.new_password)
    security.end_all_sessions(db, user.id)
    db.commit()
    _set_cookie(response, request, security.create_session(db, user, request))
    return {"ok": True}
