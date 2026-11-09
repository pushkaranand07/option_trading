"""E-banners-text: the server's store_problem is already a full message (Track A's MESSAGES), so the page shows it as
it is, once, after a short label: no second sentence of its own, no "..", and no backup claim the server did not make."""

import json

import pytest

from tests.test_ui_regressions import pytestmark as _needs_node, render  # same Node requirement

pytestmark = _needs_node

DAMAGED = ("The trade record file trades.json is damaged and cannot be read (Expecting value: line 1 column 1 (char 0)). "
           "A copy was saved as trades.damaged-20261109-101500.json. Nothing will be written to the trade record until "
           "the file is fixed or restored.")
UNREADABLE = ("The trade record file trades.json cannot be opened ([Errno 13] Permission denied). Nothing will be "
              "written to the trade record until it can be read again.")


def store_banner(problem):
    return json.loads(render("JSON.stringify(bannerTexts(ARGS[0]))", {"store_problem": problem}))["store"]


@pytest.mark.unit
@pytest.mark.parametrize("problem", [DAMAGED, UNREADABLE])
def test_the_store_banner_shows_the_servers_message_once_and_adds_nothing(problem):
    shown = store_banner(problem)
    assert shown == f"Trade record problem: {problem}"
    assert ".." not in shown and shown.count("Nothing will be written") == 1


@pytest.mark.unit
def test_an_unreadable_file_is_not_said_to_have_a_backup():
    shown = store_banner(UNREADABLE).lower()
    assert "copy" not in shown and "backup" not in shown
