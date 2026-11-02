"""Output schemas for the local model. Each is also the JSON schema that constrains generation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "industrial_accident",
    "natural_hazard",
    "transport_disruption",
    "labor_action",
    "civil_unrest",
    "security_incident",
    "infrastructure_outage",
    "health_outbreak",
    "other",
    "none",
]


class EventLabel(BaseModel):
    # The reason comes first so the model reasons before it commits to a label.
    reason: str = Field(max_length=200)
    event_type: EventType
    severity: int = Field(ge=1, le=4, description="1 minor, 2 moderate, 3 major, 4 severe")
    subject_is_named_private_person: bool


class PlaceChoice(BaseModel):
    reason: str = Field(max_length=200)
    choice: int | None = Field(description="Index of the best candidate, or null if none fits")
    confidence: float = Field(ge=0, le=1)


class BriefingText(BaseModel):
    text: str = Field(max_length=900)
