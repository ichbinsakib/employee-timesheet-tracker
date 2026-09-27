"""FastAPI dependencies for protected routes."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth.security import COOKIE_NAME, has_role, session_user
from backend.database.session import get_db
from backend.models import User


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = session_user(db, request.cookies.get(COOKIE_NAME))
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    request.state.user = user
    return user


def require(minimum: str):
    def dep(user: User = Depends(current_user)) -> User:
        if not has_role(user, minimum):
            raise HTTPException(status_code=403, detail=f"This action needs the {minimum} role.")
        return user
    return dep


require_viewer = require("viewer")
require_manager = require("manager")
require_admin = require("admin")
