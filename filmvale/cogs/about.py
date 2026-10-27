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
COMMANDS = [
    (
        "Watchlist",
        "`/add` add by link or title search\n"
        "`/list` browse with posters and details\n"
        "`/info` full details for one entry\n"
        "`/random` pick something to watch\n"
        "`/watched` · `/unwatched` mark entries\n"
        "`/remove` remove an entry\n"
        "`/tag add` · `/tag remove` organise with tags",
    ),
    (
        "Polls & movie nights",
        "`/poll` start a Discord poll from the list\n"
        "`/schedule` create a scheduled event for a movie night",
    ),
    (
        "Import & export",
        "`/export` download the list as .md, .txt or .json\n"
        "`/import` bring in a WatchList bot export, IMDb CSV or text list",
    ),
    (
        "Settings (Manage Server)",
        "`/settings show` current settings\n"
        "`/settings autoadd add` · `/settings autoadd remove` channels where posted links are added automatically\n"
        "`/settings timezone` timezone for `/schedule` times\n"
        "`/settings event-channel` default voice channel for events",
    ),
    ("Other", "`/about` this message"),
]


class About(commands.Cog):
    def __init__(self, bot: FilmvaleBot):
        self.bot = bot

    @app_commands.command(description="About Filmvale and where its data comes from.")
    async def about(self, interaction: discord.Interaction):
        me = self.bot.user
        embed = discord.Embed(
            title="🎞️ Filmvale",
            url=REPO_URL,
            description="A shared watchlist for movies, series, YouTube and anything else.",
            colour=discord.Colour.from_rgb(1, 180, 228),
        )
        if me and me.display_avatar:
            embed.set_thumbnail(url=me.display_avatar.url)
        for name, value in COMMANDS:
            embed.add_field(name=name, value=value, inline=False)
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
