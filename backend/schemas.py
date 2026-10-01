"""Pydantic request/response models for the FastAPI backend."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class DetectionUpdate(BaseModel):
    """Body for POST /detection/update - latest per-lane vehicle counts."""
    lane_counts: Dict[str, int] = Field(..., description="lane_id -> vehicle count")
    emergency_lane: Optional[str] = Field(None, description="lane_id with a CONFIRMED emergency, if any")

    @field_validator("lane_counts")
    @classmethod
    def counts_not_negative(cls, v: Dict[str, int]) -> Dict[str, int]:
        for lane, count in v.items():
            if count < 0:
                raise ValueError(f"vehicle count for lane '{lane}' cannot be negative")
        return v


class DetectionUpdateResponse(BaseModel):
    accepted: bool
    lane_counts: Dict[str, int]
    emergency_lane: Optional[str]


class CycleResult(BaseModel):
    lane: str
    green_duration: int
    yellow_duration: int
    was_emergency: bool
    vehicle_count: int
    logged_id: Optional[int] = None
    failsafe: bool = False
    failsafe_reason: Optional[str] = None


class SignalStateResponse(BaseModel):
    active_lane: Optional[str]
    states: Dict[str, str]
    last_cycle: Optional[CycleResult]


class LogRecord(BaseModel):
    id: int
    lane_id: str
    vehicle_count: int
    green_duration: int
    is_emergency: bool
    timestamp: datetime


class LogsResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[LogRecord]


class HealthResponse(BaseModel):
    status: str
    detection_mode: str = "normal"  # "normal" or "failsafe"
    detection_status_reason: str = "ok"
    time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ManualEmergencyRequest(BaseModel):
    lane_id: str
    active: bool = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)
    role: str = Field(..., description="one of: admin, operator, viewer")


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    created_at: datetime
