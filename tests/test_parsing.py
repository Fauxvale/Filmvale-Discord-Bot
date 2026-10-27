import json
from datetime import datetime, timezone

import pytest

from filmvale.exporters import to_json, to_markdown, to_text
from filmvale.importers import parse_date, parse_file, parse_runtime
from filmvale.metadata import find_links, parse_link
from filmvale.models import Item
from filmvale.timeparse import parse_when

WATCHLISTBOT_EXPORT = {
    "type": "watchlist-export",
    "scope": "guild",
    "scope_id": 1,
    "exported_at": "2026-10-26T22:25:51.499140+00:00",
    "watchlist": [
        {
            "Name": "The Room", "URL": "https://www.imdb.com/title/tt0368226/", "Requester": "<@111>",
            "RequestTime": "07 Jun 2026", "Tags": ["Movie", "Drama"], "PosterURL": "https://img/x.jpg",
            "Release Date": "27 Jun 2003", "Runtime": "99 min", "Rating": "3.6", "Seasons": None, "Years": None,
            "Description": "Oh hi Mark.", "Channel": None, "View Count": None, "Watched": "Yes",
            "TMDB ID": 17473, "TMDB Media Type": "movie",
        },
        {
            "Name": "Among Us", "URL": "https://www.imdb.com/title/tt28230655/", "Requester": "<@222>",
            "RequestTime": "08 Jun 2026", "Tags": ["TVShow", "Animation"], "PosterURL": "N/A",
            "Release Date": "2026-05-25", "Runtime": "N/A", "Rating": "N/A", "Seasons": "N/A",
            "Years": "2024–Present", "Description": "N/A", "Channel": None, "View Count": None,
            "Watched": "No", "TMDB ID": None, "TMDB Media Type": "tv",
        },
        {
            "Name": "Saying Fork", "URL": "https://www.youtube.com/watch?v=WQ-5_I15gEg", "Requester": "<@111>",
            "RequestTime": "08 Jun 2026", "Tags": ["YouTube"], "PosterURL": None, "Release Date": "07 Jun 2026",
            "Runtime": "30m:58s", "Rating": None, "Seasons": None, "Years": None, "Description": None,
            "Channel": "Daniel Hentschel", "View Count": "15,298", "Watched": "Yes",
            "TMDB ID": None, "TMDB Media Type": None,
        },
    ],
}


@pytest.mark.parametrize("url,source,value,hint", [
    ("https://www.imdb.com/title/tt0084787/?ref_=nv", "imdb", "tt0084787", None),
    ("https://m.imdb.com/de/title/tt0084787", "imdb", "tt0084787", None),
    ("https://www.themoviedb.org/movie/1091-the-thing", "tmdb", "1091", "movie"),
    ("https://www.themoviedb.org/tv/1399-game-of-thrones", "tmdb", "1399", "series"),
    ("https://thetvdb.com/series/breaking-bad", "tvdb_slug", "breaking-bad", "series"),
    ("https://thetvdb.com/?tab=series&id=81189", "tvdb", "81189", "series"),
    ("https://thetvdb.com/dereferrer/series/81189", "tvdb", "81189", "series"),
    ("https://youtu.be/dQw4w9WgXcQ?t=5", "youtube_video", "dQw4w9WgXcQ", None),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123", "youtube_video", "dQw4w9WgXcQ", None),
    ("https://youtube.com/shorts/dQw4w9WgXcQ", "youtube_video", "dQw4w9WgXcQ", None),
    ("https://www.youtube.com/playlist?list=PLabc-123", "youtube_playlist", "PLabc-123", None),
    ("https://letterboxd.com/film/the-thing/", "letterboxd", "https://letterboxd.com/film/the-thing/", "movie"),
])
def test_parse_link(url, source, value, hint):
    link = parse_link(url)
    assert (link.source, link.value, link.hint) == (source, value, hint)


def test_unsupported_and_message_scan():
    assert parse_link("https://example.com/foo") is None
    msg = "watch this (https://www.imdb.com/title/tt0084787/) and <https://youtu.be/dQw4w9WgXcQ>, also imdb.com/title/tt0084787"
    assert [l.value for l in find_links(msg)] == ["tt0084787", "dQw4w9WgXcQ"]


@pytest.mark.parametrize("raw,minutes", [
    ("100 min", 100), ("30m:58s", 31), ("1h 45m", 105), ("2h", 120), ("45:10", 45),
    ("1:45:00", 105), ("N/A", None), (None, None), (95, 95),
])
def test_parse_runtime(raw, minutes):
    assert parse_runtime(raw) == minutes


def test_parse_date_formats():
    assert parse_date("07 Jun 2026").date().isoformat() == "2026-06-07"
    assert parse_date("2026-05-25").date().isoformat() == "2026-05-25"
    assert parse_date("N/A") is None


def test_watchlistbot_import():
    movie, show, video = parse_file("export.json", json.dumps(WATCHLISTBOT_EXPORT).encode())
    assert (movie.kind, movie.title, movie.imdb_id, movie.tmdb_id) == ("movie", "The Room", "tt0368226", 17473)
    assert movie.runtime == 99 and movie.rating == 3.6 and movie.year == 2003 and movie.watched
    assert movie.tags == ["Drama"] and movie.added_by_id == 111
    assert movie.added_at == datetime(2026, 6, 7, tzinfo=timezone.utc)
    assert show.kind == "series" and show.runtime is None and show.seasons is None and show.poster_url is None
    assert show.overview is None and not show.watched
    assert video.kind == "youtube" and video.youtube_id == "WQ-5_I15gEg" and video.runtime == 31
    assert video.creator == "Daniel Hentschel" and video.poster_url.endswith("WQ-5_I15gEg/hqdefault.jpg")


def test_imdb_csv_import():
    csv_text = (
        "Position,Const,Created,Modified,Description,Title,URL,Title Type,IMDb Rating,Runtime (mins),Year,Genres,Num Votes,Release Date,Directors,Your Rating,Date Rated\n"
        '1,tt0084787,2024-01-02,2024-01-02,,The Thing,https://www.imdb.com/title/tt0084787/,Movie,8.2,109,1982,"Horror, Sci-Fi",400000,1982-06-25,John Carpenter,,\n'
        "2,tt0903747,2024-01-03,2024-01-03,,Breaking Bad,https://www.imdb.com/title/tt0903747/,TV Series,9.5,49,2008,Drama,2000000,2008-01-20,,10,2024-02-01\n"
    )
    thing, bb = parse_file("WATCHLIST.csv", csv_text.encode())
    assert thing.kind == "movie" and thing.runtime == 109 and thing.genres == ["Horror", "Sci-Fi"] and not thing.watched
    assert bb.kind == "series" and bb.watched


def _sample_items():
    return [
        Item(title="The Thing", kind="movie", year=1982, runtime=109, imdb_id="tt0084787", metadata_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
             url="https://www.imdb.com/title/tt0084787/", genres=["Horror"], tags=["halloween"],
             added_by_name="alice", added_at=datetime(2026, 10, 1, tzinfo=timezone.utc)),
        Item(title="Severance", kind="series", year=2022, seasons=2, tmdb_id=95396, watched=True,
             url="https://www.themoviedb.org/tv/95396"),
        Item(title="Some Video", kind="youtube", youtube_id="dQw4w9WgXcQ",
             url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        Item(title="Untitled Thing (2019)", kind="other"),
    ]


def test_text_export_round_trip():
    text = to_text(_sample_items(), "Test Server")
    assert "1. [ ] The Thing (1982)" in text and "[x] Severance (2022)" in text
    parsed = parse_file("export.txt", text.encode())
    assert len(parsed) == 4
    back = {i.title: i for i in parsed}
    assert back["The Thing"].imdb_id == "tt0084787" and back["The Thing"].year == 1982
    assert back["Severance"].kind == "series" and back["Severance"].watched
    assert back["Some Video"].kind == "youtube" and back["Some Video"].youtube_id == "dQw4w9WgXcQ"
    assert back["Untitled Thing"].kind == "other"


def test_markdown_export_round_trip():
    items = _sample_items()
    items[0].title = "The [Thing]*"
    text = to_markdown(items, "Test Server")
    assert "## 🎬 Movies (1)" in text
    assert "- [ ] **[The \\[Thing\\]\\*](<https://www.imdb.com/title/tt0084787/>)** (1982)" in text
    assert "- [x] **[Severance](<https://www.themoviedb.org/tv/95396>)** (2022)" in text
    parsed = parse_file("export.md", text.encode())
    assert len(parsed) == 4
    back = {i.title: i for i in parsed}
    assert back["The [Thing]*"].imdb_id == "tt0084787" and back["The [Thing]*"].year == 1982
    assert back["Severance"].kind == "series" and back["Severance"].watched
    assert back["Some Video"].kind == "youtube" and back["Some Video"].youtube_id == "dQw4w9WgXcQ"
    assert back["Untitled Thing"].kind == "other" and back["Untitled Thing"].year == 2019


def test_json_export_round_trip():
    original = _sample_items()
    back = parse_file("backup.json", to_json(original, 1).encode())
    assert [(i.title, i.kind, i.watched, i.tags) for i in back] == [(i.title, i.kind, i.watched, i.tags) for i in original]
    assert back[0].added_at == original[0].added_at


def test_plain_text_list():
    items = parse_file("list.txt", b"- Alien (1979)\n* [x] Aliens\n3. https://youtu.be/dQw4w9WgXcQ\n\n# comment\n")
    assert [(i.title, i.year, i.watched) for i in items[:2]] == [("Alien", 1979, False), ("Aliens", None, True)]
    assert items[2].kind == "youtube"


def test_parse_when():
    now = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)  # a Monday
    when = parse_when("friday 8pm", "America/New_York", now=now)
    assert when.isoformat() == "2026-10-31T00:00:00+00:00"  # 8pm EDT = midnight UTC
    assert parse_when("2026-11-01 20:00", "UTC").isoformat() == "2026-11-01T20:00:00+00:00"
    assert parse_when("<t:1793577600:F>").timestamp() == 1793577600
    assert parse_when("<t:1793386800>", "America/New_York").timestamp() == 1793386800  # timezone ignored
    assert parse_when("movie night <t:1793386800:R> (friday)").timestamp() == 1793386800
    assert parse_when("Friday, October 30, 2026 at 12:00 PM", "America/Los_Angeles").timestamp() == 1793386800
    assert parse_when("not a date at all", "UTC") is None
