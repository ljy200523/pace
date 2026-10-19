from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import CalendarEvent, WellbeingEntry


EVENT_EFFORT_PER_HOUR = {
    "academic": 1.5,
    "class": 1.25,
    "work": 1.5,
    "personal": 0.5,
    "rest": 0.0,
}
WEEK_LABELS = (
    (20, "Light"),
    (40, "Balanced"),
    (60, "Busy"),
    (float("inf"), "Very full"),
)


def _app_zone():
    try:
        return ZoneInfo(settings.app_timezone)
    except ZoneInfoNotFoundError:
        # Singapore has no daylight-saving changes; this keeps the default working
        # on Windows even before the tzdata wheel has been installed.
        if settings.app_timezone == "Asia/Singapore":
            return timezone(timedelta(hours=8), name="Asia/Singapore")
        raise


def _aware(value: datetime) -> datetime:
    zone = _app_zone()
    return value.astimezone(zone) if value.tzinfo else value.replace(tzinfo=zone)


def _event_effort(event: CalendarEvent, start: datetime | None = None, end: datetime | None = None) -> float:
    event_start, event_end = _aware(event.starts_at), _aware(event.ends_at)
    duration = max(0.0, (min(event_end, end) - max(event_start, start)).total_seconds() / 3600) if start and end else max(0.0, (event_end - event_start).total_seconds() / 3600)
    return duration * EVENT_EFFORT_PER_HOUR.get((event.category or "academic").lower(), 1.0)


def insights(student_id: int, db: Session, today: date | None = None) -> dict:
    zone = _app_zone()
    today = today or datetime.now(zone).date()
    start = datetime.combine(today, time.min, tzinfo=zone)
    end = start + timedelta(days=28)
    events = db.scalars(select(CalendarEvent).where(
        CalendarEvent.student_id == student_id,
        CalendarEvent.starts_at < end,
        CalendarEvent.ends_at > start,
    )).all()
    weeks = []
    daily_effort: dict[date, float] = {}
    for week_index in range(4):
        week_start = start + timedelta(days=week_index * 7)
        week_end = week_start + timedelta(days=7)
        effort = 0.0
        event_count = 0
        for event in events:
            event_start, event_end = _aware(event.starts_at), _aware(event.ends_at)
            overlap_start, overlap_end = max(event_start, week_start), min(event_end, week_end)
            if overlap_start < overlap_end:
                effort += _event_effort(event, week_start, week_end)
                event_count += 1
                cursor = overlap_start
                while cursor < overlap_end:
                    next_date = cursor.astimezone(zone).date() + timedelta(days=1)
                    day_end = min(datetime.combine(next_date, time.min, tzinfo=zone), overlap_end)
                    daily_effort[cursor.date()] = daily_effort.get(cursor.date(), 0.0) + _event_effort(event, cursor, day_end)
                    cursor = day_end
        label = next(name for ceiling, name in WEEK_LABELS if effort < ceiling)
        weeks.append({
            "week": week_index + 1,
            "start": week_start.date().isoformat(),
            "end": (week_end - timedelta(days=1)).date().isoformat(),
            "effort_points": round(effort, 1),
            "event_count": event_count,
            "classification": label,
        })

    recent = db.scalars(select(WellbeingEntry).where(
        WellbeingEntry.student_id == student_id,
        WellbeingEntry.entry_date >= today - timedelta(days=2),
        WellbeingEntry.entry_date <= today,
    ).order_by(WellbeingEntry.entry_date.desc())).all()
    sleep_values = [float(row.sleep_hours) for row in recent if row.sleep_hours is not None]
    average_sleep = sum(sleep_values) / len(sleep_values) if sleep_values else None
    sleep_score = None if average_sleep is None else round(min(100.0, max(0.0, (7.5 - average_sleep) / 7.5 * 100)), 1)
    mood_energy = [value for row in recent for value in (row.mood, row.energy) if value is not None]
    wellbeing_score = None if not mood_energy else round(sum((5 - value) / 4 * 100 for value in mood_energy) / len(mood_energy), 1)
    week_workload = weeks[0]["effort_points"]
    workload_score = round(min(100.0, week_workload / 40 * 100), 1)
    components = [(workload_score, 0.4), (sleep_score, 0.3), (wellbeing_score, 0.3)]
    available = [(score, weight) for score, weight in components if score is not None]
    risk_score = round(sum(score * weight for score, weight in available) / sum(weight for _, weight in available)) if available else None
    partial_data = average_sleep is None or not mood_energy
    risk_label = "No recent data" if risk_score is None else "Partial data" if partial_data else "Low" if risk_score < 30 else "Moderate" if risk_score < 60 else "Elevated"
    low_energy = [row.energy for row in recent if row.energy is not None]
    low_energy_signal = bool(low_energy and sum(low_energy) / len(low_energy) <= 2)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "weeks": weeks,
        "risk": {
            "score": risk_score,
            "classification": risk_label,
            "components": {
                "workload": {"score": workload_score, "weight_percent": 40, "effort_points": week_workload},
                "sleep": {"score": sleep_score, "weight_percent": 30, "average_hours": round(average_sleep, 1) if average_sleep is not None else None},
                "mood_energy": {"score": wellbeing_score, "weight_percent": 30},
            },
            "days_with_recent_checkins": len(recent),
            "partial_data": partial_data,
            "note": "A planning signal based on the available calendar and check-ins, not a diagnosis.",
        },
        "daily_effort": {day.isoformat(): round(value, 1) for day, value in daily_effort.items()},
        "low_energy_signal": low_energy_signal,
    }


def recovery_candidates(student_id: int, db: Session, today: date | None = None, days: int = 7) -> list[dict]:
    report = insights(student_id, db, today)
    zone = _app_zone()
    today = today or datetime.now(zone).date()
    start = datetime.combine(today, time.min, tzinfo=zone)
    end = start + timedelta(days=days)
    events = db.scalars(select(CalendarEvent).where(
        CalendarEvent.student_id == student_id,
        CalendarEvent.starts_at < end,
        CalendarEvent.ends_at > start,
    )).all()
    candidates = []
    for offset in range(days):
        day = today + timedelta(days=offset)
        if report["daily_effort"].get(day.isoformat(), 0) < 8 and not report["low_energy_signal"]:
            continue
        day_start = datetime.combine(day, time(9), tzinfo=zone)
        day_end = datetime.combine(day, time(21), tzinfo=zone)
        busy = sorted(
            (max(_aware(event.starts_at), day_start), min(_aware(event.ends_at), day_end))
            for event in events
            if _aware(event.starts_at) < day_end and _aware(event.ends_at) > day_start
        )
        merged: list[list[datetime]] = []
        for busy_start, busy_end in busy:
            if merged and busy_start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], busy_end)
            else:
                merged.append([busy_start, busy_end])
        cursor = day_start
        gaps = []
        for busy_start, busy_end in merged:
            if busy_start - cursor >= timedelta(hours=2):
                gaps.append((cursor, busy_start))
            cursor = max(cursor, busy_end)
        if day_end - cursor >= timedelta(hours=2):
            gaps.append((cursor, day_end))
        if not gaps:
            continue
        # Place recovery after the busiest occupied stretch when possible, otherwise use the first open gap.
        chosen = max(gaps, key=lambda gap: (min(gap[1], gap[0] + timedelta(hours=4)) - max(gap[0], day_start + timedelta(hours=3))).total_seconds())
        block_start = max(chosen[0], day_start + timedelta(hours=3))
        if chosen[1] - block_start < timedelta(hours=2):
            block_start = chosen[0]
        candidates.append({
            "date": day.isoformat(),
            "starts_at": block_start.isoformat(),
            "ends_at": (block_start + timedelta(hours=2)).isoformat(),
            "reason": "Low recent energy" if report["low_energy_signal"] else "A full workload day",
        })
    return candidates
