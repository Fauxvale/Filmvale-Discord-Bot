"""/poll — native Discord polls built from the watchlist."""

from __future__ import annotations

from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from ..bot import KIND_CHOICES, FilmvaleBot, tag_autocomplete
from ..models import Item

MAX_ANSWERS = 10  # Discord limit
ANSWER_LEN = 55  # Discord limit


def answer_text(item: Item) -> str:
    text = item.display_title
    if len(text) > ANSWER_LEN:
        text = text[: ANSWER_LEN - 1].rstrip() + "…"
    return text


def build_poll(items: list[Item], question: str, *, hours: int = 24, multiple: bool = True) -> discord.Poll:
    poll = discord.Poll(question=question[:300], duration=timedelta(hours=hours), multiple=multiple)
    for item in items[:MAX_ANSWERS]:
        poll.add_answer(text=answer_text(item), emoji=item.emoji)
    return poll


class Polls(commands.Cog):
    def __init__(self, bot: FilmvaleBot):
        self.bot = bot

    @app_commands.command(description="Start a native Discord poll from the watchlist.")
    @app_commands.guild_only()
    @app_commands.describe(
        question="Poll question",
        items="Specific titles separated by ; (otherwise picks at random)",
        count="How many random options (2–10)",
        kind="Only pick this type",
        tag="Only pick items with this tag",
        hours="How long the poll stays open (1–768 hours)",
        multiple="Let people vote for more than one option (default: yes)",
        include_watched="Allow already-watched items in random picks",
    )
    @app_commands.choices(kind=KIND_CHOICES)
    @app_commands.autocomplete(tag=tag_autocomplete)
    async def poll(
        self,
        interaction: discord.Interaction,
        question: str = "What should we watch next?",
        items: str | None = None,
        count: app_commands.Range[int, 2, 10] = 5,
        kind: app_commands.Choice[str] | None = None,
        tag: str | None = None,
        hours: app_commands.Range[int, 1, 768] = 24,
        multiple: bool = True,
        include_watched: bool = False,
    ):
        if items:
            picks, missing = [], []
            for name in (n.strip() for n in items.split(";")):
                if not name:
                    continue
                found = await self.bot.resolve_item(interaction.guild_id, name)
                if found and found.id not in {p.id for p in picks}:
                    picks.append(found)
                elif not found:
                    missing.append(name)
            if missing:
                await interaction.response.send_message(
                    "Couldn't find: " + ", ".join(f"**{discord.utils.escape_markdown(m)}**" for m in missing),
                    ephemeral=True,
                )
                return
        else:
            picks = await self.bot.db.random_items(
                interaction.guild_id,
                count,
                kind=kind.value if kind else None,
                watched=None if include_watched else False,
                tag=tag,
            )
        if len(picks) < 2:
            await interaction.response.send_message("A poll needs at least 2 options.", ephemeral=True)
            return
        if len(picks) > MAX_ANSWERS:
            await interaction.response.send_message(f"Discord polls allow at most {MAX_ANSWERS} options.", ephemeral=True)
            return
        await interaction.response.send_message(poll=build_poll(picks, question, hours=hours, multiple=multiple))


async def setup(bot: FilmvaleBot):
    await bot.add_cog(Polls(bot))
