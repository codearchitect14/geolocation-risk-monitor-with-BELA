"""Versioned prompts. The version is stored with every decision that used the model."""

from __future__ import annotations

from meridian.llm.client import wrap_data

EVENT_LABEL_VERSION = "event_label_v2"
ADJUDICATE_VERSION = "adjudicate_v1"

EVENT_TYPE_GUIDE = """Event types:
- industrial_accident: fire, explosion, chemical or oil spill, collapse at a plant, refinery, warehouse, mine, or site
- natural_hazard: flood, storm, hurricane, typhoon, earthquake, wildfire, heat wave, volcanic activity, landslide
- transport_disruption: closure or suspension of a port, airport, road, bridge, or railway; derailment or crash; cancelled flights
- labor_action: strike, walkout, work stoppage, picket
- civil_unrest: protest, riot, blockade by demonstrators, political unrest
- security_incident: attack, bombing, shooting, kidnapping, piracy, cyber attack on infrastructure
- infrastructure_outage: power, telecom, internet, or water outage
- health_outbreak: disease outbreak or epidemic
- other: a real disruption that fits none of the above
- none: not a disruption (sports, opinion, entertainment, routine crime about one person, history, business results)
Subtype: the specific kind (fire, explosion, spill, collapse, flood, storm, earthquake, wildfire, heat, volcanic, landslide, port_closure, airport_closure, road_closure, rail_closure, accident, strike, protest, riot, attack, power_outage, telecom_outage, water_outage, outbreak, other). Use other when none fits.
Severity: 1 minor and local, 2 moderate with closures of hours or limited damage, 3 major with significant damage, injuries, or closures of a day or more, 4 severe with widespread damage, multiple deaths, or loss of a major facility or route.
subject_is_named_private_person: true when the report is about a crime or incident whose subject is a named private individual."""


def event_label_prompt(title: str, lead: str = "") -> str:
    body = title if not lead else f"{title}\n{lead}"
    return f"{EVENT_TYPE_GUIDE}\n\nLabel the report below. Give a short reason first.\n{wrap_data(body)}"


def adjudicate_prompt(sentence: str, mention: str, candidates: list[str], hints: str) -> str:
    listing = "\n".join(f"{i}: {c}" for i, c in enumerate(candidates))
    return (
        f'Decide which place the name "{mention}" refers to in the report. Choose the candidate that best fits the '
        "context, or null if none fits (for example if the name is not used as a place). Give a short reason first.\n"
        f"{wrap_data(sentence)}\nContext hints: {hints}\nCandidates:\n{listing}"
    )
