# Filmvale

Filmvale is a self-hosted Discord bot for keeping a shared watchlist of movies, series, YouTube videos and anything else, inspired by [WatchList](https://www.watchlistbot.com/).

## Features

| | |
|---|---|
| **Watchlist** | `/add` by link or title search (visual picker with posters), `/remove`, `/watched`, `/unwatched`, `/tag add/remove` |
| **Browse** | `/list` — paginated compact list ⇄ poster-card view, filter by type/status/tag, 6 sort orders, open any entry for full details (poster, runtime, release, rating, genres, who added it & when) |
| **Random picks** | `/random kind:movie count:3` — with 🎲 Reroll and 📊 "Poll these" buttons |
| **Native polls** | `/poll` — real Discord polls (not reaction embeds), random or hand-picked (`items:Alien; Up; Heat`), 1h–32 days, multiple votes allowed by default |
| **Auto-add** | Links posted in configured channels (and their threads) are added automatically: IMDb, TMDB, TheTVDB, Letterboxd, YouTube videos/shorts/playlists |
| **Movie nights** | `/schedule item:<title or link> when:"friday 8pm"` creates a Discord scheduled event with the poster as cover, length = runtime + 15 min |
| **Export** | `/export` → human-readable `.txt` (or `.json` backup) |
| **About** | `/about` — what Filmvale is and where its data comes from |
| **Import** | `/import` → WatchList bot `.json`/`.zip` exports, IMDb list `.csv`, this bot's own exports, or any `.txt` with one title/link per line. Preview + confirm, merge/replace, skip/update on conflict, optional TMDB enrichment |

## Setup

1. **Create the bot** at <https://discord.com/developers/applications> → *New Application* → *Bot*:
   - *Reset Token* and copy it.
   - Under *Privileged Gateway Intents* enable **Message Content Intent** (needed for auto-add).
2. **Get a TMDB key** (free) at <https://www.themoviedb.org/settings/api>. Either the v3 API key or v4 read token works. Without it, movie/TV links are stored with no metadata and title search is disabled — IMDb blocks scraping, so this key is effectively required.
3. *(Optional)* A **YouTube Data API v3** key adds video runtimes, upload dates and descriptions. Titles, channels and thumbnails work without it.
4. **Install & configure**
   ```fish
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   cp .env.example .env   # then fill in DISCORD_TOKEN, TMDB_API_KEY, DEV_GUILD_ID
   ```
   Set `DEV_GUILD_ID` to your server's ID so commands appear instantly (global sync can take up to an hour).
5. **Invite it** (replace `CLIENT_ID` with the Application ID):
   ```
   https://discord.com/oauth2/authorize?client_id=CLIENT_ID&scope=bot+applications.commands&permissions=580817018539072
   ```
   (View Channels, Send Messages (+ in threads), Embed Links, Attach Files, Read History, Add Reactions, Create Events, Send Polls, Connect — needed to host events in voice channels.)
6. **Run**: `.venv/bin/python -m filmvale`
7. **Configure in Discord** (requires *Manage Server*):
   - `/settings autoadd add channel:#movie-links`
   - `/settings timezone zone:America/New_York` — used to interpret `/schedule` times
   - `/settings event-channel channel:🔊 Movie Night` — optional default venue for events

## Migrating from WatchList

Run `/watchlist export` in the original bot, download the `.json`, then `/import file:<that file>`. Titles, links, requester, request date, tags, watched status, runtime, rating, poster, description and TMDB IDs carry over. The original bot stores the content type as a tag (`Movie`/`TVShow`/`YouTube`); that becomes the entry type here and is removed from the tags. With `enrich:True` (default) missing runtimes, genres, episode counts, etc. are filled from TMDB.

## Notes

- TMDB's API terms forbid caching their data for more than 6 months, so Filmvale re-fetches each entry's TMDB details once they're ~5 months old (checked every 6 hours). If a title has been removed from TMDB — or no TMDB key is configured — its cached TMDB details (description, poster, runtime, rating, genres…) are cleared once they pass 6 months; your own data (title, tags, who added it, watched status) is never touched.
- Data lives in a single SQLite file (`filmvale.db`); each server has its own list.
- Removing an entry is limited to whoever added it or members with *Manage Messages*. `/import` and `/settings` default to *Manage Server*; `/schedule` to *Create Events*. Server admins can change these under *Server Settings → Integrations*.
- Discord poll limits: 10 options, 55 characters per option, 1 hour – 32 days.
- Tests: `.venv/bin/pip install pytest pytest-asyncio && .venv/bin/python -m pytest`

## Attribution

<img src="filmvale/assets/tmdb_logo_short.svg" alt="TMDB logo" height="14">

Movie and TV metadata and posters come from [The Movie Database (TMDB)](https://www.themoviedb.org/). Filmvale uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB.

TMDB's license is for non-commercial use only. If you run your own copy, you need your own TMDB API key and must follow the [TMDB API Terms of Use](https://www.themoviedb.org/api-terms-of-use).

## License

[MIT](LICENSE)
