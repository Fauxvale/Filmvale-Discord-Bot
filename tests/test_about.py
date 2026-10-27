import re

import discord

from filmvale.bot import COGS, FilmvaleBot
from filmvale.cogs.about import COMMANDS


async def test_about_lists_every_command():
    bot = FilmvaleBot()
    try:
        for cog in COGS:
            await bot.load_extension(cog)
        registered = {
            "/" + c.qualified_name for c in bot.tree.walk_commands() if isinstance(c, discord.app_commands.Command)
        }
    finally:
        await bot.close()
    listed = set(re.findall(r"`(/[^`]+)`", " ".join(value for _, value in COMMANDS)))
    assert listed == registered
    assert all(len(value) <= 1024 for _, value in COMMANDS)  # Discord embed field limit
