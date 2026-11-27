import json
import uuid

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
