"""Embeds and interactive views shared by the cogs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Awaitable, Callable

import discord

from .models import KIND_EMOJI, Item, utcnow

if TYPE_CHECKING:
    from .bot import FilmvaleBot

TMDB_CREDIT = "Data from TMDB"

KIND_COLOURS = {
    "movie": discord.Colour.from_rgb(229, 160, 13),
    "series": discord.Colour.from_rgb(1, 180, 228),
    "youtube": discord.Colour.from_rgb(255, 0, 0),
    "other": discord.Colour.blurple(),
}


def _truncate(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def added_by(item: Item) -> str:
    if item.added_by_id:
        return f"<@{item.added_by_id}>"
    return item.added_by_name or "unknown"


def facts_line(item: Item) -> str:
    bits = [item.kind_label]
    if item.runtime_text:
        bits.append(item.runtime_text)
    if item.release_date:
        bits.append(item.release_date[:4] if item.kind != "youtube" else item.release_date)
    if item.rating:
        bits.append(f"⭐ {item.rating}")
    return " · ".join(bits)


def item_embed(item: Item, *, large_poster: bool = True, heading: str | None = None) -> discord.Embed:
    """Full detail card for one item."""
    title = f"{item.emoji} {item.display_title}"
    if item.watched:
        title = f"✅ {item.display_title}"
    embed = discord.Embed(
        title=_truncate(title, 256),
        url=item.link,
        description=_truncate(item.overview, 600),
        colour=discord.Colour.dark_grey() if item.watched else KIND_COLOURS.get(item.kind),
    )
    if heading:
        embed.set_author(name=heading)
    embed.add_field(name="Type", value=item.kind_label)
    if item.release_date or item.year:
        embed.add_field(name="Released", value=item.release_date or str(item.year))
    if item.runtime_text:
        embed.add_field(name="Episodes" if item.kind == "series" else "Runtime", value=item.runtime_text)
    if item.rating:
        embed.add_field(name="Rating", value=f"⭐ {item.rating}/10")
    if item.creator:
        embed.add_field(name="Channel" if item.kind == "youtube" else "By", value=_truncate(item.creator, 100))
    if item.genres:
        embed.add_field(name="Genres", value=_truncate(", ".join(item.genres), 200))
    if item.tags:
        embed.add_field(name="Tags", value=_truncate(", ".join(f"`{t}`" for t in item.tags), 200))
    when = f"<t:{int(item.added_at.timestamp())}:D>" if item.added_at else "unknown date"
    embed.add_field(name="Added", value=f"{added_by(item)} · {when}")
    if item.watched:
        watched = f"<t:{int(item.watched_at.timestamp())}:D>" if item.watched_at else "yes"
        embed.add_field(name="Watched", value=watched)
    if item.poster_url:
        if large_poster:
            embed.set_image(url=item.poster_url)
        else:
            embed.set_thumbnail(url=item.poster_url)
    footer = [f"#{item.id}" if item.id else None, TMDB_CREDIT if item.metadata_at else None]
    embed.set_footer(text=" · ".join(f for f in footer if f))
    return embed


def card_embed(item: Item, number: int | None = None) -> discord.Embed:
    """Compact card with a poster thumbnail — several of these fit in one message."""
    prefix = f"{number}. " if number is not None else ""
    status = "✅ " if item.watched else ""
    embed = discord.Embed(
        title=_truncate(f"{prefix}{status}{item.emoji} {item.display_title}", 256),
        url=item.link,
        colour=discord.Colour.dark_grey() if item.watched else KIND_COLOURS.get(item.kind),
    )
    lines = [f"**{facts_line(item)}**"]
    if item.overview:
        lines.append(_truncate(item.overview, 180))
    when = f"<t:{int(item.added_at.timestamp())}:R>" if item.added_at else ""
    lines.append(f"-# Added by {added_by(item)} {when}" + (f" · tags: {', '.join(item.tags)}" if item.tags else ""))
    embed.description = "\n".join(lines)
    if item.poster_url:
        embed.set_thumbnail(url=item.poster_url)
    if item.metadata_at:
        embed.set_footer(text=TMDB_CREDIT)
    return embed


def list_line(item: Item, number: int) -> str:
    check = "✅" if item.watched else item.emoji
    title = f"[{discord.utils.escape_markdown(item.display_title)}]({item.link})" if item.link else \
        f"**{discord.utils.escape_markdown(item.display_title)}**"
    when = f"<t:{int(item.added_at.timestamp())}:d>" if item.added_at else ""
    second = f"{facts_line(item)} · added by {added_by(item)} {when}".rstrip()
    return f"`{number:>3}` {check} {title}\n-# {second}"


class OwnerView(discord.ui.View):
    """A view only the user who invoked the command can drive."""

    def __init__(self, owner_id: int, timeout: float = 600):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "These controls belong to whoever ran the command — run it yourself to get your own.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


class ItemActionsView(OwnerView):
    """Buttons under a single item's detail card."""

    def __init__(self, bot: FilmvaleBot, item: Item, owner_id: int):
        super().__init__(owner_id)
        self.bot, self.item = bot, item
        self._sync()

    def _sync(self) -> None:
        self.toggle.label = "Mark unwatched" if self.item.watched else "Mark watched"
        self.toggle.style = discord.ButtonStyle.secondary if self.item.watched else discord.ButtonStyle.success

    @discord.ui.button(label="Mark watched", emoji="👁️")
    async def toggle(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.item.watched = not self.item.watched
        self.item.watched_at = utcnow() if self.item.watched else None
        await self.bot.db.update_item(self.item)
        self._sync()
        await interaction.response.edit_message(embed=item_embed(self.item), view=self)


class WatchlistBrowser(OwnerView):
    """Paginated watchlist with a compact list mode and a poster-card mode."""

    LIST_PAGE = 10
    CARD_PAGE = 5

    def __init__(self, bot: FilmvaleBot, items: list[Item], owner_id: int, title: str, cards: bool = False):
        super().__init__(owner_id)
        self.bot, self.items, self.title = bot, items, title
        self.cards = cards
        self.page = 0
        self._refresh()

    @property
    def per_page(self) -> int:
        return self.CARD_PAGE if self.cards else self.LIST_PAGE

    @property
    def pages(self) -> int:
        return max(1, -(-len(self.items) // self.per_page))

    def page_items(self) -> list[tuple[int, Item]]:
        start = self.page * self.per_page
        return list(enumerate(self.items[start : start + self.per_page], start + 1))

    def embeds(self) -> list[discord.Embed]:
        total_runtime = sum(i.runtime or 0 for i in self.items if i.kind == "movie")
        footer = f"Page {self.page + 1}/{self.pages} · {len(self.items)} items"
        if total_runtime:
            footer += f" · {total_runtime // 60}h {total_runtime % 60}m of movies"
        if any(item.metadata_at for _, item in self.page_items()):
            footer += f" · {TMDB_CREDIT}"
        if not self.items:
            return [discord.Embed(title=self.title, description="Nothing here yet — try `/add`.")]
        if self.cards:
            embeds = [card_embed(item, n) for n, item in self.page_items()]
            embeds[0].set_author(name=self.title)
            embeds[-1].set_footer(text=footer)
            return embeds
        embed = discord.Embed(
            title=self.title,
            description="\n".join(list_line(item, n) for n, item in self.page_items()),
            colour=discord.Colour.gold(),
        )
        # Show the first poster on the page so the list never feels bare.
        first = self.page_items()[0][1]
        if first.poster_url:
            embed.set_thumbnail(url=first.poster_url)
        embed.set_footer(text=footer)
        return [embed]

    def _refresh(self) -> None:
        self.prev.disabled = self.page == 0
        self.first.disabled = self.page == 0
        self.next.disabled = self.page >= self.pages - 1
        self.last.disabled = self.page >= self.pages - 1
        self.mode.label = "List view" if self.cards else "Poster view"
        self.mode.emoji = "📜" if self.cards else "🖼️"
        self.details.options = [
            discord.SelectOption(
                label=_truncate(f"{n}. {item.display_title}", 100),
                description=_truncate(facts_line(item), 100),
                value=str(item.id),
                emoji=KIND_EMOJI.get(item.kind),
            )
            for n, item in self.page_items()
        ] or [discord.SelectOption(label="Empty", value="0")]
        self.details.disabled = not self.items

    async def _show(self, interaction: discord.Interaction) -> None:
        self._refresh()
        await interaction.response.edit_message(embeds=self.embeds(), view=self)

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, row=0)
    async def first(self, interaction: discord.Interaction, _):
        self.page = 0
        await self._show(interaction)

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.primary, row=0)
    async def prev(self, interaction: discord.Interaction, _):
        self.page = max(0, self.page - 1)
        await self._show(interaction)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.primary, row=0)
    async def next(self, interaction: discord.Interaction, _):
        self.page = min(self.pages - 1, self.page + 1)
        await self._show(interaction)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
    async def last(self, interaction: discord.Interaction, _):
        self.page = self.pages - 1
        await self._show(interaction)

    @discord.ui.button(label="Poster view", style=discord.ButtonStyle.secondary, row=0)
    async def mode(self, interaction: discord.Interaction, _):
        first_index = self.page * self.per_page
        self.cards = not self.cards
        self.page = first_index // self.per_page
        await self._show(interaction)

    @discord.ui.select(placeholder="🔍 Open an item for full details…", row=1)
    async def details(self, interaction: discord.Interaction, select: discord.ui.Select):
        item = await self.bot.db.get_item(interaction.guild_id, int(select.values[0]))
        if not item:
            await interaction.response.send_message("That item was removed.", ephemeral=True)
            return
        view = ItemActionsView(self.bot, item, interaction.user.id)
        await interaction.response.send_message(embed=item_embed(item), view=view, ephemeral=True)


class SearchPicker(OwnerView):
    """Shows TMDB search results as poster cards; picking one calls ``on_pick``."""

    def __init__(self, results: list[Item], owner_id: int, on_pick: Callable[[discord.Interaction, Item], Awaitable[None]]):
        super().__init__(owner_id, timeout=300)
        self.results, self.on_pick = results[:10], on_pick
        self.choose.options = [
            discord.SelectOption(
                label=_truncate(f"{n}. {r.display_title}", 100),
                description=_truncate(f"{r.kind_label} · {r.overview or 'No description'}", 100),
                value=str(n - 1),
                emoji=KIND_EMOJI.get(r.kind),
            )
            for n, r in enumerate(self.results, 1)
        ]

    def embeds(self) -> list[discord.Embed]:
        embeds = []
        for n, r in enumerate(self.results[:5], 1):
            e = discord.Embed(
                title=_truncate(f"{n}. {r.emoji} {r.display_title}", 256),
                url=r.link,
                description=_truncate(r.overview, 200) or "*No description*",
                colour=KIND_COLOURS.get(r.kind),
            )
            e.set_footer(text=" · ".join(
                b for b in (f"⭐ {r.rating}/10" if r.rating else None, r.kind_label, TMDB_CREDIT) if b
            ))
            if r.poster_url:
                e.set_thumbnail(url=r.poster_url)
            embeds.append(e)
        if len(self.results) > 5:
            embeds[-1].set_footer(text=f"+{len(self.results) - 5} more in the menu below · {TMDB_CREDIT}")
        return embeds

    @discord.ui.select(placeholder="Pick the right one…")
    async def choose(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.stop()
        await self.on_pick(interaction, self.results[int(select.values[0])])

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _):
        self.stop()
        await interaction.response.edit_message(content="Cancelled.", embeds=[], view=None)


class ConfirmView(OwnerView):
    def __init__(self, owner_id: int, confirm_label: str = "Confirm", danger: bool = False):
        super().__init__(owner_id, timeout=180)
        self.value: bool | None = None
        self.confirm.label = confirm_label
        if danger:
            self.confirm.style = discord.ButtonStyle.danger

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _):
        self.value = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _):
        self.value = False
        self.stop()
        await interaction.response.edit_message(content="Cancelled.", embeds=[], view=None)
