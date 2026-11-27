import json
import uuid

import pytest

import ids

PRINT = {"id": "7d674373-b170-5fd8-ab33-29bacad29ffa", "key": "lob:89631139:LOB-001:ultra_rare", "formerKeys": [],
         "status": "live", "successors": [], "products": [1, 2]}


def test_mint_is_uuid5_of_the_birth_key():
    assert ids.mint("lob:89631139:LOB-001:ultra_rare", set()) == str(uuid.uuid5(ids.YGJSON_NAMESPACE, "lob:89631139:LOB-001:ultra_rare"))


def test_mint_skips_a_taken_id():
    first = ids.mint("k", set())
    assert ids.mint("k", {first}) == str(uuid.uuid5(ids.YGJSON_NAMESPACE, "k#2"))
    second = ids.mint("k", {first})
    assert ids.mint("k", {first, second}) == str(uuid.uuid5(ids.YGJSON_NAMESPACE, "k#3"))


def test_namespace_is_the_project_url_uuid():
    assert ids.YGJSON_NAMESPACE == uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/ArthurG-data/ygjson")


def test_ledger_round_trips_sorted(tmp_path):
    ledger = {k: {} for k in ids.KINDS}
    ledger["prints"] = {"b": {"id": "b", "key": "x", "formerKeys": [], "status": "live", "successors": [], "products": []},
                        "a": {"id": "a", "key": "y", "formerKeys": [], "status": "live", "successors": [], "products": []}}
    ids.save_ledger(ledger, tmp_path)
    assert [e["id"] for e in json.loads((tmp_path / "prints.json").read_text())["prints"]] == ["a", "b"]
    assert ids.load_ledger(tmp_path) == ledger


def test_missing_ledger_loads_empty(tmp_path):
    assert ids.load_ledger(tmp_path) == {k: {} for k in ids.KINDS}


def _ledger():
    base = {"status": "live", "successors": []}
    return {
        "prints": {PRINT["id"]: PRINT},
        "printings": {"x": {"id": PRINT["id"] + ":en:first", "key": "k:en:first", "formerIds": ["k:en:first"], **base}},
        "cards": {"1": {"id": "1", "name": "Blue-Eyes", "konamiId": 4007, **base}},
        "sets": {"lob": {"id": "lob", "names": ["Legend of Blue Eyes"], "code": "LOB", "releaseDate": "2002-03-08",
                         "identity": ["a", "b"], **base}},
        "archetypes": {"hero": {"id": "hero", "names": ["HERO"], "identity": ["x"], **base}},
        "sealed": {"1": {"id": "lob-box", "tcgplayerProductId": 5, **base}},
    }


def test_ledger_entries_match_the_schema():
    ledger = _ledger()
    assert ids.schema_errors(ledger) == []
    ledger["prints"][PRINT["id"]] = {**PRINT, "status": "gone"}
    assert ids.schema_errors(ledger)


def test_schema_rejects_a_bad_printing_id():
    ledger = _ledger()
    ledger["printings"]["x"]["id"] = "not-a-uuid:en:first"
    assert ids.schema_errors(ledger)


def test_held_names_and_reserved_cover_live_and_retired_entries():
    ledger = {"sets": {"b": {"id": "b", "names": ["Old", "New"], "status": "live", "successors": []},
                       "a": {"id": "a", "names": ["Gone", "New"], "status": "retired", "successors": []}}}
    assert ids.held_names(ledger, "sets") == {"Old": "b", "New": "a", "Gone": "a"}  # a name under two slugs: smallest
    assert ids.reserved(ledger, "sets") == {"a", "b"}
    assert ids.held_names(ledger, "archetypes") == {} and ids.reserved(ledger, "archetypes") == set()


def _hand_ledger():
    base = {"formerKeys": [], "products": []}
    return {"prints": {
        "live1": {"id": "live1", "key": "k1", "status": "live", "successors": [], **base},
        "gone1": {"id": "gone1", "key": "k2", "status": "retired", "successors": [], **base},
        "gone2": {"id": "gone2", "key": "k3", "status": "retired", "successors": [], **base}}}


def _write_hand(tmp_path, doc):
    path = tmp_path / "ids.json"
    path.write_text(json.dumps(doc))
    return path


def test_hand_entry_without_why_is_refused(tmp_path):
    path = _write_hand(tmp_path, {"_comment": "c", "prints": {"k9": {"id": "gone1", "why": " "}}, "successors": {}})
    with pytest.raises(ValueError, match="k9"):
        ids.load_hand(path)
    path = _write_hand(tmp_path, {"prints": {}, "successors": {"gone1": {"successors": ["live1"]}}})
    with pytest.raises(ValueError, match="gone1"):
        ids.load_hand(path)


def test_missing_hand_file_is_empty(tmp_path):
    assert ids.load_hand(tmp_path / "nope.json") == ({}, {})


def test_hand_may_not_give_a_live_id_to_a_second_print(tmp_path):
    path = _write_hand(tmp_path, {"prints": {"a": {"id": "live1", "why": "w"}, "b": {"id": "ghost", "why": "w"},
                                            "c": {"id": "gone1", "why": "w"}},
                                  "successors": {"live1": {"successors": ["gone1"], "why": "w"},
                                                 "gone2": {"successors": ["ghost"], "why": "w"},
                                                 "gone1": {"successors": ["live1"], "why": "w"}}})
    hand = ids.load_hand(path)
    assert hand == ({"a": "live1", "b": "ghost", "c": "gone1"},
                    {"live1": ["gone1"], "gone2": ["ghost"], "gone1": ["live1"]})
    errors = ids.hand_errors(_hand_ledger(), hand)
    assert len(errors) == 4
    assert any("a" in e and "live1" in e for e in errors)
    assert any("ghost" in e for e in errors)
    assert not any("'c'" in e for e in errors)


def test_hand_successors_override_the_computed_ones():
    entries = _hand_ledger()["prints"]
    out = ids.apply_successors(entries, {"gone1": ["live1"], "live1": ["gone1"]})
    assert out["gone1"]["successors"] == ["live1"]
    assert out["live1"]["successors"] == []
    assert entries["gone1"]["successors"] == []


def test_review_body_is_sorted():
    body = ids.review_body([{"id": "b"}, {"id": "a"}], [{"id": "z"}, {"id": "y"}],
                           [{"from": "q", "to": "r"}, {"from": "p", "to": "s"}])
    assert [r["id"] for r in body["prints"]] == ["a", "b"]
    assert [r["id"] for r in body["cards"]] == ["y", "z"]
    assert [r["from"] for r in body["renames"]] == ["p", "q"]


def test_hand_may_not_give_one_retired_id_to_two_keys():
    errors = ids.hand_errors(_hand_ledger(), ({"a": "gone1", "b": "gone1"}, {}))
    assert len(errors) == 1
    assert "'a'" in errors[0] and "'b'" in errors[0] and "gone1" in errors[0]
