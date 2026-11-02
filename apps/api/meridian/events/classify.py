"""Label a news report with an event type, subtype, and severity using the local model."""

from __future__ import annotations

from dataclasses import dataclass

from meridian.events.config import EventsConfig
from meridian.llm.client import LlmClient, LlmError
from meridian.llm.prompts import EVENT_LABEL_VERSION, event_label_prompt
from meridian.llm.schemas import EventLabel

LEAD_CHARS = 600


@dataclass
class Classification:
    event_type: str
    subtype: str
    severity: int
    private_person: bool
    reason: str
    prompt_version: str = EVENT_LABEL_VERSION

    def drop_reason(self, cfg: EventsConfig) -> str | None:
        rules = cfg.raw["classification"]
        if rules["drop_private_person"] and self.private_person:
            return "private_person"
        if self.event_type in rules["drop_types"]:
            return "not_a_disruption"
        return None


def classify_report(llm: LlmClient, title: str, text: str = "") -> Classification | None:
    """The model's label for the headline and lead, or None when the model could not produce a valid one."""
    try:
        completion = llm.complete(event_label_prompt(title, text[:LEAD_CHARS]), EventLabel, max_tokens=260)
    except LlmError:
        return None
    label: EventLabel = completion.parsed  # type: ignore[assignment]
    return Classification(
        label.event_type, label.subtype, label.severity, label.subject_is_named_private_person, label.reason
    )
