"""Turn human date/time input ("friday 8pm", "2026-11-01 20:00", "<t:1793577600:F>") into aware datetimes."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import dateparser

DISCORD_TS = re.compile(r"<t:(\d+)(?::\w)?>")


def parse_when(text: str, tz_name: str = "UTC", now: datetime | None = None) -> datetime | None:
    text = text.strip()
    if m := DISCORD_TS.fullmatch(text):
        return datetime.fromtimestamp(int(m.group(1)), timezone.utc)
    if text.isdigit() and len(text) >= 9:
        return datetime.fromtimestamp(int(text), timezone.utc)
    settings = {
        "TIMEZONE": tz_name,
        "TO_TIMEZONE": "UTC",
        "RETURN_AS_TIMEZONE_AWARE": True,
        "PREFER_DATES_FROM": "future",
        "PREFER_DAY_OF_MONTH": "first",
    }
    if now:
        settings["RELATIVE_BASE"] = now.astimezone(ZoneInfo(tz_name)).replace(tzinfo=None)
    return dateparser.parse(text, settings=settings)
