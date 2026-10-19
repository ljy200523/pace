from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StudentCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)


class SignupRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class AccountRead(BaseModel):
    email: str
    student_id: int
    display_name: str


class StudentUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)


class StudentRead(BaseModel):
    id: int
    display_name: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class WellbeingWrite(BaseModel):
    entry_date: date
    sleep_hours: float | None = Field(default=None, ge=0, le=24)
    energy: int | None = Field(default=None, ge=1, le=5, description="1 = very low, 5 = very high")
    mood: int | None = Field(default=None, ge=1, le=5, description="1 = very low, 5 = very good")
    stress: int | None = Field(default=None, ge=1, le=5, description="1 = low, 5 = very high")
    meals_count: int | None = Field(default=None, ge=0, le=20)
    water_glasses: int | None = Field(default=None, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=2000)


class WellbeingRead(WellbeingWrite):
    id: int
    student_id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class NutritionAnalysis(BaseModel):
    detected_food: str = Field(min_length=1, max_length=200)
    quality_tag: Literal["Balanced", "Heavy/Greasy", "Low Nutrient / Refined Carbs", "Snack", "Not enough information"]
    feedback_tip: str = Field(min_length=1, max_length=600)


class NutritionLogRead(NutritionAnalysis):
    id: int
    student_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CalendarEventWrite(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    starts_at: datetime
    ends_at: datetime
    category: str = Field(default="academic", max_length=30)
    provider: Literal["manual", "google", "apple"] = "manual"
    external_id: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def validate_interval(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if (self.starts_at.tzinfo is None) != (self.ends_at.tzinfo is None):
            raise ValueError("starts_at and ends_at must both include a timezone or both omit it")
        return self


class CalendarEventRead(CalendarEventWrite):
    id: int
    student_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CalendarSyncRequest(BaseModel):
    provider: Literal["google", "apple"]
    events: list[CalendarEventWrite] = Field(max_length=500)


class CalendarSyncResponse(BaseModel):
    provider: str
    imported: int
    updated: int


class WorkloadDay(BaseModel):
    day: date
    event_count: int
    scheduled_hours: float


class CalendarForecastWeek(BaseModel):
    week: int
    start: date
    end: date
    effort_points: float
    event_count: int
    classification: str


class CalendarRiskComponent(BaseModel):
    score: float | None
    weight_percent: int
    effort_points: float | None = None
    average_hours: float | None = None


class CalendarRisk(BaseModel):
    score: int | None
    classification: str
    components: dict[str, CalendarRiskComponent]
    days_with_recent_checkins: int
    partial_data: bool
    note: str


class CalendarInsights(BaseModel):
    generated_at: datetime
    weeks: list[CalendarForecastWeek]
    risk: CalendarRisk


class RestBlockResult(BaseModel):
    created: int
    skipped: int
    events: list[CalendarEventRead]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatReply(BaseModel):
    user_message_id: int
    assistant_message_id: int
    reply: str
    source: str


class ChatMessageRead(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
