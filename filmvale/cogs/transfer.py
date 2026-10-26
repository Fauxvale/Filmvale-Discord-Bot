"""/export and /import."""

from __future__ import annotations

import asyncio
import io
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from ..bot import KIND_CHOICES, FilmvaleBot
from ..exporters import to_json, to_text
from ..importers import ImportFormatError, parse_file
from ..metadata import MetadataError, MediaLink
from ..models import KIND_LABELS, Item, utcnow
from ..ui import ConfirmView

log = logging.getLogger(__name__)

MAX_IMPORT_BYTES = 10 * 1024 * 1024


def _safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-").lower() or "server"


class Transfer(commands.Cog):
    def __init__(self, bot: FilmvaleBot):
        self.bot = bot

    # ── /export ──────────────────────────────────────────────────────────

    @app_commands.command(description="Download the watchlist as a readable .txt (or a .json backup).")
    @app_commands.guild_only()
    @app_commands.describe(
        format="txt = human-readable list, json = full backup that can be re-imported",
        status="Which entries to include",
        kind="Only export one type",
    )
    @app_commands.choices(
        format=[
            app_commands.Choice(name="Plain text (.txt)", value="txt"),
            app_commands.Choice(name="JSON backup (.json)", value="json"),
        ],
        status=[
            app_commands.Choice(name="Everything", value="all"),
            app_commands.Choice(name="To watch only", value="unwatched"),
            app_commands.Choice(name="Watched only", value="watched"),
        ],
        kind=KIND_CHOICES,
    )
    async def export(
        self,
        interaction: discord.Interaction,
        format: app_commands.Choice[str] | None = None,
        status: app_commands.Choice[str] | None = None,
        kind: app_commands.Choice[str] | None = None,
    ):
        fmt = format.value if format else "txt"
        watched = {"all": None, "unwatched": False, "watched": True}[status.value if status else "all"]
        items = await self.bot.db.list_items(
            interaction.guild_id, kind=kind.value if kind else None, watched=watched, sort="title"
        )
        if not items:
            await interaction.response.send_message("Nothing to export.", ephemeral=True)
            return
        name = interaction.guild.name
        body = to_text(items, name) if fmt == "txt" else to_json(items, interaction.guild_id)
        filename = f"watchlist-{_safe_filename(name)}-{utcnow():%Y%m%d}.{fmt}"
        await interaction.response.send_message(
            f"📤 Exported **{len(items)}** entries.",
            file=discord.File(io.BytesIO(body.encode("utf-8")), filename=filename),
        )

    # ── /import ──────────────────────────────────────────────────────────

    @app_commands.command(name="import", description="Import a WatchList bot export, IMDb CSV, or text list.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        file="WatchList bot .json/.zip export, IMDb .csv export, this bot's .json/.txt export, or a .txt list",
        mode="merge = add to the current list, replace = wipe the current list first",
        on_conflict="What to do when an entry is already on the list (merge mode)",
        enrich="Fill in missing posters/runtimes/genres from TMDB/YouTube (slower)",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Merge with current list", value="merge"),
            app_commands.Choice(name="Replace current list", value="replace"),
        ],
        on_conflict=[
            app_commands.Choice(name="Skip (keep what's there)", value="skip"),
            app_commands.Choice(name="Update (fill gaps, sync watched status & tags)", value="update"),
        ],
    )
    async def import_(
        self,
        interaction: discord.Interaction,
        file: discord.Attachment,
        mode: app_commands.Choice[str] | None = None,
        on_conflict: app_commands.Choice[str] | None = None,
        enrich: bool = True,
    ):
        mode_value = mode.value if mode else "merge"
        conflict = on_conflict.value if on_conflict else "skip"
        if file.size > MAX_IMPORT_BYTES:
            await interaction.response.send_message("That file is too big (10 MB max).", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        try:
            incoming = parse_file(file.filename, await file.read())
        except (ImportFormatError, ValueError, KeyError) as e:
            await interaction.followup.send(f"⚠️ Couldn't read `{file.filename}`: {e}")
            return
        if not incoming:
            await interaction.followup.send("That file didn't contain any entries.")
            return

        guild_id = interaction.guild_id
        for item in incoming:
            item.guild_id = guild_id
        incoming = self._dedupe_within(incoming)

        new, conflicts = [], []
        if mode_value == "replace":
            new = incoming
        else:
            for item in incoming:
                existing = await self.bot.db.find_duplicate(item)
                (conflicts.append((existing, item)) if existing else new.append(item))

        current_total = len(await self.bot.db.list_items(guild_id, watched=None))
        embed = discord.Embed(title=f"📥 Import preview — {file.filename}", colour=discord.Colour.blurple())
        embed.add_field(name="In file", value=str(len(incoming)))
        embed.add_field(name="Will add", value=str(len(new)))
        if mode_value == "merge":
            embed.add_field(
                name="Already on list",
                value=f"{len(conflicts)} ({'will update' if conflict == 'update' else 'will skip'})",
            )
        else:
            embed.add_field(name="⚠️ Will delete", value=f"{current_total} current entries")
        by_kind = {}
        for item in incoming:
            by_kind[item.kind] = by_kind.get(item.kind, 0) + 1
        embed.add_field(
            name="Types", value=", ".join(f"{KIND_LABELS[k]}: {n}" for k, n in by_kind.items()), inline=False
        )
        watched_count = sum(i.watched for i in incoming)
        embed.add_field(name="Watched", value=f"{watched_count} of {len(incoming)}")
        sample = "\n".join(f"{i.emoji} {i.display_title}" for i in new[:10]) or "*nothing new*"
        if len(new) > 10:
            sample += f"\n… and {len(new) - 10} more"
        embed.add_field(name="New entries", value=sample[:1024], inline=False)
        if enrich and not self.bot.resolver.has_tmdb:
            embed.set_footer(text="TMDB_API_KEY isn't set, so only YouTube entries can be enriched.")

        view = ConfirmView(interaction.user.id, "Replace list" if mode_value == "replace" else "Import",
                           danger=mode_value == "replace")
        view.message = await interaction.followup.send(embed=embed, view=view, wait=True)
        await view.wait()
        if not view.value:
            if view.value is None:
                await view.message.edit(content="Import timed out.", view=None)
            return

        to_process = new + ([imp for _, imp in conflicts] if conflict == "update" else [])
        await view.message.edit(content=f"⏳ Importing {len(to_process)} entries…", embed=None, view=None)

        await self._fill_requesters(interaction.guild, to_process)
        if enrich:
            await self._enrich(to_process, view.message)

        now = utcnow()
        for item in new:
            item.added_at = item.added_at or now
            item.added_by_name = item.added_by_name or "import"
            item.watched_at = item.watched_at or (now if item.watched else None)

        if mode_value == "replace":
            await self.bot.db.clear_items(guild_id)
        await self.bot.db.add_items(new)
        updated = 0
        if conflict == "update":
            for existing, imported in conflicts:
                merged = existing.merge_missing(imported)
                merged.kind = existing.kind
                merged.watched = existing.watched or imported.watched
                merged.watched_at = existing.watched_at or (now if merged.watched else None)
                merged.tags = sorted({*existing.tags, *imported.tags}, key=str.lower)
                await self.bot.db.update_item(merged)
                updated += 1

        summary = f"✅ Imported **{len(new)}** new entries"
        if updated:
            summary += f", updated **{updated}**"
        elif conflicts:
            summary += f", skipped **{len(conflicts)}** already on the list"
        await view.message.edit(content=summary + ". Browse them with `/list`.")

    @staticmethod
    def _dedupe_within(items: list[Item]) -> list[Item]:
        seen, out = set(), []
        for item in items:
            key = (
                ("tmdb", item.kind, item.tmdb_id) if item.tmdb_id else
                ("imdb", item.imdb_id) if item.imdb_id else
                ("yt", item.youtube_id) if item.youtube_id else
                ("url", item.url) if item.url else
                ("title", item.kind, item.title.lower(), item.year)
            )
            if key not in seen:
                seen.add(key)
                out.append(item)
        return out

    async def _fill_requesters(self, guild: discord.Guild, items: list[Item]) -> None:
        """Imported requesters are bare user ids; look up display names for exports."""
        names: dict[int, str | None] = {}
        for user_id in {i.added_by_id for i in items if i.added_by_id and not i.added_by_name}:
            member = guild.get_member(user_id)
            if not member:
                try:
                    member = await guild.fetch_member(user_id)
                except discord.HTTPException:
                    member = None
            names[user_id] = member.display_name if member else None
        for item in items:
            if item.added_by_id and not item.added_by_name:
                item.added_by_name = names.get(item.added_by_id)

    async def _enrich(self, items: list[Item], status: discord.Message) -> None:
        resolver = self.bot.resolver
        done = 0
        lock = asyncio.Lock()

        async def one(item: Item) -> None:
            nonlocal done
            try:
                found = None
                if resolver.has_tmdb and item.kind in ("movie", "series"):
                    if item.tmdb_id:
                        found = await resolver.tmdb_details(item.tmdb_id, item.kind)
                    elif item.imdb_id:
                        found = await resolver.tmdb_find(item.imdb_id, "imdb_id")
                    elif not item.url:
                        found = await resolver.best_match(item.title, item.kind, item.year)
                elif item.kind == "youtube" and item.youtube_id and (not item.creator or not item.poster_url):
                    source = "youtube_playlist" if "playlist" in (item.url or "") else "youtube_video"
                    found = await resolver.youtube(MediaLink(source, item.youtube_id, item.url or ""))
                if found:
                    merged = item.merge_missing(found)
                    # Prefer TMDB's consistently-sized posters over scraped ones.
                    if found.poster_url and found.kind != "youtube":
                        merged.poster_url = found.poster_url
                    vars(item).update(vars(merged))  # in place: callers hold references to these items
            except (MetadataError, asyncio.TimeoutError) as e:
                log.info("Enrich skipped for %s: %s", item.title, e)
            except Exception:
                log.exception("Enrich failed for %s", item.title)
            async with lock:
                done += 1
                if done % 15 == 0:
                    try:
                        await status.edit(content=f"⏳ Fetching metadata… {done}/{len(items)}")
                    except discord.HTTPException:
                        pass

        await asyncio.gather(*(one(i) for i in items))


async def setup(bot: FilmvaleBot):
    await bot.add_cog(Transfer(bot))
