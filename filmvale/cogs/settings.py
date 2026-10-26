"""/settings — per-server configuration (admins only by default)."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

import discord
from discord import app_commands
from discord.ext import commands

from ..bot import FilmvaleBot

_TIMEZONES = sorted(available_timezones())


class Settings(commands.Cog):
    settings = app_commands.Group(
        name="settings",
        description="Configure Filmvale for this server.",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )
    autoadd = app_commands.Group(name="autoadd", description="Channels where posted links are auto-added.", parent=settings)

    def __init__(self, bot: FilmvaleBot):
        self.bot = bot

    @settings.command(name="show", description="Show the current settings.")
    async def show(self, interaction: discord.Interaction):
        s = await self.bot.db.get_settings(interaction.guild_id)
        channels = await self.bot.db.guild_autoadd_channels(interaction.guild_id)
        embed = discord.Embed(title="⚙️ Filmvale settings", colour=discord.Colour.blurple())
        embed.add_field(name="Auto-add channels", value=", ".join(f"<#{c}>" for c in channels) or "*none*", inline=False)
        embed.add_field(name="Timezone", value=s.timezone)
        embed.add_field(name="Default event channel", value=f"<#{s.event_channel_id}>" if s.event_channel_id else "*none (external location)*")
        embed.add_field(
            name="Metadata",
            value=f"TMDB: {'✅' if self.bot.resolver.has_tmdb else '❌ (set TMDB_API_KEY)'} · "
                  f"YouTube API: {'✅' if self.bot.resolver.youtube_key else '➖ optional (runtimes)'}",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @autoadd.command(name="add", description="Auto-add media links posted in a channel.")
    async def autoadd_add(self, interaction: discord.Interaction, channel: discord.TextChannel | discord.ForumChannel):
        await self.bot.db.set_autoadd(interaction.guild_id, channel.id, True)
        self.bot.autoadd_channels.add(channel.id)
        perms = channel.permissions_for(interaction.guild.me)
        warn = "" if perms.read_messages and perms.send_messages and perms.add_reactions else \
            "\n⚠️ I'm missing View Channel / Send Messages / Add Reactions there."
        await interaction.response.send_message(
            f"✅ Links posted in {channel.mention} will be added automatically.{warn}", ephemeral=True
        )

    @autoadd.command(name="remove", description="Stop auto-adding links from a channel.")
    async def autoadd_remove(self, interaction: discord.Interaction, channel: discord.TextChannel | discord.ForumChannel):
        await self.bot.db.set_autoadd(interaction.guild_id, channel.id, False)
        self.bot.autoadd_channels.discard(channel.id)
        await interaction.response.send_message(f"Stopped auto-adding in {channel.mention}.", ephemeral=True)

    @settings.command(name="timezone", description="Timezone used to read /schedule times.")
    @app_commands.describe(zone="e.g. America/New_York, Europe/London")
    async def timezone(self, interaction: discord.Interaction, zone: str):
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError):
            await interaction.response.send_message(f"`{zone}` isn't a known timezone.", ephemeral=True)
            return
        s = await self.bot.db.get_settings(interaction.guild_id)
        s.timezone = zone
        await self.bot.db.save_settings(s)
        await interaction.response.send_message(f"🕒 Timezone set to **{zone}**.", ephemeral=True)

    @timezone.autocomplete("zone")
    async def timezone_autocomplete(self, interaction: discord.Interaction, current: str):
        needle = current.lower().replace(" ", "_")
        return [app_commands.Choice(name=z, value=z) for z in _TIMEZONES if needle in z.lower()][:25]

    @settings.command(name="event-channel", description="Default voice channel for /schedule events (omit to clear).")
    async def event_channel(
        self, interaction: discord.Interaction, channel: discord.VoiceChannel | discord.StageChannel | None = None
    ):
        s = await self.bot.db.get_settings(interaction.guild_id)
        s.event_channel_id = channel.id if channel else None
        await self.bot.db.save_settings(s)
        msg = f"Movie nights will default to {channel.mention}." if channel else "Cleared — events default to an external location."
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: FilmvaleBot):
    await bot.add_cog(Settings(bot))
