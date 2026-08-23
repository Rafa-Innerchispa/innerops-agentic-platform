"""Hora local RalfIA — carpetas y logs en zona horaria del operador."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

RALFIA_TIMEZONE = os.getenv("RALFIA_TIMEZONE", "America/Guayaquil")


def local_tz() -> ZoneInfo:
    try:
        return ZoneInfo(RALFIA_TIMEZONE)
    except Exception:
        return ZoneInfo("America/Guayaquil")


def now_local() -> datetime:
    return datetime.now(local_tz())


def now_local_iso() -> str:
    return now_local().isoformat()


def local_timestamp(fmt: str = "%Y%m%d_%H%M%S") -> str:
    """Marca de tiempo para carpetas de salida (hora local, no UTC)."""
    return now_local().strftime(fmt)
