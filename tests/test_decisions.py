import copy
import json

import pytest

import decisions

REVIEW = {"unmatched": [{"productId": 1, "name": "A"}, {"productId": 2, "name": "B"}, {"productId": 3, "name": "C"}],
          "groups": [{"groupId": 9}], "duplicateRows": 51}
IGNORE = {"tcgplayer-2": {"unmatched": [{"match": {"productId": 2}, "why": "a deck box, not a card"}]}}


def test_ignored_items_move_to_the_ignored_section():
    out = decisions.filter_review("tcgplayer-2", copy.deepcopy(REVIEW), IGNORE)
    assert [i["productId"] for i in out["unmatched"]] == [1, 3]
    assert out["ignored"] == {"unmatched": [{"productId": 2, "name": "B"}]}
    assert out["groups"] == REVIEW["groups"] and out["duplicateRows"] == 51


def test_filtering_again_is_a_no_op_and_other_files_are_untouched():
    once = decisions.filter_review("tcgplayer-2", copy.deepcopy(REVIEW), IGNORE)
    # an importer rebuilds its lists from scratch: the old ignored section is replaced, not added to
    assert decisions.filter_review("tcgplayer-2", {**copy.deepcopy(REVIEW), "ignored": once["ignored"]}, IGNORE) == once
    assert decisions.filter_review("sealed", copy.deepcopy(REVIEW), IGNORE) == REVIEW


def test_a_match_on_several_fields_needs_all_of_them():
    ignore = {"x": {"unmatched": [{"match": {"productId": 1, "name": "Z"}, "why": "w"}]}}
    assert "ignored" not in decisions.filter_review("x", copy.deepcopy(REVIEW), ignore)


def test_save_review_writes_the_filtered_body(tmp_path):
    path = tmp_path / "tcgplayer-2.json"
    decisions.save_review(path, copy.deepcopy(REVIEW), IGNORE)
    assert json.loads(path.read_text())["ignored"]["unmatched"][0]["productId"] == 2


def test_review_counts_leave_out_ignored_items_and_numbers():
    reviews = {"tcgplayer-2": decisions.filter_review("tcgplayer-2", copy.deepcopy(REVIEW), IGNORE)}
    assert decisions.review_counts(reviews) == {"tcgplayer-2.groups": 1, "tcgplayer-2.unmatched": 2}


# --- print overrides --------------------------------------------------------------------------------------------

PID = "lob:1:LOB-001:ultra_rare"


def files(**fields):
    return {"001": {"cards": [{"id": "1", "prints": [{"id": PID, "set": "lob", **fields}]}]}}


def test_an_override_sets_the_print_s_editions():
    data = files()
    changed, stale = decisions.apply_print_overrides(data, {"lob": ["first", "unlimited"]},
                                                     {PID: {"editions": ["unlimited"], "why": "w"},
                                                      "gone:1::common": {"editions": ["first"], "why": "w"}})
    assert data["001"]["cards"][0]["prints"][0]["editions"] == ["unlimited"]
    assert (changed, stale) == (1, ["gone:1::common"])
    assert decisions.apply_print_overrides(data, {"lob": ["first", "unlimited"]},
                                           {PID: {"editions": ["unlimited"], "why": "w"}})[0] == 0  # already applied


def test_editions_equal_to_the_set_s_are_left_off_the_print():
    data = files(editions=["limited"])
    decisions.apply_print_overrides(data, {"lob": ["first"]}, {PID: {"editions": ["first"], "why": "w"}})
    assert "editions" not in data["001"]["cards"][0]["prints"][0]


# --- what validate.py reports -----------------------------------------------------------------------------------

SETS = [{"id": "lob", "editions": ["first", "unlimited"]}]


def problems(ignore=None, overrides=None, reviews=None, data=None):
    return decisions.problems(ignore or {}, overrides or {}, reviews or {}, data or files(), SETS)


def test_applied_decisions_are_not_problems():
    reviews = {"tcgplayer-2": decisions.filter_review("tcgplayer-2", copy.deepcopy(REVIEW), IGNORE)}
    assert problems(IGNORE, {PID: {"editions": ["unlimited"], "why": "w"}}, reviews, files(editions=["unlimited"])) == []


@pytest.mark.parametrize("reviews, message", [
    ({"tcgplayer-2": REVIEW}, "{'productId': 2} is still in the list: rerun the importer"),
    ({"tcgplayer-2": {**REVIEW, "unmatched": []}}, "{'productId': 2} matches nothing: the item is gone"),
    ({}, "review/tcgplayer-2.json has no list unmatched"),
])
def test_an_ignore_entry_that_is_stale_or_not_applied_is_reported(reviews, message):
    (problem,) = problems(IGNORE, reviews=reviews)
    assert problem.startswith("ignore.json: tcgplayer-2/unmatched: ") and message in problem


def test_an_ignored_item_whose_entry_was_removed_is_reported():
    reviews = {"tcgplayer-2": decisions.filter_review("tcgplayer-2", copy.deepcopy(REVIEW), IGNORE)}
    (problem,) = problems({}, reviews=reviews)
    assert problem == ("review/tcgplayer-2.json: 1 ignored unmatched items no ignore.json entry accepts any more: "
                       "rerun the importer that writes it")


def test_an_ignore_entry_needs_a_why():
    ignore = {"tcgplayer-2": {"unmatched": [{"match": {"productId": 2}, "why": " "}]}}
    (problem,) = problems(ignore, reviews={"tcgplayer-2": REVIEW})
    assert "needs a non-empty match and why" in problem


@pytest.mark.parametrize("override, data, message", [
    ({"editions": ["first"]}, files(editions=["first"]), "no why"),
    ({"rarity": "common", "why": "w"}, files(), "rarity cannot be overridden (only editions)"),
    ({"editions": ["unlimited"], "why": "w"}, files(), "the print's editions are not the override's: rerun import_tcgcsv"),
])
def test_a_bad_or_unapplied_override_is_reported(override, data, message):
    (problem,) = problems(overrides={PID: override}, data=data)
    assert problem.startswith(f"print_overrides.json: {PID}: ") and message in problem


def test_an_override_naming_no_print_is_reported():
    (problem,) = problems(overrides={"gone:1::common": {"editions": ["first"], "why": "w"}})
    assert "no such print" in problem


def test_an_override_equal_to_the_set_s_editions_is_applied_when_the_print_has_none():
    assert problems(overrides={PID: {"editions": ["first", "unlimited"], "why": "w"}}) == []
