import subprocess

import pytest

import ids
import refresh_summary
import ygjson


def live(*ids_):
    return {i: {"id": i, "status": "live"} for i in ids_}


def snapshot(ledger=None, events=(), reviews=None, sources=None):
    return {"ledger": {k: {} for k in ids.KINDS} | (ledger or {}), "events": list(events),
            "reviews": reviews or {}, "sources": sources or {}}


BAN = {"card": "1", "format": "tcg", "status": "banned", "effective": "2026-12-01", "source": "ygoprodeck"}
UNDATED = {"card": "2", "format": "goat", "status": "limited", "inForceBy": "2026-11-27", "source": "ygoprodeck"}


def test_ids_added_and_retired_per_kind():
    before = snapshot({"cards": live("a", "b"), "prints": live("p")})
    after = snapshot({"cards": {**live("a", "c"), "b": {"id": "b", "status": "retired"}},
                      "prints": {"p": {"id": "p", "status": "retired"}}})
    text = refresh_summary.body(before, after, {}, "2026-11-30")
    assert "| cards | 2 | 1 | 1 |" in text  # a and c live; c added; b retired
    assert "| prints | 1 → 0 (-1) | 0 | 1 |" in text
    assert "| sets | 0 | 0 | 0 |" in text


def test_ban_list_events_added_and_removed_name_the_card():
    before = snapshot(events=[{**BAN, "status": "limited"}])
    after = snapshot(events=[BAN, UNDATED])
    text = refresh_summary.body(before, after, {"1": "Pot of Greed"}, "2026-11-30")
    assert "2 events added, 1 removed." in text
    assert "| Pot of Greed | tcg | banned | 2026-12-01 | ygoprodeck |" in text
    assert "| 2 | goat | limited | in force by 2026-11-27 | ygoprodeck |" in text  # no name: the id
    assert "| Pot of Greed | tcg | limited | 2026-12-01 | ygoprodeck |" in text.split("Removed:")[1]


def test_a_long_ban_list_is_cut_and_counted():
    after = snapshot(events=[{**BAN, "card": str(i)} for i in range(refresh_summary.SHOWN + 5)])
    assert "| … and 5 more | | | | |" in refresh_summary.body(snapshot(), after, {}, "2026-11-30")


def test_review_counts_and_sources_before_and_after():
    before = snapshot(reviews={"tcgplayer-2": {"unmatched": [1, 2], "groups": [1]}},
                      sources={"tcgcsv": {"modifiedOn": "2026-11-05"}, "ygojson": {"commit": "a", "increment": 1}})
    after = snapshot(reviews={"tcgplayer-2": {"unmatched": [1], "groups": [1]}, "ids": {"renames": []}},
                     sources={"tcgcsv": {"modifiedOn": "2026-11-26"}, "ygojson": {"commit": "a", "increment": 1}})
    text = refresh_summary.body(before, after, {}, "2026-11-30")
    assert "| tcgplayer-2 | unmatched | 2 → 1 (-1) |" in text
    assert "| tcgplayer-2 | groups" not in text and "| ids | renames" not in text
    assert "2 other review counts unchanged." in text
    assert "All 0 review counts unchanged." in refresh_summary.body(snapshot(), snapshot(), {}, "2026-11-30")
    assert "| tcgcsv | modifiedOn 2026-11-05 | modifiedOn 2026-11-26 |" in text
    assert "| ygojson | commit a, increment 1 | unchanged |" in text
    assert "| yugipedia | — | unchanged |" in text


@pytest.fixture
def repo(tmp_path, monkeypatch):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "test")
    for path in ("sets/sets.json", "data/cards/000.json", "sources.json", "review/ids.json"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("[]\n")
    git("add", ".")
    git("commit", "-q", "-m", "data")
    monkeypatch.setattr(ygjson, "ROOT", tmp_path)
    return tmp_path


def test_nothing_changed_when_only_sources_and_review_moved(repo):
    assert not refresh_summary.data_changed("HEAD")
    (repo / "sources.json").write_text('{"tcgcsv": {}}\n')
    (repo / "review" / "ids.json").write_text("[1]\n")
    assert not refresh_summary.data_changed("HEAD")


@pytest.mark.parametrize("path", ["sets/sets.json", "data/cards/000.json", "data/cards/001.json", "ids/prints.json"])
def test_a_changed_or_new_data_file_is_a_change(repo, path):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text("[1]\n")
    assert refresh_summary.data_changed("HEAD")
