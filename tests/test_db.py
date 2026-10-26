import pytest

from filmvale.db import Database
from filmvale.models import Item


@pytest.fixture
async def db():
    d = Database(":memory:")
    await d.connect()
    yield d
    await d.close()


async def test_crud_and_duplicates(db):
    a = await db.add_item(Item(title="Alien", guild_id=1, imdb_id="tt0078748", tags=["Horror"]))
    await db.add_item(Item(title="Up", guild_id=1, kind="movie", watched=True))
    await db.add_item(Item(title="Other server", guild_id=2))
    assert a.id and a.tags == ["Horror"]
    assert await db.find_duplicate(Item(title="whatever", guild_id=1, imdb_id="tt0078748"))
    assert not await db.find_duplicate(Item(title="whatever", guild_id=2, imdb_id="tt0078748"))
    assert await db.find_duplicate(Item(title="up", guild_id=1))
    assert [i.title for i in await db.list_items(1)] == ["Alien"]
    assert len(await db.list_items(1, watched=None)) == 2
    assert [i.title for i in await db.list_items(1, tag="horror")] == ["Alien"]
    assert len(await db.random_items(1, 5, watched=None)) == 2
    a.watched = True
    await db.update_item(a)
    assert (await db.get_item(1, a.id)).watched
    assert await db.all_tags(1) == ["Horror"]
