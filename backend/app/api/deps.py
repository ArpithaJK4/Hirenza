from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import decode_access_token
from app.models import AuditLog, CandidateProfile, User

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    sub = decode_access_token(token)
    user = db.get(User, int(sub)) if sub and sub.isdigit() else None
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user


def current_profile(user: User = Depends(current_user), db: Session = Depends(get_db)) -> CandidateProfile:
    from app.bootstrap import ensure_profile
    p = ensure_profile(db, user)
    db.commit()
    return p


def audit(db: Session, request: Request | None, user: User | None, action: str, entity: str | None = None,
          entity_id=None, **details) -> None:
    db.add(AuditLog(user_id=user.id if user else None, action=action, entity=entity,
                    entity_id=str(entity_id) if entity_id is not None else None, details=details,
                    ip=request.client.host if request and request.client else None))
