"""Export a watchlist as human-readable text or a lossless JSON backup."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime

from .models import KINDS, Item, utcnow

SECTION_NAMES = {"movie": "MOVIES", "series": "SERIES", "youtube": "YOUTUBE", "other": "OTHER"}


def to_text(items: list[Item], server_name: str) -> str:
    unwatched = sum(not i.watched for i in items)
    lines = [
        f"FILMVALE WATCHLIST — {server_name}",
        f"Exported {utcnow():%Y-%m-%d %H:%M} UTC · {len(items)} items "
        f"({unwatched} to watch, {len(items) - unwatched} watched)",
        "[ ] = not watched yet   [x] = watched",
        "",
    ]
    if any(i.metadata_at for i in items):
        lines[3:3] = [
            "Movie & TV data from TMDB (https://www.themoviedb.org). Filmvale uses TMDB and the",
            "TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB.",
        ]
    for kind in KINDS:
        group = [i for i in items if i.kind == kind]
        if not group:
            continue
        group.sort(key=lambda i: (i.watched, i.title.lower()))
        lines.append(f"== {SECTION_NAMES[kind]} ({len(group)}) ==")
        lines.append("")
        for n, item in enumerate(group, 1):
            lines.append(f"{n}. [{'x' if item.watched else ' '}] {item.display_title}")
            facts = []
            if item.runtime_text:
                facts.append(f"Runtime: {item.runtime_text}")
            if item.release_date:
                facts.append(f"Released: {item.release_date}")
            if item.rating:
                facts.append(f"Rating: {item.rating}/10")
            if item.creator:
                facts.append(f"{'Channel' if kind == 'youtube' else 'By'}: {item.creator}")
            if facts:
                lines.append("    " + " · ".join(facts))
            if item.genres or item.tags:
                bits = []
                if item.genres:
                    bits.append("Genres: " + ", ".join(item.genres))
                if item.tags:
                    bits.append("Tags: " + ", ".join(item.tags))
                lines.append("    " + " · ".join(bits))
            who = item.added_by_name or (f"user {item.added_by_id}" if item.added_by_id else "unknown")
            added = f"Added by {who}"
            if item.added_at:
                added += f" on {item.added_at:%Y-%m-%d}"
            if item.watched and item.watched_at:
                added += f" · watched {item.watched_at:%Y-%m-%d}"
            lines.append("    " + added)
            if item.link:
                lines.append("    " + item.link)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def to_json(items: list[Item], guild_id: int) -> str:
    def encode(value):
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError(type(value))

    payload = {
        "format": "filmvale",
        "version": 1,
        "guild_id": guild_id,
        "exported_at": utcnow().isoformat(),
        "items": [asdict(i) for i in items],
    }
    return json.dumps(payload, indent=2, default=encode, ensure_ascii=False)
