"""Watch configured channels and add any supported media links that get posted."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from ..bot import FilmvaleBot
from ..metadata import MetadataError, find_links
from ..ui import card_embed

log = logging.getLogger(__name__)


class AutoAdd(commands.Cog):
    def __init__(self, bot: FilmvaleBot):
        self.bot = bot

    def _watched_channel(self, message: discord.Message) -> bool:
        channel = message.channel
        ids = {channel.id, getattr(channel, "parent_id", None)}  # include threads inside the channel
        return bool(ids & self.bot.autoadd_channels)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not self._watched_channel(message):
            return
        links = find_links(message.content)
        if not links:
            return
        embeds, created_any, duplicate_any, failed = [], False, False, []
        async with message.channel.typing():
            for link in links[:5]:
                try:
                    item = await self.bot.lookup_link(link)
                except MetadataError as e:
                    failed.append(f"{link.url}: {e}")
                    continue
                saved, created = await self.bot.add_to_watchlist(item, message.guild.id, message.author)
                created_any |= created
                duplicate_any |= not created
                embed = card_embed(saved)
                embed.set_author(name="Added to the watchlist" if created else "Already on the watchlist")
                embeds.append(embed)
        try:
            if created_any:
                await message.add_reaction("✅")
            if duplicate_any:
                await message.add_reaction("🔁")
            if failed:
                await message.add_reaction("⚠️")
        except discord.HTTPException:
            pass
        if embeds or failed:
            content = "\n".join(f"⚠️ {f}" for f in failed) or None
            await message.reply(content=content, embeds=embeds, mention_author=False, silent=True)


async def setup(bot: FilmvaleBot):
    await bot.add_cog(AutoAdd(bot))
