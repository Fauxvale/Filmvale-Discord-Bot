"""/about — what Filmvale is, plus the TMDB attribution its API terms require."""

from __future__ import annotations

from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from ..bot import FilmvaleBot

TMDB_LOGO = Path(__file__).resolve().parent.parent / "assets" / "tmdb_logo.png"
TMDB_NOTICE = "Filmvale uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB."
REPO_URL = "https://github.com/Fauxvale/Filmvale-Discord-Bot"


class About(commands.Cog):
    def __init__(self, bot: FilmvaleBot):
        self.bot = bot

    @app_commands.command(description="About Filmvale and where its data comes from.")
    async def about(self, interaction: discord.Interaction):
        me = self.bot.user
        embed = discord.Embed(
            title="🎞️ Filmvale",
            url=REPO_URL,
            description=(
                "A shared watchlist for movies, series and YouTube.\n"
                "`/add` · `/list` · `/random` · `/poll` · `/schedule` · `/export` · `/import`"
            ),
            colour=discord.Colour.from_rgb(1, 180, 228),
        )
        if me and me.display_avatar:
            embed.set_thumbnail(url=me.display_avatar.url)
        embed.add_field(
            name="Data sources",
            value=(
                f"Movie & TV metadata and posters: [The Movie Database (TMDB)](https://www.themoviedb.org/)\n"
                f"YouTube details: YouTube\n\n*{TMDB_NOTICE}*"
            ),
            inline=False,
        )
        embed.set_footer(text="Powered by TMDB", icon_url="attachment://tmdb_logo.png")
        await interaction.response.send_message(
            embed=embed, file=discord.File(TMDB_LOGO, filename="tmdb_logo.png")
        )


async def setup(bot: FilmvaleBot):
    await bot.add_cog(About(bot))
