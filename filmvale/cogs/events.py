"""/schedule — create a Discord scheduled event for a movie night."""

from __future__ import annotations

import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from ..bot import FilmvaleBot, item_autocomplete
from ..metadata import MetadataError, parse_link
from ..models import Item, utcnow
from ..timeparse import parse_when

log = logging.getLogger(__name__)

DEFAULT_LENGTH = 120  # minutes, when runtime is unknown
BUFFER = 15  # minutes added to runtime for snacks & stragglers


class Events(commands.Cog):
    def __init__(self, bot: FilmvaleBot):
        self.bot = bot

    async def _poster_bytes(self, url: str | None) -> bytes | None:
        if not url:
            return None
        try:
            async with self.bot.resolver.session.get(url) as r:
                if r.status == 200 and r.content_type.startswith("image/"):
                    return await r.read()
        except aiohttp.ClientError:
            pass
        return None

    @app_commands.command(description="Schedule a movie night as a Discord event.")
    @app_commands.guild_only()
    @app_commands.default_permissions(create_events=True)
    @app_commands.checks.bot_has_permissions(create_events=True)
    @app_commands.describe(
        item="Watchlist entry (or paste a link to add & schedule it)",
        when='When it starts: a Discord timestamp like <t:1793386800>, or "friday 8pm", "2026-11-01 20:00"',
        channel="Voice/stage channel to host it in (defaults to the server's event channel)",
        location="Text location instead of a channel (e.g. 'Teleparty', 'Jake's place')",
        length="Event length in minutes (defaults to runtime + 15)",
        title="Custom event name",
    )
    @app_commands.autocomplete(item=item_autocomplete(watched=False))
    async def schedule(
        self,
        interaction: discord.Interaction,
        item: str,
        when: str,
        channel: discord.VoiceChannel | discord.StageChannel | None = None,
        location: str | None = None,
        length: app_commands.Range[int, 10, 1440] | None = None,
        title: str | None = None,
    ):
        await interaction.response.defer(thinking=True)
        settings = await self.bot.db.get_settings(interaction.guild_id)

        target = await self._resolve_target(interaction, item)
        if isinstance(target, str):
            await interaction.followup.send(target)
            return

        start = parse_when(when, settings.timezone)
        if not start:
            await interaction.followup.send(
                f"Couldn't understand `{when}` as a date/time. Try `2026-11-01 20:00` or `friday 8pm`."
            )
            return
        if start <= utcnow() + timedelta(minutes=1):
            await interaction.followup.send(
                f"That's in the past (<t:{int(start.timestamp())}:F>). "
                f"Server timezone is **{settings.timezone}** — change it with `/settings timezone`."
            )
            return

        minutes = length or ((target.runtime + BUFFER) if target.runtime and target.kind != "series" else DEFAULT_LENGTH)
        end = start + timedelta(minutes=minutes)

        if not channel and not location and settings.event_channel_id:
            channel = interaction.guild.get_channel(settings.event_channel_id)

        description = self._description(target)
        kwargs: dict = {
            "name": (title or f"🍿 {target.display_title}")[:100],
            "start_time": start,
            "end_time": end,
            "description": description,
            "privacy_level": discord.PrivacyLevel.guild_only,
        }
        if channel and not location:
            kwargs["entity_type"] = (
                discord.EntityType.stage_instance if isinstance(channel, discord.StageChannel)
                else discord.EntityType.voice
            )
            kwargs["channel"] = channel
        else:
            kwargs["entity_type"] = discord.EntityType.external
            kwargs["location"] = (location or "Movie night")[:100]
        if image := await self._poster_bytes(target.poster_url):
            kwargs["image"] = image

        try:
            event = await interaction.guild.create_scheduled_event(**kwargs, reason=f"Scheduled by {interaction.user}")
        except discord.HTTPException as e:
            if "image" in kwargs and e.status == 400:
                kwargs.pop("image")  # some poster formats are rejected — retry without it
                event = await interaction.guild.create_scheduled_event(**kwargs)
            else:
                raise

        target.event_id = event.id
        await self.bot.db.update_item(target)
        await interaction.followup.send(
            f"📅 **{discord.utils.escape_markdown(target.display_title)}** is scheduled for "
            f"<t:{int(start.timestamp())}:F> (<t:{int(start.timestamp())}:R>).\n{event.url}"
        )

    @schedule.autocomplete("when")
    async def when_autocomplete(self, interaction: discord.Interaction, current: str):
        """Echo back how the time will be read, so mistakes are caught before submitting."""
        if not current.strip():
            return []
        settings = await self.bot.db.get_settings(interaction.guild_id)
        parsed = parse_when(current, settings.timezone)
        if parsed:
            local = parsed.astimezone(ZoneInfo(settings.timezone))
            label = f"📅 {local:%a, %b %d %Y · %I:%M %p %Z}"
            if parsed <= utcnow():
                label += " (in the past!)"
        else:
            label = "❓ Can't read that yet — try <t:1793386800> or friday 8pm"
        return [app_commands.Choice(name=label[:100], value=current[:100])]

    async def _resolve_target(self, interaction: discord.Interaction, value: str) -> Item | str:
        """Find the watchlist item, adding it first if a link was pasted."""
        if link := parse_link(value):
            try:
                found = await self.bot.lookup_link(link)
            except MetadataError as e:
                return f"⚠️ {e}"
            saved, _ = await self.bot.add_to_watchlist(found, interaction.guild_id, interaction.user)
            return saved
        found = await self.bot.resolve_item(interaction.guild_id, value)
        return found or "Couldn't find that on the watchlist — pick from the suggestions or paste a link."

    @staticmethod
    def _description(item: Item) -> str:
        parts = []
        facts = [f for f in (item.kind_label, item.runtime_text, item.release_date, f"⭐ {item.rating}/10" if item.rating else None) if f]
        parts.append(" · ".join(facts))
        if item.overview:
            parts.append(item.overview[:600])
        if item.link:
            parts.append(item.link)
        description = "\n\n".join(parts)
        credit = "\n\nData from TMDB." if item.metadata_at else ""
        return description[: 1000 - len(credit)] + credit

    @schedule.error
    async def schedule_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.BotMissingPermissions):
            msg = "I need the **Create Events** permission to schedule movie nights."
        else:
            log.exception("schedule failed", exc_info=error)
            msg = f"Couldn't create the event: {getattr(error, 'original', error)}"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: FilmvaleBot):
    await bot.add_cog(Events(bot))
