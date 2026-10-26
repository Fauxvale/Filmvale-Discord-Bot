"""Link detection and metadata lookup (TMDB for film/TV, YouTube oEmbed/Data API for videos)."""

from __future__ import annotations

import asyncio
import html
import logging
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import aiohttp

from .models import Item

log = logging.getLogger(__name__)

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w500"
USER_AGENT = "Mozilla/5.0 (compatible; FilmvaleBot/1.0)"

URL_RE = re.compile(r"https?://[^\s<>|]+", re.IGNORECASE)
IMDB_RE = re.compile(r"imdb\.com/(?:[a-z]{2}(?:-[a-z]{2})?/)?title/(tt\d+)", re.IGNORECASE)
TMDB_RE = re.compile(r"themoviedb\.org/(movie|tv)/(\d+)", re.IGNORECASE)
TVDB_ID_RE = re.compile(r"thetvdb\.com/(?:.*[?&]id=|dereferrer/(series|movie)/)(\d+)", re.IGNORECASE)
TVDB_SLUG_RE = re.compile(r"thetvdb\.com/(series|movies)/([a-z0-9][a-z0-9-]*)", re.IGNORECASE)
LETTERBOXD_RE = re.compile(r"(?:letterboxd\.com/film/[a-z0-9-]+|boxd\.it/\w+)", re.IGNORECASE)
YOUTUBE_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be")
YT_ID_RE = re.compile(r"^[\w-]{11}$")


@dataclass(frozen=True)
class MediaLink:
    """A recognised media link and the identifier extracted from it."""

    source: str  # imdb | tmdb | tvdb | tvdb_slug | letterboxd | youtube_video | youtube_playlist
    value: str
    url: str
    hint: str | None = None  # "movie" / "series" when the URL tells us


def _clean_url(raw: str) -> str:
    return raw.rstrip(").,!?;:'\">]")


def parse_link(raw: str) -> MediaLink | None:
    url = _clean_url(raw.strip())
    if m := IMDB_RE.search(url):
        return MediaLink("imdb", m.group(1), f"https://www.imdb.com/title/{m.group(1)}/")
    if m := TMDB_RE.search(url):
        kind = "series" if m.group(1).lower() == "tv" else "movie"
        return MediaLink("tmdb", m.group(2), url, kind)
    if m := TVDB_ID_RE.search(url):
        kind = "movie" if (m.group(1) or "").lower() == "movie" else "series"
        return MediaLink("tvdb", m.group(2), url, kind)
    if m := TVDB_SLUG_RE.search(url):
        kind = "movie" if m.group(1).lower() == "movies" else "series"
        return MediaLink("tvdb_slug", m.group(2), url, kind)
    if LETTERBOXD_RE.search(url):
        return MediaLink("letterboxd", url, url, "movie")

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host in YOUTUBE_HOSTS:
        query = parse_qs(parsed.query)
        video_id = None
        if host == "youtu.be":
            video_id = parsed.path.lstrip("/").split("/")[0]
        elif "v" in query:
            video_id = query["v"][0]
        else:
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) >= 2 and parts[0] in ("shorts", "live", "embed", "v"):
                video_id = parts[1]
        if video_id and YT_ID_RE.match(video_id):
            return MediaLink("youtube_video", video_id, f"https://www.youtube.com/watch?v={video_id}")
        if "list" in query:
            pid = query["list"][0]
            return MediaLink("youtube_playlist", pid, f"https://www.youtube.com/playlist?list={pid}")
    return None


def find_links(text: str) -> list[MediaLink]:
    """All supported media links in a message, de-duplicated, in order."""
    seen, links = set(), []
    for raw in URL_RE.findall(text or ""):
        link = parse_link(raw)
        if link and (link.source, link.value) not in seen:
            seen.add((link.source, link.value))
            links.append(link)
    return links


def _iso_duration_minutes(value: str) -> int | None:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not m:
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    total = d * 1440 + h * 60 + mi + (1 if s >= 30 else 0)
    return total or (1 if s else None)


class MetadataError(Exception):
    pass


class Resolver:
    def __init__(self, tmdb_key: str | None, youtube_key: str | None):
        self.tmdb_key = tmdb_key
        self.youtube_key = youtube_key
        self.session: aiohttp.ClientSession | None = None
        self._tmdb_limit = asyncio.Semaphore(8)

    async def start(self) -> None:
        self.session = aiohttp.ClientSession(
            headers={"User-Agent": USER_AGENT}, timeout=aiohttp.ClientTimeout(total=15)
        )

    async def close(self) -> None:
        if self.session:
            await self.session.close()

    @property
    def has_tmdb(self) -> bool:
        return bool(self.tmdb_key)

    # ── HTTP helpers ─────────────────────────────────────────────────────

    async def _tmdb(self, path: str, **params) -> dict:
        if not self.tmdb_key:
            raise MetadataError("TMDB_API_KEY is not configured, so movie/TV metadata is unavailable.")
        headers = {}
        # v4 "read access tokens" are JWTs; v3 keys are short hex strings.
        if self.tmdb_key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {self.tmdb_key}"
        else:
            params["api_key"] = self.tmdb_key
        async with self._tmdb_limit:
            for attempt in range(3):
                async with self.session.get(f"{TMDB_API}{path}", params=params, headers=headers) as r:
                    if r.status == 429:
                        await asyncio.sleep(float(r.headers.get("Retry-After", 1 + attempt)))
                        continue
                    if r.status == 404:
                        raise MetadataError("Not found on TMDB.")
                    if r.status != 200:
                        raise MetadataError(f"TMDB returned HTTP {r.status}.")
                    return await r.json()
        raise MetadataError("TMDB rate limit hit; try again shortly.")

    async def _get_text(self, url: str) -> tuple[str, str]:
        async with self.session.get(url, allow_redirects=True) as r:
            return str(r.url), await r.text(errors="replace")

    # ── TMDB ─────────────────────────────────────────────────────────────

    def _from_tmdb(self, data: dict, kind: str) -> Item:
        is_tv = kind == "series"
        date = data.get("first_air_date" if is_tv else "release_date") or None
        runtime = data.get("runtime")
        if is_tv:
            runs = data.get("episode_run_time") or []
            runtime = runs[0] if runs else (data.get("last_episode_to_air") or {}).get("runtime")
        ext = data.get("external_ids") or {}
        imdb_id = data.get("imdb_id") or ext.get("imdb_id") or None
        creator = None
        if is_tv and data.get("created_by"):
            creator = ", ".join(c["name"] for c in data["created_by"][:2])
        elif crew := (data.get("credits") or {}).get("crew"):
            directors = [c["name"] for c in crew if c.get("job") == "Director"]
            creator = ", ".join(directors[:2]) or None
        tmdb_id = data["id"]
        return Item(
            kind=kind,
            title=data.get("name" if is_tv else "title") or data.get("original_title") or "Unknown",
            year=int(date[:4]) if date else None,
            release_date=date,
            runtime=runtime or None,
            seasons=data.get("number_of_seasons") if is_tv else None,
            episodes=data.get("number_of_episodes") if is_tv else None,
            overview=data.get("overview") or None,
            poster_url=f"{TMDB_IMG}{data['poster_path']}" if data.get("poster_path") else None,
            rating=round(data["vote_average"], 1) if data.get("vote_average") else None,
            genres=[g["name"] for g in data.get("genres") or []],
            creator=creator,
            url=f"https://www.imdb.com/title/{imdb_id}/" if imdb_id
            else f"https://www.themoviedb.org/{'tv' if is_tv else 'movie'}/{tmdb_id}",
            imdb_id=imdb_id,
            tmdb_id=tmdb_id,
            tvdb_id=ext.get("tvdb_id") or None,
        )

    async def tmdb_details(self, tmdb_id: int | str, kind: str) -> Item:
        path = f"/tv/{tmdb_id}" if kind == "series" else f"/movie/{tmdb_id}"
        data = await self._tmdb(path, append_to_response="external_ids,credits")
        return self._from_tmdb(data, kind)

    async def tmdb_find(self, external_id: str, source: str) -> Item:
        data = await self._tmdb(f"/find/{external_id}", external_source=source)
        if data.get("movie_results"):
            return await self.tmdb_details(data["movie_results"][0]["id"], "movie")
        if data.get("tv_results"):
            return await self.tmdb_details(data["tv_results"][0]["id"], "series")
        if ep := (data.get("tv_episode_results") or []):
            return await self.tmdb_details(ep[0]["show_id"], "series")
        raise MetadataError(f"TMDB has no entry for {external_id}.")

    async def search(self, query: str, kind: str | None = None, year: int | None = None) -> list[Item]:
        """Search TMDB. Results are lightweight (no runtime); call ``tmdb_details`` on the chosen one."""
        if kind == "movie":
            data = await self._tmdb("/search/movie", query=query, year=year or "", include_adult="false")
            results = [(r, "movie") for r in data.get("results", [])]
        elif kind == "series":
            data = await self._tmdb("/search/tv", query=query, first_air_date_year=year or "", include_adult="false")
            results = [(r, "series") for r in data.get("results", [])]
        else:
            data = await self._tmdb("/search/multi", query=query, include_adult="false")
            results = [
                (r, "series" if r["media_type"] == "tv" else "movie")
                for r in data.get("results", []) if r.get("media_type") in ("movie", "tv")
            ]
        return [self._from_tmdb(r, k) for r, k in results[:10]]

    async def best_match(self, title: str, kind: str | None = None, year: int | None = None) -> Item | None:
        results = await self.search(title, kind if kind in ("movie", "series") else None, year)
        if not results and year:
            results = await self.search(title, kind if kind in ("movie", "series") else None)
        if not results:
            return None
        return await self.tmdb_details(results[0].tmdb_id, results[0].kind)

    # ── YouTube ──────────────────────────────────────────────────────────

    async def youtube(self, link: MediaLink) -> Item:
        item = Item(kind="youtube", title=link.value, url=link.url, youtube_id=link.value)
        if link.source == "youtube_video":
            item.poster_url = f"https://i.ytimg.com/vi/{link.value}/hqdefault.jpg"
        async with self.session.get(
            "https://www.youtube.com/oembed", params={"url": link.url, "format": "json"}
        ) as r:
            if r.status == 200:
                data = await r.json(content_type=None)
                item.title = data.get("title") or item.title
                item.creator = data.get("author_name")
                item.poster_url = item.poster_url or data.get("thumbnail_url")
            elif r.status in (401, 403, 404):
                raise MetadataError("That YouTube video is private, removed, or not embeddable.")
        if self.youtube_key:
            await self._youtube_api(link, item)
        if link.source == "youtube_playlist":
            item.genres = ["Playlist"]
        return item

    async def _youtube_api(self, link: MediaLink, item: Item) -> None:
        if link.source == "youtube_video":
            endpoint, parts = "videos", "snippet,contentDetails"
        else:
            endpoint, parts = "playlists", "snippet,contentDetails"
        params = {"part": parts, "id": link.value, "key": self.youtube_key}
        try:
            async with self.session.get(f"https://www.googleapis.com/youtube/v3/{endpoint}", params=params) as r:
                if r.status != 200:
                    return
                data = (await r.json()).get("items") or []
        except aiohttp.ClientError:
            return
        if not data:
            return
        snip, details = data[0].get("snippet", {}), data[0].get("contentDetails", {})
        published = (snip.get("publishedAt") or "")[:10] or None
        item.release_date = published
        item.year = int(published[:4]) if published else None
        item.overview = (snip.get("description") or "").strip()[:1000] or None
        if "duration" in details:
            item.runtime = _iso_duration_minutes(details["duration"])
        if "itemCount" in details:
            item.episodes = details["itemCount"]
        thumbs = snip.get("thumbnails") or {}
        for size in ("maxres", "standard", "high"):
            if size in thumbs:
                item.poster_url = thumbs[size]["url"]
                break

    # ── Dispatch ─────────────────────────────────────────────────────────

    async def resolve(self, link: MediaLink) -> Item:
        try:
            if link.source == "imdb":
                return await self._with_fallback(self.tmdb_find(link.value, "imdb_id"), link)
            if link.source == "tmdb":
                return await self._with_fallback(self.tmdb_details(link.value, link.hint), link)
            if link.source == "tvdb":
                return await self._with_fallback(self.tmdb_find(link.value, "tvdb_id"), link)
            if link.source == "tvdb_slug":
                return await self._resolve_tvdb_slug(link)
            if link.source == "letterboxd":
                return await self._resolve_letterboxd(link)
            if link.source.startswith("youtube"):
                return await self.youtube(link)
        except aiohttp.ClientError as e:
            raise MetadataError(f"Network error while looking that up: {e}") from e
        raise MetadataError("Unsupported link.")

    async def _with_fallback(self, coro, link: MediaLink) -> Item:
        """Use TMDB if possible; otherwise keep the bare link so nothing is lost."""
        if not self.has_tmdb:
            coro.close()
            item = await self._scrape_opengraph(link)
        else:
            item = await coro
        if link.source == "imdb":
            item.imdb_id = item.imdb_id or link.value
        return item

    async def _resolve_tvdb_slug(self, link: MediaLink) -> Item:
        # TheTVDB slugs aren't usable with TMDB's /find, so read the page's numeric id first.
        try:
            _, page = await self._get_text(link.url)
            m = re.search(r"TheTVDB\.com (?:Series|Movie) ID\s*</strong>\s*<span>\s*(\d+)", page)
            if m and self.has_tmdb:
                try:
                    return await self.tmdb_find(m.group(1), "tvdb_id")
                except MetadataError:
                    pass
        except aiohttp.ClientError:
            pass
        title = link.value.replace("-", " ").title()
        if self.has_tmdb and (match := await self.best_match(title, link.hint)):
            return match
        return Item(kind=link.hint or "series", title=title, url=link.url)

    async def _resolve_letterboxd(self, link: MediaLink) -> Item:
        final_url, page = await self._get_text(link.url)
        if m := re.search(r'data-tmdb-id="(\d+)"', page):
            kind = "series" if 'data-tmdb-type="tv"' in page else "movie"
            if self.has_tmdb:
                return await self.tmdb_details(m.group(1), kind)
        item = _opengraph_item(page, final_url)
        item.kind = "movie"
        return item

    async def _scrape_opengraph(self, link: MediaLink) -> Item:
        try:
            final_url, page = await self._get_text(link.url)
            item = _opengraph_item(page, final_url)
        except aiohttp.ClientError:
            item = Item(title=link.value, url=link.url)
        item.kind = link.hint or "movie"
        item.url = link.url
        return item


def _opengraph_item(page: str, url: str) -> Item:
    def meta(prop: str) -> str | None:
        m = re.search(
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']*)', page
        ) or re.search(
            rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']', page
        )
        return html.unescape(m.group(1)).strip() if m else None

    title = meta("og:title") or url
    year = None
    if m := re.search(r"\((\d{4})\)", title):
        year = int(m.group(1))
    title = re.sub(r"\s*[-|]\s*(IMDb|Letterboxd|TheTVDB.*)$", "", title)
    title = re.sub(r"\s*\(\d{4}\)\s*$", "", title).strip() or url
    return Item(
        title=title,
        year=year,
        overview=meta("og:description") or meta("description"),
        poster_url=meta("og:image"),
        url=url,
    )
