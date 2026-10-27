<p align="center"><img src="art/filmvale-banner.png" alt="Filmvale — your server's watchlist" width="680"></p>
Filmvale is a self-hosted Discord bot for keeping a shared watchlist of movies, series, YouTube videos and anything else, inspired by [WatchList](https://www.watchlistbot.com/).

## Features

| Feature | Details |
|---|---|
| **Watchlist** | Add by link or title search (visual picker with posters), mark watched, tag, remove |
| **Browse** | Paginated compact list ⇄ poster-card view, filter by type/status/tag, 6 sort orders, open any entry for full details (poster, runtime, release, rating, genres, who added it & when) |
| **Random picks** | Pick one or more random entries, with 🎲 Reroll and 📊 "Poll these" buttons |
| **Native polls** | Real Discord polls (not reaction embeds), random or hand-picked, 1 hour–32 days, multiple votes allowed by default. Discord announces the result itself when the poll closes |
| **Auto-add** | Links posted in configured channels (and their threads) are added automatically: IMDb, TMDB, TheTVDB, Letterboxd, YouTube videos/shorts/playlists |
| **Movie nights** | Create a Discord scheduled event with the poster as cover; length defaults to runtime + 15 min |
| **Export** | Formatted Markdown `.md` (default), plain `.txt`, or a full `.json` backup |
| **Import** | WatchList bot `.json`/`.zip` exports, IMDb list `.csv`, Filmvale's own exports, or any `.txt`/`.md` with one title/link per line. Preview + confirm, merge/replace, skip/update on conflict, optional TMDB enrichment |

## Commands

Parameters in *italics* are optional. Any `item` parameter autocompletes from the watchlist, or you can type part of a title.

### Watchlist

| Command | What it does |
|---|---|
| `/add` *link* *title* *kind* *year* *tags* | Add an entry by pasting a link, or search by `title` (narrowed by `kind`/`year`) and pick from the results. `tags` is comma-separated, e.g. `horror,halloween` |
| `/list` *kind* *status* *tag* *sort* *posters* *private* | Browse the watchlist. `status`: to watch (default), watched or everything. `sort`: newest added (default), oldest added, title A–Z, release date, runtime, rating. `posters:True` starts in poster-card view, `private:True` shows it only to you |
| `/info` item | Full details for one entry, with a Mark watched/unwatched button |
| `/random` *kind* *count* *tag* *include_watched* | Pick 1–10 random entries (unwatched only unless `include_watched:True`) |
| `/watched` item | Mark an entry as watched |
| `/unwatched` item | Undo marking an entry as watched |
| `/remove` item | Remove an entry. Only whoever added it, or members with *Manage Messages*/*Manage Server* |
| `/tag add` item tags | Add comma-separated tags to an entry |
| `/tag remove` item tags | Remove comma-separated tags from an entry |

### Polls & events

| Command | What it does |
|---|---|
| `/poll` *question* *items* *count* *kind* *tag* *hours* *multiple* *include_watched* | Start a native Discord poll. Either list titles with `items:Alien; Up; Heat`, or let it pick `count` (2–10, default 5) random entries filtered by `kind`/`tag`. `hours`: 1–768 (default 24). `multiple` defaults to `True` |
| `/schedule` item when *channel* *location* *length* *title* | Create a Discord scheduled event. `when` takes natural language (`friday 8pm`, `2026-11-01 20:00`) or a Discord timestamp (`<t:1793386800>`), with a live preview while you type. Hosted in a voice/stage `channel` (or the server's default event channel), or at a text `location` such as `Teleparty`. `length` in minutes (default runtime + 15). Pasting a link as `item` adds it to the watchlist too. Requires *Create Events* |

### Import & export

| Command | What it does |
|---|---|
| `/export` *format* *status* *kind* | Download the watchlist. `format`: Markdown `.md` (default), plain text `.txt`, or JSON backup `.json` (lossless, can be re-imported). `status`: everything (default), to watch only, watched only |
| `/import` file *mode* *on_conflict* *enrich* | Import a file (see the formats above). Shows a preview to confirm first. `mode`: merge (default) or replace. `on_conflict`: skip (default) or update (fill gaps, sync watched status & tags). `enrich` (default `True`) fills in missing posters/runtimes/genres from TMDB/YouTube. Requires *Manage Server* |

### Settings

All `/settings` commands require *Manage Server*.

| Command | What it does |
|---|---|
| `/settings show` | Show the current settings |
| `/settings autoadd add` channel | Auto-add media links posted in a channel (and its threads) |
| `/settings autoadd remove` channel | Stop auto-adding links from a channel |
| `/settings timezone` zone | Timezone used to read `/schedule` times, e.g. `America/New_York` (autocompletes) |
| `/settings event-channel` *channel* | Default voice channel for `/schedule` events (omit to clear) |

### Other

| Command | What it does |
|---|---|
| `/about` | What Filmvale is and where its data comes from |

### Auto-add

In a channel set up with `/settings autoadd add`, just post a link. Filmvale reacts ✅ when it adds something, 🔁 when it's already on the list and ⚠️ when a link couldn't be looked up, then replies quietly with a card for each entry.

## Setup

1. **Create the bot** at <https://discord.com/developers/applications> → *New Application* → *Bot*:
   - *Reset Token* and copy it.
   - Under *Privileged Gateway Intents* enable **Message Content Intent** (needed for auto-add).
   - *(Optional)* Upload [`art/filmvale-icon.png`](art/filmvale-icon.png) as the *App Icon* (General Information) and [`art/filmvale-banner.png`](art/filmvale-banner.png) as the *Banner* (Bot). SVG sources are in [`art/`](art/).
2. **Get a TMDB key** (free) at <https://www.themoviedb.org/settings/api>. Either the v3 API key or v4 read token works. Without it, movie/TV links are stored with no metadata and title search is disabled — IMDb blocks scraping, so this key is effectively required.
3. *(Optional)* A **YouTube Data API v3** key adds video runtimes, upload dates and descriptions. Titles, channels and thumbnails work without it.
4. **Install & configure** (Python 3.10+)
   ```fish
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   cp .env.example .env   # then fill it in, see below
   ```
5. **Invite it** (replace `CLIENT_ID` with the Application ID):
   ```
   https://discord.com/oauth2/authorize?client_id=CLIENT_ID&scope=bot+applications.commands&permissions=580817018539072
   ```
   (View Channels, Send Messages (+ in threads), Embed Links, Attach Files, Read History, Add Reactions, Create Events, Send Polls, Connect — needed to host events in voice channels.)
6. **Run**: `.venv/bin/python -m filmvale`
7. **Configure in Discord**:
   - `/settings autoadd add channel:#movie-links`
   - `/settings timezone zone:America/New_York` — used to interpret `/schedule` times
   - `/settings event-channel channel:🔊 Movie Night` — optional default venue for events

### Configuration (`.env`)

| Variable | Description |
|---|---|
| `DISCORD_TOKEN` | **Required.** The bot token |
| `TMDB_API_KEY` | Strongly recommended. TMDB v3 API key or v4 read access token |
| `YOUTUBE_API_KEY` | Optional. YouTube Data API v3 key |
| `DEV_GUILD_ID` | Optional. Your server's ID, so slash commands sync there instantly (global sync can take up to an hour) |
| `DATABASE_PATH` | Optional. SQLite file location (default `filmvale.db`) |
| `LOG_LEVEL` | Optional. `DEBUG`, `INFO` (default), `WARNING`… |

### Updating

```fish
git pull
.venv/bin/pip install -r requirements.txt
```
Then restart the bot. The database is upgraded automatically on start.

## Migrating from WatchList

Run `/watchlist export` in the original bot, download the `.json`, then `/import file:<that file>`. Titles, links, requester, request date, tags, watched status, runtime, rating, poster, description and TMDB IDs carry over. The original bot stores the content type as a tag (`Movie`/`TVShow`/`YouTube`); that becomes the entry type here and is removed from the tags. With `enrich:True` (default) missing runtimes, genres, episode counts, etc. are filled from TMDB.

## Notes

- TMDB's API terms forbid caching their data for more than 6 months, so Filmvale re-fetches each entry's TMDB details once they're ~5 months old (checked every 6 hours). If a title has been removed from TMDB — or no TMDB key is configured — its cached TMDB details (description, poster, runtime, rating, genres…) are cleared once they pass 6 months; your own data (title, tags, who added it, watched status) is never touched.
- Data lives in a single SQLite file (`filmvale.db`); each server has its own list.
- The default permissions above (`/import` and `/settings` → *Manage Server*, `/schedule` → *Create Events*) can be changed by server admins under *Server Settings → Integrations*.
- Discord poll limits: 10 options, 55 characters per option, 1 hour – 32 days.
- Tests: `.venv/bin/pip install pytest pytest-asyncio && .venv/bin/python -m pytest`

## Attribution

<img src="filmvale/assets/tmdb_logo_short.svg" alt="TMDB logo" height="14">

Movie and TV metadata and posters come from [The Movie Database (TMDB)](https://www.themoviedb.org/). Filmvale uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB.

TMDB's license is for non-commercial use only. If you run your own copy, you need your own TMDB API key and must follow the [TMDB API Terms of Use](https://www.themoviedb.org/api-terms-of-use).

## License

[MIT](LICENSE)
