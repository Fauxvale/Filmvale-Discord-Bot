"""Export a watchlist as human-readable Markdown/text or a lossless JSON backup."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime

from .models import KIND_EMOJI, KINDS, Item, utcnow

SECTION_NAMES = {"movie": "MOVIES", "series": "SERIES", "youtube": "YOUTUBE", "other": "OTHER"}
MD_SECTION_NAMES = {"movie": "Movies", "series": "Series", "youtube": "YouTube", "other": "Other"}
TMDB_NOTICE = "Filmvale uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB."


def _summary(items: list[Item]) -> str:
    unwatched = sum(not i.watched for i in items)
    return (
        f"Exported {utcnow():%Y-%m-%d %H:%M} UTC · {len(items)} items "
        f"({unwatched} to watch, {len(items) - unwatched} watched)"
    )


def _groups(items: list[Item]):
    for kind in KINDS:
        group = sorted((i for i in items if i.kind == kind), key=lambda i: (i.watched, i.title.lower()))
        if group:
            yield kind, group


def _details(item: Item) -> list[str]:
    """The detail lines shown under each entry, shared by the text and Markdown exports."""
    lines = []
    facts = []
    if item.runtime_text:
        facts.append(f"Runtime: {item.runtime_text}")
    if item.release_date:
        facts.append(f"Released: {item.release_date}")
    if item.rating:
        facts.append(f"Rating: {item.rating}/10")
    if item.creator:
        facts.append(f"{'Channel' if item.kind == 'youtube' else 'By'}: {item.creator}")
    if facts:
        lines.append(" · ".join(facts))
    bits = []
    if item.genres:
        bits.append("Genres: " + ", ".join(item.genres))
    if item.tags:
        bits.append("Tags: " + ", ".join(item.tags))
    if bits:
        lines.append(" · ".join(bits))
    who = item.added_by_name or (f"user {item.added_by_id}" if item.added_by_id else "unknown")
    added = f"Added by {who}"
    if item.added_at:
        added += f" on {item.added_at:%Y-%m-%d}"
    if item.watched and item.watched_at:
        added += f" · watched {item.watched_at:%Y-%m-%d}"
    lines.append(added)
    return lines


def to_text(items: list[Item], server_name: str) -> str:
    lines = [
        f"FILMVALE WATCHLIST — {server_name}",
        _summary(items),
        "[ ] = not watched yet   [x] = watched",
        "",
    ]
    if any(i.metadata_at for i in items):
        lines[3:3] = [
            "Movie & TV data from TMDB (https://www.themoviedb.org). Filmvale uses TMDB and the",
            "TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB.",
        ]
    for kind, group in _groups(items):
        lines.append(f"== {SECTION_NAMES[kind]} ({len(group)}) ==")
        lines.append("")
        for n, item in enumerate(group, 1):
            lines.append(f"{n}. [{'x' if item.watched else ' '}] {item.display_title}")
            lines.extend("    " + d for d in _details(item))
            if item.link:
                lines.append("    " + item.link)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>#|~])")


def md_escape(text: str) -> str:
    return _MD_SPECIAL.sub(r"\\\1", text)


def to_markdown(items: list[Item], server_name: str) -> str:
    lines = [f"# Filmvale Watchlist — {md_escape(server_name)}", "", f"*{_summary(items)}*", ""]
    if any(i.metadata_at for i in items):
        lines += [f"> Movie & TV data from [TMDB](https://www.themoviedb.org). {TMDB_NOTICE}", ""]
    for kind, group in _groups(items):
        lines += [f"## {KIND_EMOJI[kind]} {MD_SECTION_NAMES[kind]} ({len(group)})", ""]
        for item in group:
            title = md_escape(item.title)
            if item.link:
                title = f"[{title}](<{item.link}>)"
            year = f" ({item.year})" if item.year and str(item.year) not in item.title else ""
            lines.append(f"- [{'x' if item.watched else ' '}] **{title}**{year}")
            lines.extend("    - " + md_escape(d) for d in _details(item))
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
