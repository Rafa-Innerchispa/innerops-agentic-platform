"""Zona horaria canónica RalfIA — Guayaquil, Ecuador (America/Guayaquil, GMT-5).

Logs humanos (feed, INBOX, SESSION_LOG, MAPA) usan hora local.
Mongo guarda UTC en ``ts`` (orden) + ``ts_local`` / ``ts_display`` (lectura).
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ_GUAYAQUIL = ZoneInfo("America/Guayaquil")
TZ_LABEL = "GYT (GMT-5)"


def now_local() -> datetime:
    return datetime.now(TZ_GUAYAQUIL)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_utc_iso() -> str:
    return now_utc().isoformat()


def now_local_iso() -> str:
    return now_local().isoformat()


def format_log(dt: datetime | None = None) -> str:
    """Marca para feed, INBOX, SESSION_LOG: ``2026-07-01 14:22 GYT (GMT-5)``."""
    target = dt if dt is not None else now_local()
    if target.tzinfo is None:
        target = target.replace(tzinfo=TZ_GUAYAQUIL)
    else:
        target = target.astimezone(TZ_GUAYAQUIL)
    return target.strftime(f"%Y-%m-%d %H:%M {TZ_LABEL}")


def format_filename(dt: datetime | None = None) -> str:
    """Prefijo de archivos en disco: ``20260701_142200`` (hora Guayaquil)."""
    target = dt if dt is not None else now_local()
    if target.tzinfo is None:
        target = target.replace(tzinfo=TZ_GUAYAQUIL)
    else:
        target = target.astimezone(TZ_GUAYAQUIL)
    return target.strftime("%Y%m%d_%H%M%S")


def to_local_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(TZ_GUAYAQUIL).isoformat()
