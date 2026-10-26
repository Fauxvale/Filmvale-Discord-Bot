"""Parse watchlist files from other tools into ``Item`` objects.

Supported inputs:
  * WatchList bot (watchlistbot.com) ``/watchlist export`` JSON (and .zip containing it)
  * This bot's own JSON export
  * IMDb list/watchlist CSV exports
  * Plain text: one title or link per line (bullets/numbering/checkboxes are stripped)
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import datetime, timezone

from .metadata import IMDB_RE, find_links
from .models import KINDS, Item

KIND_ALIASES = {
    "movie": "movie", "movies": "movie", "film": "movie", "feature": "movie", "tvmovie": "movie", "video": "movie",
    "tvshow": "series", "tv": "series", "series": "series", "show": "series", "tvseries": "series",
    "tvminiseries": "series", "miniseries": "series", "tvspecial": "series",
    "youtube": "youtube", "yt": "youtube",
    "other": "other",
}

MENTION_RE = re.compile(r"<@!?(\d+)>")


class ImportFormatError(ValueError):
    pass


def _norm_kind(value) -> str | None:
    if not value:
        return None
    key = re.sub(r"[^a-z]", "", str(value).lower())
    return KIND_ALIASES.get(key)


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip().upper() in ("", "N/A", "NONE", "NULL"))


def _int(value) -> int | None:
    if _blank(value):
        return None
    m = re.search(r"\d+", str(value).replace(",", ""))
    return int(m.group()) if m else None


def _float(value) -> float | None:
    if _blank(value):
        return None
    try:
        return float(str(value).split("/")[0])
    except ValueError:
        return None


def parse_runtime(value) -> int | None:
    """'100 min', '30m:58s', '1h 45m', '1:45:00', 'PT1H5M', 95 -> minutes."""
    if _blank(value):
        return None
    if isinstance(value, (int, float)):
        return int(value) or None
    text = str(value).strip().lower()
    if m := re.fullmatch(r"(?:(\d+):)?(\d+):(\d{2})", text):
        h, mi, s = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
        # "45:10" is mm:ss, "1:45:10" is h:mm:ss
        return h * 60 + mi + (1 if s >= 30 else 0) if m.group(1) else mi + (1 if s >= 30 else 0)
    h = re.search(r"(\d+)\s*h", text)
    mi = re.search(r"(\d+)\s*m(?!s)", text)
    s = re.search(r"(\d+)\s*s", text)
    if h or mi:
        total = (int(h.group(1)) * 60 if h else 0) + (int(mi.group(1)) if mi else 0)
        if s and int(s.group(1)) >= 30:
            total += 1
        return total or None
    return _int(text)


_DATE_FORMATS = ("%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%Y")


def parse_date(value) -> datetime | None:
    if _blank(value):
        return None
    if isinstance(value, (int, float)):
        ts = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(ts, timezone.utc)
    text = str(value).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _first_year(value) -> int | None:
    if _blank(value):
        return None
    m = re.search(r"(1[89]\d\d|20\d\d)", str(value))
    return int(m.group(1)) if m else None


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("yes", "true", "1", "y", "watched", "x")


def _split_tags(value) -> list[str]:
    if _blank(value):
        return []
    if isinstance(value, list):
        return [str(t).strip() for t in value if str(t).strip()]
    return [t.strip() for t in str(value).split(",") if t.strip()]


# ── WatchList bot JSON ───────────────────────────────────────────────────


def _from_watchlistbot(entry: dict) -> Item:
    tags = _split_tags(entry.get("Tags"))
    kind = None
    # The original bot stores the content type as one of the tags (Movie / TVShow / YouTube / Other).
    remaining = []
    for t in tags:
        k = _norm_kind(t) if t.lower() in ("movie", "tvshow", "youtube", "other") else None
        if k and not kind:
            kind = k
        elif not k:
            remaining.append(t)
    media_type = entry.get("TMDB Media Type")
    if media_type == "tv":
        kind = "series"
    elif media_type == "movie":
        kind = kind or "movie"
    url = None if _blank(entry.get("URL")) else str(entry["URL"]).strip()
    if not kind:
        kind = "youtube" if url and "youtu" in url else "other"

    release = parse_date(entry.get("Release Date"))
    requester = str(entry.get("Requester") or "")
    mention = MENTION_RE.search(requester)
    imdb = IMDB_RE.search(url or "")
    links = find_links(url or "")
    youtube_id = links[0].value if links and links[0].source.startswith("youtube") else None
    item = Item(
        title=str(entry.get("Name") or url or "Untitled").strip(),
        kind=kind,
        year=release.year if release else _first_year(entry.get("Years")),
        release_date=release.date().isoformat() if release else None,
        runtime=parse_runtime(entry.get("Runtime")),
        seasons=_int(entry.get("Seasons")),
        overview=None if _blank(entry.get("Description")) else entry["Description"],
        poster_url=None if _blank(entry.get("PosterURL")) else entry["PosterURL"],
        rating=_float(entry.get("Rating")),
        creator=None if _blank(entry.get("Channel")) else entry["Channel"],
        url=url,
        imdb_id=imdb.group(1) if imdb else None,
        tmdb_id=_int(entry.get("TMDB ID")),
        youtube_id=youtube_id,
        tags=remaining,
        added_by_id=int(mention.group(1)) if mention else None,
        added_by_name=None if mention or not requester else requester,
        added_at=parse_date(entry.get("RequestTime")),
        watched=_bool(entry.get("Watched")),
    )
    if youtube_id and not item.poster_url and links[0].source == "youtube_video":
        item.poster_url = f"https://i.ytimg.com/vi/{youtube_id}/hqdefault.jpg"
    return item


# ── This bot's own JSON ──────────────────────────────────────────────────


def _from_native(entry: dict) -> Item:
    data = dict(entry)
    for key in ("added_at", "watched_at"):
        data[key] = parse_date(data.get(key))
    data.pop("id", None)
    data.pop("guild_id", None)
    data.pop("event_id", None)
    allowed = Item.__dataclass_fields__.keys()
    item = Item(**{k: v for k, v in data.items() if k in allowed})
    if item.kind not in KINDS:
        item.kind = "other"
    return item


# ── IMDb CSV ─────────────────────────────────────────────────────────────


def _from_imdb_row(row: dict) -> Item:
    imdb_id = row.get("Const", "").strip()
    release = parse_date(row.get("Release Date"))
    return Item(
        title=row.get("Title", "").strip() or imdb_id,
        kind=_norm_kind(row.get("Title Type")) or "movie",
        year=_int(row.get("Year")),
        release_date=release.date().isoformat() if release else None,
        runtime=_int(row.get("Runtime (mins)")),
        rating=_float(row.get("IMDb Rating")),
        genres=_split_tags(row.get("Genres")),
        creator=row.get("Directors") or None,
        url=row.get("URL") or f"https://www.imdb.com/title/{imdb_id}/",
        imdb_id=imdb_id or None,
        added_at=parse_date(row.get("Created")),
        watched=bool(row.get("Your Rating", "").strip()),
    )


def _from_csv(text: str) -> list[Item]:
    reader = csv.DictReader(io.StringIO(text))
    fields = set(reader.fieldnames or [])
    if "Const" in fields and "Title" in fields:
        return [_from_imdb_row(r) for r in reader if r.get("Const")]
    title_key = next((f for f in reader.fieldnames or [] if f.lower() in ("title", "name")), None)
    if not title_key:
        raise ImportFormatError("CSV needs a 'Title' or 'Name' column (or be an IMDb export).")
    items = []
    for r in reader:
        lowered = {k.lower(): v for k, v in r.items() if k}
        if not (lowered.get(title_key.lower()) or "").strip():
            continue
        url = lowered.get("url") or lowered.get("link")
        items.append(Item(
            title=lowered[title_key.lower()].strip(),
            kind=_norm_kind(lowered.get("type") or lowered.get("kind")) or "movie",
            year=_int(lowered.get("year")),
            url=url or None,
            tags=_split_tags(lowered.get("tags")),
            watched=_bool(lowered.get("watched", "")),
        ))
    return items


# ── Plain text ───────────────────────────────────────────────────────────

_LINE_PREFIX = re.compile(r"^\s*(?:[-*•]+|\d+[.)]|\[[ xX✓]?\])\s*")


def _from_text(text: str) -> list[Item]:
    items: list[Item] = []
    section_kind = None
    lines = text.splitlines()
    if lines and lines[0].startswith("FILMVALE WATCHLIST"):
        # Our own export: skip the header block before the first "== SECTION ==" line.
        lines = lines[next((n for n, l in enumerate(lines) if l.startswith("==")), len(lines)):]
    for line in lines:
        if line.startswith(("    ", "\t")):
            # Indented detail lines (as in this bot's .txt export): only the link matters.
            links = find_links(line)
            if links and items and not items[-1].url:
                link = links[0]
                items[-1].url = link.url
                items[-1].imdb_id = link.value if link.source == "imdb" else None
                if link.source.startswith("youtube"):
                    items[-1].youtube_id, items[-1].kind = link.value, "youtube"
                elif link.hint:
                    items[-1].kind = link.hint
            continue
        if m := re.match(r"^==\s*([A-Za-z ]+?)\s*(?:\(\d+\))?\s*==", line):
            section_kind = _norm_kind(m.group(1))
            continue
        watched = bool(re.match(r"^\s*(?:[-*•]+\s*|\d+[.)]\s*)?\[[xX✓]\]", line))
        clean = _LINE_PREFIX.sub("", line).strip()
        clean = _LINE_PREFIX.sub("", clean).strip()  # e.g. "1. [x] Title"
        if not clean or clean.startswith(("#", "==")):
            continue
        if links := find_links(clean):
            link = links[0]
            items.append(Item(
                title=clean.split("http")[0].strip(" -–|") or link.url,
                kind=link.hint or ("youtube" if link.source.startswith("youtube") else section_kind or "movie"),
                url=link.url,
                imdb_id=link.value if link.source == "imdb" else None,
                youtube_id=link.value if link.source.startswith("youtube") else None,
                watched=watched,
            ))
            continue
        year = None
        if m := re.search(r"\((\d{4})\)\s*$", clean):
            year = int(m.group(1))
            clean = clean[: m.start()].strip()
        items.append(Item(title=clean, kind=section_kind or "movie", year=year, watched=watched))
    return items


# ── Entry point ──────────────────────────────────────────────────────────


def _from_json(data) -> list[Item]:
    if isinstance(data, dict) and isinstance(data.get("watchlist"), list):
        return [_from_watchlistbot(e) for e in data["watchlist"] if isinstance(e, dict)]
    if isinstance(data, dict) and data.get("format") == "filmvale":
        return [_from_native(e) for e in data.get("items", [])]
    entries = data if isinstance(data, list) else next(
        (v for v in data.values() if isinstance(v, list)), None
    ) if isinstance(data, dict) else None
    if not entries:
        raise ImportFormatError("Couldn't find a list of entries in that JSON file.")
    if isinstance(entries[0], dict) and "Name" in entries[0]:
        return [_from_watchlistbot(e) for e in entries if isinstance(e, dict)]
    if isinstance(entries[0], dict) and "title" in entries[0]:
        return [_from_native(e) for e in entries if isinstance(e, dict)]
    raise ImportFormatError("Unrecognised JSON layout.")


def parse_file(filename: str, data: bytes) -> list[Item]:
    name = filename.lower()
    if name.endswith(".zip"):
        items: list[Item] = []
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for member in zf.namelist():
                if member.lower().endswith((".json", ".csv", ".txt")) and not member.startswith("__MACOSX"):
                    items.extend(parse_file(member, zf.read(member)))
        if not items:
            raise ImportFormatError("No .json/.csv/.txt watchlist found inside the zip.")
        return items
    text = data.decode("utf-8-sig", errors="replace")
    if name.endswith(".json"):
        try:
            return _from_json(json.loads(text))
        except json.JSONDecodeError as e:
            raise ImportFormatError(f"Invalid JSON: {e}") from e
    if name.endswith(".csv"):
        return _from_csv(text)
    if name.endswith((".txt", ".md")):
        return _from_text(text)
    raise ImportFormatError("Unsupported file type. Use .json, .zip, .csv or .txt.")
