from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import audit, current_user
from app.bootstrap import create_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.ratelimit import limiter
from app.core.security import create_access_token, verify_password
from app.models import User
from app.schemas import RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201)
@limiter.limit("5/hour")
def register(request: Request, body: RegisterIn, db: Session = Depends(get_db)):
    has_users = db.scalar(select(func.count(User.id))) > 0
    if has_users and not get_settings().allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is closed")
    if db.scalar(select(User.id).where(User.email == body.email.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = create_user(db, body.email, body.password, is_admin=not has_users)
    audit(db, request, user, "auth.register", "user", user.id)
    db.commit()
    return user


@router.post("/login", response_model=TokenOut)
@limiter.limit("10/minute")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == form.username.lower().strip()))
    if not user or not verify_password(form.password, user.hashed_password) or not user.is_active:
        audit(db, request, None, "auth.login_failed", details_email=form.username[:100])
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    audit(db, request, user, "auth.login", "user", user.id)
    db.commit()
    return TokenOut(access_token=create_access_token(str(user.id)))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
