"""Core data types shared across the bot."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from datetime import datetime, timezone

KINDS = ("movie", "series", "youtube", "other")

KIND_LABELS = {
    "movie": "Movie",
    "series": "Series",
    "youtube": "YouTube",
    "other": "Other",
}

KIND_EMOJI = {
    "movie": "🎬",
    "series": "📺",
    "youtube": "▶️",
    "other": "📦",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def format_runtime(minutes: int | None) -> str | None:
    if not minutes:
        return None
    hours, mins = divmod(int(minutes), 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    return f"{hours}h" if hours else f"{mins}m"


@dataclass
class Item:
    """A single watchlist entry (movie, series, YouTube video/playlist, or anything else)."""

    title: str
    kind: str = "movie"
    id: int | None = None
    guild_id: int | None = None
    year: int | None = None
    release_date: str | None = None  # ISO date (YYYY-MM-DD) when known
    runtime: int | None = None  # minutes (per-episode for series)
    seasons: int | None = None
    episodes: int | None = None
    overview: str | None = None
    poster_url: str | None = None
    rating: float | None = None  # 0-10
    genres: list[str] = field(default_factory=list)
    creator: str | None = None  # YouTube channel / director, when known
    url: str | None = None
    imdb_id: str | None = None
    tmdb_id: int | None = None
    tvdb_id: int | None = None
    youtube_id: str | None = None
    tags: list[str] = field(default_factory=list)
    added_by_id: int | None = None
    added_by_name: str | None = None
    added_at: datetime | None = None
    watched: bool = False
    watched_at: datetime | None = None
    event_id: int | None = None

    @property
    def display_title(self) -> str:
        if self.year and str(self.year) not in self.title:
            return f"{self.title} ({self.year})"
        return self.title

    @property
    def emoji(self) -> str:
        return KIND_EMOJI.get(self.kind, "📦")

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, "Other")

    @property
    def runtime_text(self) -> str | None:
        text = format_runtime(self.runtime)
        if self.kind == "series":
            parts = []
            if self.seasons:
                parts.append(f"{self.seasons} season{'s' if self.seasons != 1 else ''}")
            if self.episodes:
                parts.append(f"{self.episodes} eps")
            if text:
                parts.append(f"~{text}/ep")
            return " · ".join(parts) or None
        return text

    @property
    def link(self) -> str | None:
        """Best canonical link for the item."""
        if self.url:
            return self.url
        if self.imdb_id:
            return f"https://www.imdb.com/title/{self.imdb_id}/"
        if self.tmdb_id:
            path = "tv" if self.kind == "series" else "movie"
            return f"https://www.themoviedb.org/{path}/{self.tmdb_id}"
        if self.youtube_id:
            return f"https://www.youtube.com/watch?v={self.youtube_id}"
        return None

    def merge_missing(self, other: Item) -> Item:
        """Return a copy where empty fields are filled from ``other`` (metadata enrichment)."""
        updates = {}
        for f in fields(self):
            if f.name in ("id", "guild_id", "tags", "watched", "added_by_id", "added_by_name", "added_at"):
                continue
            mine, theirs = getattr(self, f.name), getattr(other, f.name)
            if (mine is None or mine == [] or mine == "") and theirs not in (None, [], ""):
                updates[f.name] = theirs
        # A resolver knows the real kind better than an import guess.
        if other.kind and other.kind != "other":
            updates["kind"] = other.kind
        return replace(self, **updates)
