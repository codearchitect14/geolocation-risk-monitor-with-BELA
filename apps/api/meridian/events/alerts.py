"""Alert creation and updates from exposures.

An alert exists once per tenant, event, and asset. A later exposure for the same pair updates the alert only when the level
rises or the score rises by at least alerts.update_score_delta; a change that is only detail changes nothing. Alerts that were
dismissed or resolved reopen only if the level climbs by alerts.reopen_after_levels steps. Assets inside a maintenance window
get no alert. Watch zones that the event intersects raise a zone alert (one per tenant and event).
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from typing import Any

import psycopg

from meridian.events import exposure as exposure_module
from meridian.events.config import LEVELS, EventsConfig


@dataclass
class AlertResult:
    created: int = 0
    updated: int = 0
    reopened: int = 0
    suppressed_maintenance: int = 0
    unchanged: int = 0
    zone_alerts: int = 0
    alert_ids: list[str] = field(default_factory=list)

    def merge(self, other: AlertResult) -> None:
        for name in ("created", "updated", "reopened", "suppressed_maintenance", "unchanged", "zone_alerts"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.alert_ids += other.alert_ids


def level_rank(level: str) -> int:
    return LEVELS.index(level)


def in_maintenance(windows: list[dict[str, str]], now: dt.datetime) -> bool:
    for window in windows or []:
        try:
            start = dt.datetime.fromisoformat(window["start"].replace("Z", "+00:00"))
            end = dt.datetime.fromisoformat(window["end"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if start <= now <= end:
            return True
    return False


def in_quiet_hours(quiet: dict[str, str], now: dt.datetime) -> bool:
    """quiet_hours = {"start": "22:00", "end": "06:00"} in UTC; a window may cross midnight."""
    if not quiet or "start" not in quiet or "end" not in quiet:
        return False
    current = now.strftime("%H:%M")
    start, end = quiet["start"], quiet["end"]
    return start <= current < end if start <= end else (current >= start or current < end)


def rule_matches(
    rule: dict[str, Any], event_type: str, subtype: str | None, severity: int, level: str, asset_groups: set[str]
) -> bool:
    types = rule.get("event_types") or []
    if types and event_type not in types and (subtype or "") not in types:
        return False
    if severity < int(rule.get("min_severity", 1)) or level_rank(level) < level_rank(rule.get("min_level", "medium")):
        return False
    groups = {str(g) for g in rule.get("asset_group_ids") or []}
    return not groups or bool(groups & asset_groups)


def tenant_rules(
    conn: psycopg.Connection[Any], cfg: EventsConfig, tenant_ids: list[str]
) -> dict[str, list[dict[str, Any]]]:
    rules: dict[str, list[dict[str, Any]]] = {t: [] for t in tenant_ids}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT tenant_id, id, event_types, min_severity, min_level, asset_group_ids, quiet_hours
                 FROM alert_rules WHERE enabled AND tenant_id = ANY(%s::uuid[])""",
            (tenant_ids,),
        )
        for tenant, rid, types, min_sev, min_level, groups, quiet in cur.fetchall():
            rules[str(tenant)].append(
                {
                    "id": str(rid),
                    "event_types": types,
                    "min_severity": min_sev,
                    "min_level": min_level,
                    "asset_group_ids": [str(g) for g in groups],
                    "quiet_hours": quiet,
                }
            )
    for items in rules.values():
        if not items:
            items.append(
                {
                    "id": None,
                    "event_types": [],
                    "min_severity": 1,
                    "min_level": cfg.raw["alerts"]["default_min_level"],
                    "asset_group_ids": [],
                    "quiet_hours": {},
                }
            )
    return rules


def evaluate_alerts(conn: psycopg.Connection[Any], cfg: EventsConfig, event_id: str, now: dt.datetime) -> AlertResult:
    event = exposure_module.load_event(conn, event_id)
    result = AlertResult()
    if not exposure_module.matchable(event):
        return result
    with conn.cursor() as cur:
        cur.execute(
            """SELECT x.tenant_id, x.asset_id, x.level, x.score, x.components, a.maintenance_windows,
                      COALESCE((SELECT array_agg(m.group_id::text) FROM asset_group_members m WHERE m.asset_id = a.id), '{}')
                 FROM exposures x JOIN assets a ON a.id = x.asset_id WHERE x.event_id = %s""",
            (event_id,),
        )
        rows = cur.fetchall()
    rules = tenant_rules(conn, cfg, sorted({str(r[0]) for r in rows}))
    for tenant, asset_id, level, score, components, windows, groups in rows:
        tenant, asset_id = str(tenant), str(asset_id)
        if in_maintenance(windows, now):
            result.suppressed_maintenance += 1
            continue
        matching = [
            r for r in rules[tenant] if rule_matches(r, event.type, event.subtype, event.severity, level, set(groups))
        ]
        if not matching:
            continue
        rule = matching[0]
        detail = {
            "score": round(float(score), 4),
            "level": level,
            "components": components,
            "quiet_hours": in_quiet_hours(rule["quiet_hours"], now),
        }
        _upsert(conn, cfg, result, tenant, event_id, asset_id, None, rule["id"], level, float(score), detail)
    _zone_alerts(conn, cfg, event, now, result)
    return result


def _upsert(
    conn: psycopg.Connection[Any],
    cfg: EventsConfig,
    result: AlertResult,
    tenant: str,
    event_id: str,
    asset_id: str | None,
    zone_id: str | None,
    rule_id: str | None,
    level: str,
    score: float,
    detail: dict[str, Any],
) -> None:
    alerts_cfg = cfg.raw["alerts"]
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, level, status, last_score FROM alerts
                WHERE tenant_id = %s AND event_id = %s AND asset_id IS NOT DISTINCT FROM %s""",
            (tenant, event_id, asset_id),
        )
        existing = cur.fetchone()
        if existing is None:
            cur.execute(
                """INSERT INTO alerts (tenant_id, event_id, asset_id, zone_id, rule_id, level, last_score) VALUES (%s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (tenant, event_id, asset_id, zone_id, rule_id, level, score),
            )
            alert_id = str(cur.fetchone()[0])  # type: ignore[index]
            cur.execute(
                "INSERT INTO alert_events (alert_id, tenant_id, kind, detail) VALUES (%s, %s, 'created', %s)",
                (alert_id, tenant, json.dumps(detail)),
            )
            result.created += 1
            result.alert_ids.append(alert_id)
            return
        alert_id, old_level, status, old_score = str(existing[0]), existing[1], existing[2], float(existing[3] or 0)
        climbed = level_rank(level) - level_rank(old_level)
        material = climbed > 0 or score >= old_score + float(alerts_cfg["update_score_delta"])
        if status in ("dismissed", "resolved"):
            if climbed >= int(alerts_cfg["reopen_after_levels"]):
                cur.execute(
                    "UPDATE alerts SET status = 'new', level = %s, last_score = %s, updated_at = now() WHERE id = %s",
                    (level, score, alert_id),
                )
                cur.execute(
                    "INSERT INTO alert_events (alert_id, tenant_id, kind, detail) VALUES (%s, %s, 'status_change', %s)",
                    (alert_id, tenant, json.dumps({**detail, "reopened_from": status, "previous_level": old_level})),
                )
                result.reopened += 1
                result.alert_ids.append(alert_id)
            else:
                result.unchanged += 1
            return
        if not material:
            result.unchanged += 1
            return
        cur.execute(
            "UPDATE alerts SET level = %s, last_score = %s, updated_at = now() WHERE id = %s", (level, score, alert_id)
        )
        cur.execute(
            "INSERT INTO alert_events (alert_id, tenant_id, kind, detail) VALUES (%s, %s, 'update', %s)",
            (alert_id, tenant, json.dumps({**detail, "previous_level": old_level, "previous_score": old_score})),
        )
        result.updated += 1
        result.alert_ids.append(alert_id)


def _zone_alerts(
    conn: psycopg.Connection[Any],
    cfg: EventsConfig,
    event: exposure_module.EventRow,
    now: dt.datetime,
    result: AlertResult,
) -> None:
    """One alert per tenant for the first active watch zone that the event intersects and whose rules accept it."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT z.tenant_id, z.id, z.rules FROM watch_zones z
                WHERE z.status = 'active' AND ST_Intersects(z.geom, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
                ORDER BY z.created_at""",
            (event.geometry,),
        )
        zones = cur.fetchall()
    exposure_cfg = cfg.raw["exposure"]
    half_life = cfg.half_life_hours(event.type, event.subtype)
    score = (
        float(exposure_cfg["type_weight"].get(event.type, exposure_cfg["type_weight"]["other"]))
        * float(exposure_cfg["severity_weight"][event.severity])
        * event.location_confidence
        * event.reliability
        * exposure_module.recency_decay(event.last_seen_at, now, half_life)
    )
    level = cfg.level_for(min(score, 1.0))
    done: set[str] = set()
    for tenant, zone_id, rules in zones:
        tenant = str(tenant)
        if tenant in done:
            continue
        rules = rules or {}
        if not rule_matches(
            {
                "event_types": rules.get("event_types"),
                "min_severity": rules.get("min_severity", 1),
                "min_level": rules.get("min_level", cfg.raw["alerts"]["default_min_level"]),
            },
            event.type,
            event.subtype,
            event.severity,
            level,
            set(),
        ):
            continue
        done.add(tenant)
        before = result.created
        _upsert(
            conn,
            cfg,
            result,
            tenant,
            event.id,
            None,
            str(zone_id),
            None,
            level,
            min(score, 1.0),
            {
                "zone_id": str(zone_id),
                "score": round(min(score, 1.0), 4),
                "level": level,
                "quiet_hours": in_quiet_hours(rules.get("quiet_hours") or {}, now),
            },
        )
        result.zone_alerts += result.created - before
