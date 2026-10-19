import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppAccount, CalendarEvent, GoogleCalendarConnection, Student

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_API = "https://www.googleapis.com/calendar/v3"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPES = ["openid", "email", "https://www.googleapis.com/auth/calendar.events"]


def configured() -> None:
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=503, detail="Google Calendar is not configured. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to .env.")
    if not settings.google_token_encryption_key:
        raise HTTPException(status_code=503, detail="Google token encryption is not configured. Set GOOGLE_TOKEN_ENCRYPTION_KEY in .env.")


def _fernet() -> Fernet:
    if not settings.google_token_encryption_key:
        raise HTTPException(status_code=503, detail="Google token encryption is not configured. Set GOOGLE_TOKEN_ENCRYPTION_KEY in .env.")
    try:
        return Fernet(settings.google_token_encryption_key.encode())
    except Exception as exc:
        raise HTTPException(status_code=500, detail="GOOGLE_TOKEN_ENCRYPTION_KEY must be a valid Fernet key.") from exc


def protect(value: str | None) -> str | None:
    return _fernet().encrypt(value.encode()).decode() if value else None


def reveal(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise HTTPException(status_code=500, detail="Stored Google token could not be decrypted. Check token encryption configuration.") from exc


def authorization_url(account: AppAccount, state: str) -> str:
    configured()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
        "login_hint": account.email,
    }
    return f"{GOOGLE_AUTH}?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    configured()
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(GOOGLE_TOKEN, data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        })
    if response.is_error:
        raise HTTPException(status_code=502, detail="Google authorization could not be completed. Check the redirect URI and OAuth client configuration.")
    return response.json()


async def google_email(access_token: str) -> str | None:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(GOOGLE_USERINFO, headers={"Authorization": f"Bearer {access_token}"})
    if response.is_error:
        return None
    return response.json().get("email")


def get_connection(account: AppAccount, db: Session) -> GoogleCalendarConnection:
    connection = db.scalar(select(GoogleCalendarConnection).where(GoogleCalendarConnection.account_id == account.id))
    if not connection:
        raise HTTPException(status_code=409, detail="Connect a Google Calendar account first")
    return connection


async def userinfo_scopes(access_token_value: str) -> set[str]:
    """Return the scopes Google actually granted to this access token."""
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"access_token": access_token_value},
        )
    if response.is_error:
        return set()
    return set(response.json().get("scope", "").split())


async def fetch_upcoming_events(account: AppAccount, db: Session, days: int = 14, limit: int = 40) -> list[dict]:
    """Fetch a compact, current event window directly from Google for chat context."""
    connection = get_connection(account, db)
    now = datetime.now(timezone.utc)
    data = await _request(
        connection,
        db,
        "GET",
        "/calendars/primary/events",
        params={
            "timeMin": now.isoformat(),
            "timeMax": (now + timedelta(days=days)).isoformat(),
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": min(max(limit, 1), 50),
        },
    )
    compact = []
    for event in data.get("items", []):
        if event.get("status") == "cancelled":
            continue
        start = event.get("start") or {}
        end = event.get("end") or {}
        start_value = start.get("dateTime") or start.get("date")
        end_value = end.get("dateTime") or end.get("date")
        if not start_value or not end_value:
            continue
        compact.append({
            "title": (event.get("summary") or "Untitled event")[:140],
            "starts_at": start_value,
            "ends_at": end_value,
            "category": _event_category(event),
            "all_day": "date" in start and "dateTime" not in start,
        })
    return compact


async def access_token(connection: GoogleCalendarConnection, db: Session) -> str:
    token = reveal(connection.access_token)
    expires_at = connection.token_expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and expires_at > datetime.now(timezone.utc) + timedelta(minutes=2):
        return token
    refresh_token = reveal(connection.refresh_token)
    if not refresh_token:
        raise HTTPException(status_code=409, detail="Google authorization expired. Disconnect and connect Google Calendar again.")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(GOOGLE_TOKEN, data={
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
    if response.is_error:
        raise HTTPException(status_code=409, detail="Google authorization needs attention. Reconnect Google Calendar.")
    body = response.json()
    connection.access_token = protect(body["access_token"])
    connection.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(body.get("expires_in", 3600)))
    db.commit()
    return body["access_token"]


def _student(account: AppAccount, db: Session) -> Student:
    if not account.student_id:
        student = Student(display_name=account.email.split("@")[0])
        db.add(student)
        db.flush()
        account.student_id = student.id
        db.commit()
        db.refresh(account)
        return student
    student = db.get(Student, account.student_id)
    if not student:
        raise HTTPException(status_code=404, detail="App student profile was not found")
    return student


async def _request(connection: GoogleCalendarConnection, db: Session, method: str, path: str, **kwargs) -> dict:
    token = await access_token(connection, db)
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.request(method, f"{GOOGLE_API}{path}", headers={"Authorization": f"Bearer {token}"}, **kwargs)
    if response.status_code == 401:
        connection.token_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        token = await access_token(connection, db)
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.request(method, f"{GOOGLE_API}{path}", headers={"Authorization": f"Bearer {token}"}, **kwargs)
    if response.status_code == 410:
        raise HTTPException(status_code=410, detail="Google requested a full calendar resync")
    if response.status_code == 404 and method == "DELETE":
        return {}
    if response.is_error:
        try:
            body = response.json()
            google_error = body.get("error", {})
            reasons = [item.get("reason") for item in google_error.get("errors", []) if isinstance(item, dict) and item.get("reason")]
            message = google_error.get("message")
        except (ValueError, AttributeError):
            reasons, message = [], None
        # Google error text can include request details; log only its structured reason and
        # a bounded message, never response headers or token-bearing request data.
        logging.getLogger(__name__).warning(
            "Google Calendar API rejected %s %s: status=%s reasons=%s message=%s",
            method, path, response.status_code, reasons[:5], str(message)[:300] if message else None,
        )
        if response.status_code == 403 and "insufficientPermissions" in reasons:
            raise HTTPException(
                status_code=403,
                detail="Google granted this app identity access without Calendar permissions. Disconnect Google Calendar and reconnect, approving the calendar.events permission.",
            )
        raise HTTPException(status_code=502, detail=f"Google Calendar request failed ({response.status_code}). Check the Google connection and Calendar API access.")
    return response.json() if response.content else {}


def _event_times(resource: dict) -> tuple[datetime, datetime]:
    start_raw = resource.get("start", {}).get("dateTime") or resource.get("start", {}).get("date")
    end_raw = resource.get("end", {}).get("dateTime") or resource.get("end", {}).get("date")
    if not start_raw or not end_raw:
        raise ValueError("Google event missing start or end")
    def parse(value: str) -> datetime:
        if len(value) == 10:
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parse(start_raw), parse(end_raw)


def _event_category(resource: dict) -> str:
    private = (resource.get("extendedProperties") or {}).get("private") or {}
    saved = private.get("paceCategory")
    if saved in {"academic", "class", "work", "personal", "rest"}:
        return saved
    title = (resource.get("summary") or "").lower()
    if any(word in title for word in ("protected recovery", "break", "recovery")) or title == "rest" or title.startswith("rest "):
        return "rest"
    if any(word in title for word in ("lecture", "tutorial", "seminar", "lab", "class")):
        return "class"
    if any(word in title for word in ("work shift", "work meeting", "shift")):
        return "work"
    if any(word in title for word in ("appointment", "gym", "personal")):
        return "personal"
    return "academic"


async def pull_events(account: AppAccount, db: Session, full: bool = False) -> dict[str, int]:
    connection = get_connection(account, db)
    student = _student(account, db)
    params: dict[str, str | bool] = {"singleEvents": True, "showDeleted": True, "maxResults": 2500}
    if connection.sync_token and not full:
        params["syncToken"] = connection.sync_token
    else:
        params["timeMin"] = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        params["timeMax"] = (datetime.now(timezone.utc) + timedelta(days=730)).isoformat()

    imported = updated = deleted = 0
    page_token = None
    next_sync_token = None
    while True:
        page_params = dict(params)
        if page_token:
            page_params["pageToken"] = page_token
        try:
            data = await _request(connection, db, "GET", "/calendars/primary/events", params=page_params)
        except HTTPException as exc:
            if exc.status_code == 410 and not full:
                connection.sync_token = None
                db.commit()
                return await pull_events(account, db, full=True)
            raise
        for resource in data.get("items", []):
            ext_id = resource.get("id")
            if not ext_id:
                continue
            event = db.scalar(select(CalendarEvent).where(CalendarEvent.student_id == student.id, CalendarEvent.provider == "google", CalendarEvent.external_id == ext_id))
            if resource.get("status") == "cancelled":
                if event:
                    db.delete(event)
                    deleted += 1
                continue
            try:
                starts_at, ends_at = _event_times(resource)
            except (ValueError, TypeError):
                continue
            values = {"title": (resource.get("summary") or "Untitled event")[:200], "starts_at": starts_at, "ends_at": ends_at, "category": _event_category(resource), "provider": "google", "external_id": ext_id}
            if event:
                for key, value in values.items():
                    setattr(event, key, value)
                updated += 1
            else:
                db.add(CalendarEvent(student_id=student.id, **values))
                imported += 1
        db.commit()
        page_token = data.get("nextPageToken")
        next_sync_token = data.get("nextSyncToken", next_sync_token)
        if not page_token:
            break
    if next_sync_token:
        connection.sync_token = next_sync_token
        db.commit()
    return {"imported": imported, "updated": updated, "deleted": deleted}


def google_payload(event: CalendarEvent) -> dict:
    starts = event.starts_at
    ends = event.ends_at
    if starts.tzinfo is None:
        starts = starts.replace(tzinfo=timezone.utc)
    if ends.tzinfo is None:
        ends = ends.replace(tzinfo=timezone.utc)
    return {"summary": event.title, "start": {"dateTime": starts.isoformat()}, "end": {"dateTime": ends.isoformat()}, "extendedProperties": {"private": {"daywellEventId": str(event.id), "paceCategory": event.category}}}


async def push_event(account: AppAccount, event: CalendarEvent, db: Session) -> CalendarEvent:
    if event.provider == "google":
        return event
    connection = get_connection(account, db)
    result = await _request(connection, db, "POST", "/calendars/primary/events", json=google_payload(event))
    event.provider = "google"
    event.external_id = result["id"]
    db.commit()
    db.refresh(event)
    return event


async def push_update(account: AppAccount, event: CalendarEvent, db: Session) -> CalendarEvent:
    if event.provider != "google" or not event.external_id:
        return await push_event(account, event, db)
    connection = get_connection(account, db)
    result = await _request(connection, db, "PUT", f"/calendars/primary/events/{event.external_id}", json=google_payload(event))
    db.refresh(event)
    return event


async def push_pending_events(account: AppAccount, db: Session) -> int:
    student = _student(account, db)
    pending = db.scalars(select(CalendarEvent).where(CalendarEvent.student_id == student.id, CalendarEvent.provider == "manual")).all()
    for event in pending:
        await push_event(account, event, db)
    return len(pending)


async def push_delete(account: AppAccount, event: CalendarEvent, db: Session) -> None:
    if event.provider != "google" or not event.external_id:
        return
    connection = get_connection(account, db)
    await _request(connection, db, "DELETE", f"/calendars/primary/events/{event.external_id}")


async def revoke_connection(connection: GoogleCalendarConnection) -> None:
    token = reveal(connection.refresh_token) or reveal(connection.access_token)
    if not token:
        return
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post("https://oauth2.googleapis.com/revoke", data={"token": token})


async def stop_watch(connection: GoogleCalendarConnection, db: Session) -> None:
    if not connection.channel_id or not connection.resource_id:
        return
    await _request(connection, db, "POST", "/channels/stop", json={"id": connection.channel_id, "resourceId": connection.resource_id})


async def start_watch(account: AppAccount, db: Session) -> bool:
    connection = get_connection(account, db)
    if not settings.public_base_url.startswith("https://"):
        return False
    channel_id = secrets.token_urlsafe(24)
    expiration_ms = int((datetime.now(timezone.utc) + timedelta(days=6)).timestamp() * 1000)
    channel_token = secrets.token_urlsafe(32)
    result = await _request(connection, db, "POST", "/calendars/primary/events/watch", json={
        "id": channel_id,
        "type": "web_hook",
        "address": f"{settings.public_base_url.rstrip('/')}{settings.api_prefix}/google/webhook",
        "token": channel_token,
        "expiration": str(expiration_ms),
    })
    connection.channel_id = channel_id
    connection.resource_id = result.get("resourceId")
    connection.channel_token = channel_token
    connection.channel_expires_at = datetime.fromtimestamp(int(result.get("expiration", expiration_ms)) / 1000, tz=timezone.utc)
    db.commit()
    return True
