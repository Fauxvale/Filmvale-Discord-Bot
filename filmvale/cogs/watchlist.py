"""/add, /list, /info, /random, /remove, /watched, /unwatched, /tag."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..bot import KIND_CHOICES, FilmvaleBot, item_autocomplete, parse_tags, tag_autocomplete
from ..metadata import MetadataError, parse_link
from ..models import KIND_LABELS, Item, utcnow
from ..ui import ItemActionsView, OwnerView, SearchPicker, WatchlistBrowser, card_embed, item_embed
from .polls import build_poll

STATUS_CHOICES = [
    app_commands.Choice(name="To watch (default)", value="unwatched"),
    app_commands.Choice(name="Watched", value="watched"),
    app_commands.Choice(name="Everything", value="all"),
]
SORT_CHOICES = [
    app_commands.Choice(name="Newest added", value="added"),
    app_commands.Choice(name="Oldest added", value="oldest"),
    app_commands.Choice(name="Title A–Z", value="title"),
    app_commands.Choice(name="Release date (newest)", value="release"),
    app_commands.Choice(name="Runtime (shortest)", value="runtime"),
    app_commands.Choice(name="Rating (highest)", value="rating"),
]
STATUS_FILTER = {"unwatched": False, "watched": True, "all": None}


def can_modify(interaction: discord.Interaction, item: Item) -> bool:
    perms = interaction.permissions
    return item.added_by_id == interaction.user.id or perms.manage_messages or perms.manage_guild


class RandomView(OwnerView):
    def __init__(self, bot: FilmvaleBot, owner_id: int, picks: list[Item], filters: dict, count: int):
        super().__init__(owner_id)
        self.bot, self.picks, self.filters, self.count = bot, picks, filters, count
        self.poll.disabled = len(picks) < 2

    @discord.ui.button(label="Reroll", emoji="🎲", style=discord.ButtonStyle.primary)
    async def reroll(self, interaction: discord.Interaction, _):
        self.picks = await self.bot.db.random_items(interaction.guild_id, self.count, **self.filters)
        self.poll.disabled = len(self.picks) < 2
        await interaction.response.edit_message(embeds=[card_embed(p, n) for n, p in enumerate(self.picks, 1)], view=self)

    @discord.ui.button(label="Poll these", emoji="📊", style=discord.ButtonStyle.success)
    async def poll(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(poll=build_poll(self.picks, "What should we watch?", hours=24))
        self.poll.disabled = True
        if self.message:
            await self.message.edit(view=self)


class Watchlist(commands.Cog):
    def __init__(self, bot: FilmvaleBot):
        self.bot = bot

    # ── /add ─────────────────────────────────────────────────────────────

    @app_commands.command(description="Add something to the watchlist by link or by title search.")
    @app_commands.guild_only()
    @app_commands.describe(
        link="IMDb, TMDB, TheTVDB, Letterboxd or YouTube link",
        title="Title to search for (movies & series)",
        kind="What it is — narrows title searches",
        year="Release year, to narrow title searches",
        tags="Comma-separated tags, e.g. horror,halloween",
    )
    @app_commands.choices(kind=KIND_CHOICES)
    @app_commands.autocomplete(tags=tag_autocomplete)
    async def add(
        self,
        interaction: discord.Interaction,
        link: str | None = None,
        title: str | None = None,
        kind: app_commands.Choice[str] | None = None,
        year: app_commands.Range[int, 1870, 2100] | None = None,
        tags: str | None = None,
    ):
        kind_value = kind.value if kind else None
        tag_list = parse_tags(tags)
        if not link and not title:
            await interaction.response.send_message("Give me a `link` or a `title`.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)

        if link:
            parsed = parse_link(link)
            if parsed:
                try:
                    item = await self.bot.lookup_link(parsed)
                except MetadataError as e:
                    await interaction.followup.send(f"⚠️ {e}")
                    return
            else:
                # Unknown site: keep it as an "Other" entry so nothing is lost.
                item = Item(kind=kind_value or "other", title=title or link, url=link)
            await self._finish_add(interaction, item, tag_list, edit=False)
            return

        if kind_value in ("youtube",):
            await interaction.followup.send("YouTube entries need a `link`.")
            return
        if kind_value == "other" or not self.bot.resolver.has_tmdb:
            item = Item(kind=kind_value or "movie", title=title, year=year)
            await self._finish_add(interaction, item, tag_list, edit=False)
            return
        try:
            results = await self.bot.resolver.search(title, kind_value, year)
        except MetadataError as e:
            await interaction.followup.send(f"⚠️ {e}")
            return
        if not results:
            item = Item(kind=kind_value or "movie", title=title, year=year)
            await interaction.followup.send(
                f"No TMDB matches for **{discord.utils.escape_markdown(title)}** — added it without metadata."
            )
            await self._finish_add(interaction, item, tag_list, edit=False)
            return

        async def on_pick(pick_interaction: discord.Interaction, choice: Item):
            await pick_interaction.response.defer()
            try:
                full = await self.bot.resolver.tmdb_details(choice.tmdb_id, choice.kind)
            except MetadataError:
                full = choice
            await self._finish_add(pick_interaction, full, tag_list, edit=True)

        picker = SearchPicker(results, interaction.user.id, on_pick)
        picker.message = await interaction.followup.send(
            f"🔎 Results for **{discord.utils.escape_markdown(title)}** — pick one:",
            embeds=picker.embeds(),
            view=picker,
            wait=True,
        )

    async def _finish_add(self, interaction: discord.Interaction, item: Item, tags: list[str], *, edit: bool):
        saved, created = await self.bot.add_to_watchlist(item, interaction.guild_id, interaction.user, tags)
        heading = "Added to the watchlist" if created else "Already on the watchlist"
        if not created and saved.watched:
            heading += " (already watched)"
        embed = item_embed(saved, heading=heading)
        if edit:
            await interaction.edit_original_response(content=None, embeds=[embed], view=None)
        else:
            await interaction.followup.send(embed=embed)

    # ── /list & /info ────────────────────────────────────────────────────

    @app_commands.command(name="list", description="Browse the watchlist with posters and details.")
    @app_commands.guild_only()
    @app_commands.describe(
        kind="Only show one type",
        status="To watch, watched, or everything",
        tag="Only items with this tag",
        sort="Sort order",
        posters="Start in poster-card view instead of the compact list",
        private="Only you can see the result",
    )
    @app_commands.choices(kind=KIND_CHOICES, status=STATUS_CHOICES, sort=SORT_CHOICES)
    @app_commands.autocomplete(tag=tag_autocomplete)
    async def list_(
        self,
        interaction: discord.Interaction,
        kind: app_commands.Choice[str] | None = None,
        status: app_commands.Choice[str] | None = None,
        tag: str | None = None,
        sort: app_commands.Choice[str] | None = None,
        posters: bool = False,
        private: bool = False,
    ):
        status_value = status.value if status else "unwatched"
        items = await self.bot.db.list_items(
            interaction.guild_id,
            kind=kind.value if kind else None,
            watched=STATUS_FILTER[status_value],
            tag=tag,
            sort=sort.value if sort else "added",
        )
        label = {"unwatched": "To watch", "watched": "Watched", "all": "Watchlist"}[status_value]
        title = f"📋 {label}" + (f" · {KIND_LABELS[kind.value]}" if kind else "") + (f" · #{tag}" if tag else "")
        view = WatchlistBrowser(self.bot, items, interaction.user.id, title, cards=posters)
        await interaction.response.send_message(embeds=view.embeds(), view=view, ephemeral=private)
        view.message = await interaction.original_response()

    @app_commands.command(description="Show full details for one watchlist entry.")
    @app_commands.guild_only()
    @app_commands.autocomplete(item=item_autocomplete())
    async def info(self, interaction: discord.Interaction, item: str):
        found = await self.bot.resolve_item(interaction.guild_id, item)
        if not found:
            await interaction.response.send_message("Couldn't find that on the watchlist.", ephemeral=True)
            return
        view = ItemActionsView(self.bot, found, interaction.user.id)
        await interaction.response.send_message(embed=item_embed(found), view=view)
        view.message = await interaction.original_response()

    # ── /random ──────────────────────────────────────────────────────────

    @app_commands.command(description="Pick random things to watch from the watchlist.")
    @app_commands.guild_only()
    @app_commands.describe(
        kind="Only pick this type",
        count="How many picks (1–10)",
        tag="Only pick items with this tag",
        include_watched="Allow already-watched items",
    )
    @app_commands.choices(kind=KIND_CHOICES)
    @app_commands.autocomplete(tag=tag_autocomplete)
    async def random(
        self,
        interaction: discord.Interaction,
        kind: app_commands.Choice[str] | None = None,
        count: app_commands.Range[int, 1, 10] = 1,
        tag: str | None = None,
        include_watched: bool = False,
    ):
        filters = {"kind": kind.value if kind else None, "watched": None if include_watched else False, "tag": tag}
        picks = await self.bot.db.random_items(interaction.guild_id, count, **filters)
        if not picks:
            await interaction.response.send_message("Nothing matches those filters.", ephemeral=True)
            return
        note = f"🎲 Here {'is' if len(picks) == 1 else 'are'} **{len(picks)}** random pick{'s' if len(picks) != 1 else ''}"
        if len(picks) < count:
            note += f" (only {len(picks)} matched)"
        embeds = [item_embed(picks[0])] if len(picks) == 1 else [card_embed(p, n) for n, p in enumerate(picks, 1)]
        view = RandomView(self.bot, interaction.user.id, picks, filters, count)
        await interaction.response.send_message(note, embeds=embeds, view=view)
        view.message = await interaction.original_response()

    # ── watched state & removal ──────────────────────────────────────────

    @app_commands.command(description="Mark something as watched.")
    @app_commands.guild_only()
    @app_commands.autocomplete(item=item_autocomplete(watched=False))
    async def watched(self, interaction: discord.Interaction, item: str):
        await self._set_watched(interaction, item, True)

    @app_commands.command(description="Undo marking something as watched.")
    @app_commands.guild_only()
    @app_commands.autocomplete(item=item_autocomplete(watched=True))
    async def unwatched(self, interaction: discord.Interaction, item: str):
        await self._set_watched(interaction, item, False)

    async def _set_watched(self, interaction: discord.Interaction, value: str, state: bool):
        found = await self.bot.resolve_item(interaction.guild_id, value, watched=not state)
        if not found:
            await interaction.response.send_message("Couldn't find that on the watchlist.", ephemeral=True)
            return
        found.watched = state
        found.watched_at = utcnow() if state else None
        await self.bot.db.update_item(found)
        verb = "Marked as watched" if state else "Back on the to-watch list"
        await interaction.response.send_message(embed=item_embed(found, large_poster=False, heading=verb))

    @app_commands.command(description="Remove something from the watchlist.")
    @app_commands.guild_only()
    @app_commands.autocomplete(item=item_autocomplete())
    async def remove(self, interaction: discord.Interaction, item: str):
        found = await self.bot.resolve_item(interaction.guild_id, item)
        if not found:
            await interaction.response.send_message("Couldn't find that on the watchlist.", ephemeral=True)
            return
        if not can_modify(interaction, found):
            await interaction.response.send_message(
                "Only the person who added it (or a moderator) can remove it.", ephemeral=True
            )
            return
        await self.bot.db.delete_item(interaction.guild_id, found.id)
        await interaction.response.send_message(f"🗑️ Removed **{discord.utils.escape_markdown(found.display_title)}**.")

    # ── /tag ─────────────────────────────────────────────────────────────

    tag = app_commands.Group(name="tag", description="Add or remove tags on an entry.", guild_only=True)

    @tag.command(name="add", description="Add tags to an entry.")
    @app_commands.describe(tags="Comma-separated tags")
    @app_commands.autocomplete(item=item_autocomplete(), tags=tag_autocomplete)
    async def tag_add(self, interaction: discord.Interaction, item: str, tags: str):
        await self._edit_tags(interaction, item, tags, add=True)

    @tag.command(name="remove", description="Remove tags from an entry.")
    @app_commands.describe(tags="Comma-separated tags")
    @app_commands.autocomplete(item=item_autocomplete(), tags=tag_autocomplete)
    async def tag_remove(self, interaction: discord.Interaction, item: str, tags: str):
        await self._edit_tags(interaction, item, tags, add=False)

    async def _edit_tags(self, interaction: discord.Interaction, value: str, tags: str, *, add: bool):
        found = await self.bot.resolve_item(interaction.guild_id, value)
        if not found:
            await interaction.response.send_message("Couldn't find that on the watchlist.", ephemeral=True)
            return
        changes = parse_tags(tags)
        current = {t.lower(): t for t in found.tags}
        for t in changes:
            if add:
                current.setdefault(t.lower(), t)
            else:
                current.pop(t.lower(), None)
        found.tags = sorted(current.values(), key=str.lower)
        await self.bot.db.update_item(found)
        shown = ", ".join(f"`{t}`" for t in found.tags) or "*none*"
        await interaction.response.send_message(
            f"🏷️ **{discord.utils.escape_markdown(found.display_title)}** tags: {shown}"
        )


async def setup(bot: FilmvaleBot):
    await bot.add_cog(Watchlist(bot))
