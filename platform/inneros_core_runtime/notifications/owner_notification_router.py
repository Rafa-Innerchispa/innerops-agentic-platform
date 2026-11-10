"""Failover policy for *all* InnerOS owner notices, with injected senders.

Production wiring must persist NotificationProgress in an atomic durable outbox.
A provider's 'accepted' result is NOT human delivery, read, or approval.
Nothing in this module authorizes or changes OPS execution state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
import re

CHANNELS = ("push", "whatsapp", "telegram", "email")
KINDS = frozenset({
    "approval", "incident", "report", "task_status", "test_result",
    "service_health", "opportunity", "digest", "other",
})
SEVERITIES = frozenset({"info", "low", "medium", "high", "critical"})
_ID = re.compile(r"[A-Za-z0-9_.:-]{6,120}\Z")


@dataclass(frozen=True)
class Notice:
    event_id: str
    kind: str
    severity: str
    title: str
    task_id: str = ""
    requires_owner_ack: bool = False

    def validate(self) -> None:
        if not _ID.fullmatch(self.event_id):
            raise ValueError("event_id_required")
        if self.kind not in KINDS or self.severity not in SEVERITIES:
            raise ValueError("unsupported_notice_class")
        if not self.title or len(self.title) > 180:
            raise ValueError("bad_notice_title")
        if self.task_id and not re.fullmatch(r"ops_[a-f0-9]{12}", self.task_id):
            raise ValueError("bad_task_id")


@dataclass(frozen=True)
class Preferences:
    # Every event kind is on by default; no opt-out for safety gates.
    channel_enabled: dict[str, bool] = field(
        default_factory=lambda: {channel: True for channel in CHANNELS})
    category_enabled: dict[str, bool] = field(default_factory=dict)
    escalation_seconds: int = 120

    def validate(self) -> None:
        if not 30 <= self.escalation_seconds <= 3600:
            raise ValueError("invalid_escalation_timeout")
        if any(key not in CHANNELS or not isinstance(val, bool)
               for key, val in self.channel_enabled.items()):
            raise ValueError("invalid_channel_preference")
        if any(key not in KINDS or not isinstance(val, bool)
               for key, val in self.category_enabled.items()):
            raise ValueError("invalid_category_preference")

    def eligible(self, event: Notice) -> bool:
        # Disabling routine notification is NOT disabling a task.
        # Security-critical approvals and incidents must not disappear silently.
        return (event.kind in {"approval", "incident"} or
                event.severity == "critical" or
                self.category_enabled.get(event.kind, True))


@dataclass
class NotificationProgress:
    event_id: str
    attempted: list[str] = field(default_factory=list)
    receipts: list[dict[str, Any]] = field(default_factory=list)
    state: str = "pending"  # pending / provider_accepted / awaiting_owner / exhausted / muted / acknowledged
    last_channel: str = ""
    escalation_at: datetime | None = None
    acknowledged_at: datetime | None = None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timezone_aware_datetime_required")
    return value.astimezone(timezone.utc)


def owner_acknowledge(progress: NotificationProgress, when: datetime) -> NotificationProgress:
    """Ack means the owner saw a notice, NOT an approval of task execution."""
    if progress.state not in {"awaiting_owner", "provider_accepted"}:
        raise ValueError("not_acknowledgeable")
    progress.acknowledged_at = _utc(when)
    progress.state = "acknowledged"
    progress.escalation_at = None
    return progress


def route_next(
    event: Notice, progress: NotificationProgress, prefs: Preferences,
    senders: dict[str, Callable[[Notice], dict[str, Any]]],
    *, now: datetime,
) -> NotificationProgress:
    """Attempt ordered transports. On failure immediately attempt the next.

    Critical/approval events advance to another channel if the owner hasn't
    acknowledged by the escalation deadline. A normal report is accepted for
    transport once a provider accepts, without claiming that it was read.
    Caller must persist under a per-event lock/CAS and retry due outbox rows.
    """
    event.validate()
    prefs.validate()
    ts = _utc(now)
    if event.event_id != progress.event_id:
        raise ValueError("event_progress_mismatch")
    if progress.state in {"acknowledged", "muted", "exhausted"}:
        return progress
    urgent = (event.requires_owner_ack or event.kind == "approval" or
              event.severity in {"critical", "high"})
    if progress.state == "provider_accepted" and not urgent:
        return progress
    if progress.state == "awaiting_owner" and progress.escalation_at:
        if ts < _utc(progress.escalation_at):
            return progress
    if not prefs.eligible(event):
        progress.state = "muted"
        return progress

    for channel in CHANNELS:
        if channel in progress.attempted or not prefs.channel_enabled.get(channel, True):
            continue
        progress.attempted.append(channel)
        sender = senders.get(channel)
        try:
            raw = sender(event) if sender is not None else {"ok": False, "reason": "not_configured"}
            result = raw if isinstance(raw, dict) else {"ok": False, "reason": "invalid_result"}
            accepted = bool(result.get("ok"))
            reason = "accepted" if accepted else str(result.get("reason") or "provider_rejected")[:80]
            provider_id = str(result.get("provider_message_id") or "")[:100] if accepted else ""
        except Exception as exc:
            accepted = False
            reason = type(exc).__name__
            provider_id = ""
        # No notification body, credentials, phone or tokens in receipts.
        progress.receipts.append({
            "channel": channel, "accepted": accepted,
            "provider_message_id": provider_id, "result": reason,
            "time": ts.isoformat(),
        })
        progress.last_channel = channel
        if accepted:
            progress.state = "awaiting_owner" if urgent else "provider_accepted"
            progress.escalation_at = (
                ts + timedelta(seconds=prefs.escalation_seconds)
                if urgent else None
            )
            return progress
    progress.state = "exhausted"  # Durable outbox must preserve for manual recovery.
    progress.escalation_at = None
    return progress
