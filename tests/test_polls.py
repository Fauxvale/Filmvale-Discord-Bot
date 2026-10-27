from filmvale.cogs.polls import build_poll
from filmvale.models import Item


def test_polls_allow_multiple_votes_by_default():
    assert build_poll([Item(title="A"), Item(title="B")], "Q?").multiple is True
    assert build_poll([Item(title="A"), Item(title="B")], "Q?", multiple=False).multiple is False
