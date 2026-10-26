"""Bot setup, configuration and helpers shared by every cog."""

from __future__ import annotations

import difflib
import logging
import os
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from .db import Database
from .metadata import MetadataError, Resolver
from .models import Item, utcnow

log = logging.getLogger(__name__)

COGS = (
    "filmvale.cogs.watchlist",
    "filmvale.cogs.autoadd",
    "filmvale.cogs.polls",
    "filmvale.cogs.events",
    "filmvale.cogs.transfer",
    "filmvale.cogs.settings",
    "filmvale.cogs.about",
    "filmvale.cogs.refresh",
)


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader so there's no extra dependency."""
    file = Path(path)
    if not file.exists():
        return
    for line in file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


class FilmvaleBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # needed to read links in auto-add channels
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.db = Database(os.environ.get("DATABASE_PATH", "filmvale.db"))
        self.resolver = Resolver(os.environ.get("TMDB_API_KEY"), os.environ.get("YOUTUBE_API_KEY"))
        self.autoadd_channels: set[int] = set()
        self.dev_guild_id = int(os.environ["DEV_GUILD_ID"]) if os.environ.get("DEV_GUILD_ID") else None

    async def setup_hook(self) -> None:
        await self.db.connect()
        await self.resolver.start()
        self.autoadd_channels = await self.db.autoadd_channels()
        for cog in COGS:
            await self.load_extension(cog)
        if self.dev_guild_id:
            guild = discord.Object(self.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands to dev guild %s", len(synced), self.dev_guild_id)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global commands (may take a few minutes to appear)", len(synced))
        if not self.resolver.has_tmdb:
            log.warning("TMDB_API_KEY not set — movie/TV metadata and title search are disabled.")

    async def close(self) -> None:
        await self.resolver.close()
        await self.db.close()
        await super().close()

    async def on_ready(self) -> None:
        log.info("Logged in as %s (%s) in %d servers", self.user, self.user.id, len(self.guilds))

    # ── shared helpers ───────────────────────────────────────────────────

    async def add_to_watchlist(
        self, item: Item, guild_id: int, user: discord.abc.User, tags: list[str] | None = None
    ) -> tuple[Item, bool]:
        """Insert ``item``; returns (item, created). Existing duplicates are returned untouched."""
        item.guild_id = guild_id
        existing = await self.db.find_duplicate(item)
        if existing:
            return existing, False
        item.added_by_id = user.id
        item.added_by_name = user.display_name
        item.added_at = utcnow()
        item.tags = sorted(set(item.tags) | set(tags or []), key=str.lower)
        return await self.db.add_item(item), True

    async def resolve_item(self, guild_id: int, value: str, *, watched: bool | None = None) -> Item | None:
        """Turn an autocomplete value (an id) or free text into a stored item."""
        if value.isdigit() and (item := await self.db.get_item(guild_id, int(value))):
            return item
        matches = await self.db.search_items(guild_id, value, watched=watched, limit=5)
        if matches:
            return matches[0]
        everything = await self.db.list_items(guild_id, watched=watched)
        by_title = {i.title.lower(): i for i in everything}
        close = difflib.get_close_matches(value.lower(), by_title, n=1, cutoff=0.6)
        return by_title[close[0]] if close else None

    async def lookup_link(self, link) -> Item:
        try:
            return await self.resolver.resolve(link)
        except MetadataError:
            raise
        except Exception as e:  # never let a flaky API crash a command
            log.exception("Metadata lookup failed for %s", link)
            raise MetadataError("Something went wrong fetching metadata for that link.") from e


def item_autocomplete(watched: bool | None = None):
    """Factory for an autocomplete callback over watchlist titles."""

    async def callback(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        bot: FilmvaleBot = interaction.client
        items = await bot.db.search_items(interaction.guild_id, current, watched=watched, limit=25)
        return [
            app_commands.Choice(
                name=f"{'✅ ' if i.watched else ''}{i.emoji} {i.display_title}"[:100], value=str(i.id)
            )
            for i in items
        ]

    return callback


async def tag_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    bot: FilmvaleBot = interaction.client
    # Support comma-separated input by completing only the last tag.
    head, _, last = current.rpartition(",")
    prefix = f"{head}," if head else ""
    tags = await bot.db.all_tags(interaction.guild_id)
    return [
        app_commands.Choice(name=f"{prefix}{t}"[:100], value=f"{prefix}{t}"[:100])
        for t in tags if last.strip().lower() in t.lower()
    ][:25]


def parse_tags(text: str | None) -> list[str]:
    return sorted({t.strip() for t in (text or "").split(",") if t.strip()}, key=str.lower)


KIND_CHOICES = [
    app_commands.Choice(name="Movie", value="movie"),
    app_commands.Choice(name="Series / TV show", value="series"),
    app_commands.Choice(name="YouTube", value="youtube"),
    app_commands.Choice(name="Other", value="other"),
]
