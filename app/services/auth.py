import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppAccount, AppSession

password_hash = PasswordHash.recommended()
SESSION_COOKIE = "daywell_session"
SESSION_DAYS = 14


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_session(account: AppAccount, db: Session, response: Response) -> None:
    raw_token = secrets.token_urlsafe(48)
    db.add(AppSession(token_hash=token_digest(raw_token), account_id=account.id, expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)))
    db.commit()
    response.set_cookie(SESSION_COOKIE, raw_token, httponly=True, secure=settings.cookie_secure, samesite="lax", max_age=SESSION_DAYS * 86400, path="/")


def clear_session(request: Request, response: Response, db: Session) -> None:
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        session = db.scalar(select(AppSession).where(AppSession.token_hash == token_digest(raw)))
        if session:
            db.delete(session)
            db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


def current_account(request: Request, db: Session) -> AppAccount:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        raise HTTPException(status_code=401, detail="Please sign in to your app account")
    session = db.scalar(select(AppSession).where(AppSession.token_hash == token_digest(raw)))
    if not session:
        raise HTTPException(status_code=401, detail="App session is invalid. Please sign in again.")
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=401, detail="App session expired. Please sign in again.")
    return db.get(AppAccount, session.account_id)


def app_csrf_check(request: Request) -> None:
    # SameSite=Lax protects cookie-backed mutations; require a same-origin fetch marker as defense in depth.
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site and fetch_site not in {"same-origin", "none"}:
        raise HTTPException(status_code=403, detail="Cross-origin request blocked")

