"""Keep cached TMDB data younger than TMDB's 6-month caching limit.

Entries are re-fetched once their TMDB data is ~5 months old. If TMDB no longer has
the title — or no TMDB key is configured — the cached TMDB fields are purged once
they pass 6 months, leaving the user's own data (title, tags, who added it, etc.).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import aiohttp
from discord.ext import commands, tasks

from ..bot import FilmvaleBot
from ..metadata import MetadataError, NotFoundError
from ..models import TMDB_FIELDS, Item, utcnow

log = logging.getLogger(__name__)

REFRESH_AFTER = timedelta(days=150)
MAX_AGE = timedelta(days=180)  # TMDB API terms §1.C
BATCH = 200

# Kept on purge: the title/year identify the entry, and the ids may come from the user's own link.
PURGE_FIELDS = tuple(f for f in TMDB_FIELDS if f not in ("title", "year", "imdb_id", "tvdb_id"))


def purge(item: Item) -> None:
    for name in PURGE_FIELDS:
        setattr(item, name, [] if name == "genres" else None)
    item.metadata_at = None


class Refresh(commands.Cog):
    def __init__(self, bot: FilmvaleBot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.loop.start()

    async def cog_unload(self) -> None:
        self.loop.cancel()

    @tasks.loop(hours=6)
    async def loop(self) -> None:
        refreshed = purged = 0
        if self.bot.resolver.has_tmdb:
            stale = await self.bot.db.stale_tmdb_items(utcnow() - REFRESH_AFTER, BATCH)
            results = await asyncio.gather(*(self._refresh(item) for item in stale))
            refreshed, purged = results.count("refreshed"), results.count("purged")
        else:
            for item in await self.bot.db.stale_tmdb_items(utcnow() - MAX_AGE, BATCH):
                purge(item)
                await self.bot.db.update_item(item)
                purged += 1
        if refreshed or purged:
            log.info("TMDB cache upkeep: refreshed %d, purged %d", refreshed, purged)

    @loop.before_loop
    async def before_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _refresh(self, item: Item) -> str:
        try:
            if not item.tmdb_id:
                raise NotFoundError("no TMDB id")
            fresh = await self.bot.resolver.tmdb_details(item.tmdb_id, item.kind)
        except NotFoundError:
            purge(item)
            await self.bot.db.update_item(item)
            return "purged"
        except (MetadataError, aiohttp.ClientError, asyncio.TimeoutError) as e:
            # Temporary failure: try again next run, but never keep data past the limit.
            if item.metadata_at and item.metadata_at < utcnow() - MAX_AGE:
                purge(item)
                await self.bot.db.update_item(item)
                return "purged"
            log.info("TMDB refresh failed for #%s %s: %s", item.id, item.title, e)
            return "failed"
        for name in TMDB_FIELDS:
            value = getattr(fresh, name)
            if name in ("title", "imdb_id", "tvdb_id") and not value:
                continue
            setattr(item, name, value)
        item.metadata_at = fresh.metadata_at
        await self.bot.db.update_item(item)
        return "refreshed"


async def setup(bot: FilmvaleBot):
    await bot.add_cog(Refresh(bot))
