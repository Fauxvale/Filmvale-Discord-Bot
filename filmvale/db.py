"""SQLite persistence for watchlist items and per-server settings."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime

import aiosqlite

from .models import Item, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id      INTEGER NOT NULL,
    kind          TEXT    NOT NULL,
    title         TEXT    NOT NULL,
    year          INTEGER,
    release_date  TEXT,
    runtime       INTEGER,
    seasons       INTEGER,
    episodes      INTEGER,
    overview      TEXT,
    poster_url    TEXT,
    rating        REAL,
    genres        TEXT    NOT NULL DEFAULT '[]',
    creator       TEXT,
    url           TEXT,
    imdb_id       TEXT,
    tmdb_id       INTEGER,
    tvdb_id       INTEGER,
    youtube_id    TEXT,
    tags          TEXT    NOT NULL DEFAULT '[]',
    added_by_id   INTEGER,
    added_by_name TEXT,
    added_at      TEXT    NOT NULL,
    watched       INTEGER NOT NULL DEFAULT 0,
    watched_at    TEXT,
    event_id      INTEGER,
    metadata_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_guild ON items (guild_id, watched);

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id         INTEGER PRIMARY KEY,
    timezone         TEXT NOT NULL DEFAULT 'UTC',
    event_channel_id INTEGER
);

CREATE TABLE IF NOT EXISTS autoadd_channels (
    guild_id   INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);
"""

_COLUMNS = (
    "guild_id", "kind", "title", "year", "release_date", "runtime", "seasons", "episodes",
    "overview", "poster_url", "rating", "genres", "creator", "url", "imdb_id", "tmdb_id",
    "tvdb_id", "youtube_id", "tags", "added_by_id", "added_by_name", "added_at", "watched",
    "watched_at", "event_id", "metadata_at",
)

# Columns added after the first release, applied to existing databases on startup.
_MIGRATIONS = {"metadata_at": "ALTER TABLE items ADD COLUMN metadata_at TEXT"}


@dataclass
class GuildSettings:
    guild_id: int
    timezone: str = "UTC"
    event_channel_id: int | None = None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _row_to_item(row: aiosqlite.Row) -> Item:
    return Item(
        id=row["id"],
        guild_id=row["guild_id"],
        kind=row["kind"],
        title=row["title"],
        year=row["year"],
        release_date=row["release_date"],
        runtime=row["runtime"],
        seasons=row["seasons"],
        episodes=row["episodes"],
        overview=row["overview"],
        poster_url=row["poster_url"],
        rating=row["rating"],
        genres=json.loads(row["genres"] or "[]"),
        creator=row["creator"],
        url=row["url"],
        imdb_id=row["imdb_id"],
        tmdb_id=row["tmdb_id"],
        tvdb_id=row["tvdb_id"],
        youtube_id=row["youtube_id"],
        tags=json.loads(row["tags"] or "[]"),
        added_by_id=row["added_by_id"],
        added_by_name=row["added_by_name"],
        added_at=_dt(row["added_at"]),
        watched=bool(row["watched"]),
        watched_at=_dt(row["watched_at"]),
        event_id=row["event_id"],
        metadata_at=_dt(row["metadata_at"]),
    )


def _item_values(item: Item) -> tuple:
    return (
        item.guild_id, item.kind, item.title, item.year, item.release_date, item.runtime,
        item.seasons, item.episodes, item.overview, item.poster_url, item.rating,
        json.dumps(item.genres), item.creator, item.url, item.imdb_id, item.tmdb_id,
        item.tvdb_id, item.youtube_id, json.dumps(item.tags), item.added_by_id,
        item.added_by_name, (item.added_at or utcnow()).isoformat(), int(item.watched),
        item.watched_at.isoformat() if item.watched_at else None, item.event_id,
        item.metadata_at.isoformat() if item.metadata_at else None,
    )


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        cur = await self.conn.execute("PRAGMA table_info(items)")
        existing = {r["name"] for r in await cur.fetchall()}
        for column, sql in _MIGRATIONS.items():
            if column not in existing:
                await self.conn.execute(sql)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    # ── items ────────────────────────────────────────────────────────────

    async def add_item(self, item: Item) -> Item:
        placeholders = ", ".join("?" for _ in _COLUMNS)
        cur = await self.conn.execute(
            f"INSERT INTO items ({', '.join(_COLUMNS)}) VALUES ({placeholders})", _item_values(item)
        )
        await self.conn.commit()
        return await self.get_item(item.guild_id, cur.lastrowid)

    async def add_items(self, items: list[Item]) -> int:
        placeholders = ", ".join("?" for _ in _COLUMNS)
        await self.conn.executemany(
            f"INSERT INTO items ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
            [_item_values(i) for i in items],
        )
        await self.conn.commit()
        return len(items)

    async def update_item(self, item: Item) -> None:
        assignments = ", ".join(f"{c} = ?" for c in _COLUMNS)
        await self.conn.execute(
            f"UPDATE items SET {assignments} WHERE id = ? AND guild_id = ?",
            (*_item_values(item), item.id, item.guild_id),
        )
        await self.conn.commit()

    async def get_item(self, guild_id: int, item_id: int) -> Item | None:
        cur = await self.conn.execute(
            "SELECT * FROM items WHERE guild_id = ? AND id = ?", (guild_id, item_id)
        )
        row = await cur.fetchone()
        return _row_to_item(row) if row else None

    async def delete_item(self, guild_id: int, item_id: int) -> None:
        await self.conn.execute("DELETE FROM items WHERE guild_id = ? AND id = ?", (guild_id, item_id))
        await self.conn.commit()

    async def clear_items(self, guild_id: int) -> None:
        await self.conn.execute("DELETE FROM items WHERE guild_id = ?", (guild_id,))
        await self.conn.commit()

    async def list_items(
        self,
        guild_id: int,
        *,
        kind: str | None = None,
        watched: bool | None = False,
        tag: str | None = None,
        sort: str = "added",
    ) -> list[Item]:
        order = {
            "added": "added_at DESC",
            "oldest": "added_at ASC",
            "title": "title COLLATE NOCASE ASC",
            "release": "COALESCE(release_date, year) DESC",
            "runtime": "runtime IS NULL, runtime ASC",
            "rating": "rating IS NULL, rating DESC",
        }.get(sort, "added_at DESC")
        sql = "SELECT * FROM items WHERE guild_id = ?"
        params: list = [guild_id]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if watched is not None:
            sql += " AND watched = ?"
            params.append(int(watched))
        cur = await self.conn.execute(f"{sql} ORDER BY {order}", params)
        items = [_row_to_item(r) for r in await cur.fetchall()]
        if tag:
            wanted = tag.lower()
            items = [i for i in items if wanted in (t.lower() for t in i.tags)]
        return items

    async def random_items(self, guild_id: int, count: int, **filters) -> list[Item]:
        pool = await self.list_items(guild_id, **filters)
        return random.sample(pool, min(count, len(pool)))

    async def search_items(
        self, guild_id: int, text: str, *, watched: bool | None = None, limit: int = 25
    ) -> list[Item]:
        sql = "SELECT * FROM items WHERE guild_id = ? AND title LIKE ?"
        params: list = [guild_id, f"%{text}%"]
        if watched is not None:
            sql += " AND watched = ?"
            params.append(int(watched))
        sql += " ORDER BY watched ASC, title COLLATE NOCASE LIMIT ?"
        params.append(limit)
        cur = await self.conn.execute(sql, params)
        return [_row_to_item(r) for r in await cur.fetchall()]

    async def find_duplicate(self, item: Item) -> Item | None:
        """Find an existing entry that refers to the same media as ``item``."""
        checks = []
        if item.tmdb_id:
            checks.append(("tmdb_id = ? AND kind = ?", (item.tmdb_id, item.kind)))
        if item.imdb_id:
            checks.append(("imdb_id = ?", (item.imdb_id,)))
        if item.tvdb_id:
            checks.append(("tvdb_id = ? AND kind = ?", (item.tvdb_id, item.kind)))
        if item.youtube_id:
            checks.append(("youtube_id = ?", (item.youtube_id,)))
        if item.url:
            checks.append(("url = ?", (item.url,)))
        if not checks:
            checks.append((
                "title = ? COLLATE NOCASE AND kind = ? AND (year IS ? OR year IS NULL OR ? IS NULL)",
                (item.title, item.kind, item.year, item.year),
            ))
        for clause, params in checks:
            cur = await self.conn.execute(
                f"SELECT * FROM items WHERE guild_id = ? AND {clause} LIMIT 1", (item.guild_id, *params)
            )
            row = await cur.fetchone()
            if row:
                return _row_to_item(row)
        return None

    async def stale_tmdb_items(self, older_than: datetime, limit: int) -> list[Item]:
        """Entries (in any server) whose TMDB data was fetched before ``older_than``, oldest first."""
        cur = await self.conn.execute(
            "SELECT * FROM items WHERE metadata_at IS NOT NULL AND metadata_at < ? "
            "ORDER BY metadata_at LIMIT ?",
            (older_than.isoformat(), limit),
        )
        return [_row_to_item(r) for r in await cur.fetchall()]

    async def all_tags(self, guild_id: int) -> list[str]:
        cur = await self.conn.execute("SELECT tags FROM items WHERE guild_id = ?", (guild_id,))
        tags: dict[str, str] = {}
        for row in await cur.fetchall():
            for t in json.loads(row["tags"] or "[]"):
                tags.setdefault(t.lower(), t)
        return sorted(tags.values(), key=str.lower)

    # ── settings ─────────────────────────────────────────────────────────

    async def get_settings(self, guild_id: int) -> GuildSettings:
        cur = await self.conn.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
        row = await cur.fetchone()
        if not row:
            return GuildSettings(guild_id)
        return GuildSettings(guild_id, row["timezone"], row["event_channel_id"])

    async def save_settings(self, s: GuildSettings) -> None:
        await self.conn.execute(
            "INSERT INTO guild_settings (guild_id, timezone, event_channel_id) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET timezone = excluded.timezone, "
            "event_channel_id = excluded.event_channel_id",
            (s.guild_id, s.timezone, s.event_channel_id),
        )
        await self.conn.commit()

    async def autoadd_channels(self) -> set[int]:
        cur = await self.conn.execute("SELECT channel_id FROM autoadd_channels")
        return {r["channel_id"] for r in await cur.fetchall()}

    async def guild_autoadd_channels(self, guild_id: int) -> list[int]:
        cur = await self.conn.execute(
            "SELECT channel_id FROM autoadd_channels WHERE guild_id = ?", (guild_id,)
        )
        return [r["channel_id"] for r in await cur.fetchall()]

    async def set_autoadd(self, guild_id: int, channel_id: int, enabled: bool) -> None:
        if enabled:
            await self.conn.execute(
                "INSERT OR IGNORE INTO autoadd_channels VALUES (?, ?)", (guild_id, channel_id)
            )
        else:
            await self.conn.execute(
                "DELETE FROM autoadd_channels WHERE guild_id = ? AND channel_id = ?",
                (guild_id, channel_id),
            )
        await self.conn.commit()
