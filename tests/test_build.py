import copy
import json
import re

import pytest
from test_ygjson import ARCHETYPES, CARDS, ERAS, LEGALITY, SEALED, SETS

import build
import ids
import ygjson


@pytest.fixture
def data(monkeypatch):
    monkeypatch.setattr(ygjson, "load_sets", lambda: SETS)
    monkeypatch.setattr(ygjson, "load_eras", lambda: ERAS)
    monkeypatch.setattr(ygjson, "load_cards", lambda: CARDS)
    monkeypatch.setattr(ygjson, "load_archetypes", lambda: ARCHETYPES)
    monkeypatch.setattr(ygjson, "load_sealed", lambda: SEALED)
    monkeypatch.setattr(ygjson, "load_legality", lambda: LEGALITY)
    ledger = ids.run({k: {} for k in ids.KINDS}, SETS, CARDS, ARCHETYPES, SEALED, ({}, {}), {})[0]
    monkeypatch.setattr(ids, "load_ledger", lambda: ledger)
    monkeypatch.setattr(ids, "load_hand", lambda: ({}, {}))
    return ledger


def test_without_a_cache_meta_has_no_sources(data, tmp_path):
    docs = build.build("0.0.0-dev", "2026-10-28", tmp_path)
    assert set(docs) == {"AllSets", "AllCards", "AllPrintings", "AllArchetypes", "AllProducts", "Legality", "Ids"}
    assert all(d["meta"] == {"version": "0.0.0-dev", "date": "2026-10-28", "idsVersion": 1} for d in docs.values())


def test_every_file_shares_one_meta_and_the_documented_keys(data, tmp_path):
    docs = build.build("0.1.0", "2026-10-28", tmp_path)
    assert len({json.dumps(d["meta"], sort_keys=True) for d in docs.values()}) == 1
    assert list(docs["AllSets"]["data"]) == ["legend-of-blue-eyes-white-dragon"]
    assert list(docs["AllCards"]["data"]) == ["46986414"]
    assert len(docs["AllPrintings"]["data"]) == 3  # 2 editions of the first print, 1 of the second
    assert list(docs["AllArchetypes"]["data"]) == ["dark-magician"]
    assert list(docs["AllProducts"]["data"]) == ["lob-booster-pack"]
    assert set(docs["Legality"]["data"]) == {"formats", "events"}


def test_sources_come_from_whichever_cache_files_exist(data, tmp_path):
    (tmp_path / "ygoprodeck").mkdir()
    (tmp_path / "ygoprodeck" / "dbver.json").write_text('[{"database_version": "147.60", "last_update": "x"}]')
    (tmp_path / "ygojson").mkdir()
    (tmp_path / "ygojson" / "meta.json").write_text('{"increment": 1559}')
    assert build.build("0.1.0", "2026-10-28", tmp_path)["AllSets"]["meta"]["sources"] == {"ygoprodeck": "147.60", "ygojson": 1559}
    (tmp_path / "tcgcsv").mkdir()
    (tmp_path / "tcgcsv" / "2_groups.json").write_text(json.dumps({"results": [
        {"modifiedOn": "2026-08-25T20:31:08.153"}, {"modifiedOn": "2026-10-27T18:09:35.5"}]}))
    assert build.build("0.1.0", "2026-10-28", tmp_path)["Legality"]["meta"]["sources"]["tcgcsv"] == "2026-10-27"


def test_invalid_data_is_refused(data, monkeypatch, tmp_path):
    bad = {"046": {"cards": [{**CARDS["046"]["cards"][0], "archetypes": ["no-such-archetype"]}]}}
    monkeypatch.setattr(ygjson, "load_cards", lambda: bad)
    with pytest.raises(SystemExit) as e:
        build.build("0.1.0", "2026-10-28", tmp_path)
    assert "refusing to build" in str(e.value) and "no-such-archetype" in str(e.value)


def test_data_the_ledger_does_not_match_is_refused(data, monkeypatch, tmp_path):
    ledger = {**data, "cards": {"other": {**data["cards"]["46986414"], "id": "other"}}}
    monkeypatch.setattr(ids, "load_ledger", lambda: ledger)
    with pytest.raises(SystemExit) as e:
        build.build("0.1.0", "2026-10-28", tmp_path)
    assert "refusing to build" in str(e.value) and "card '46986414': no live ledger entry" in str(e.value)


PRINTING_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:en:(first|unlimited|limited)$")


def test_release_printings_are_keyed_by_uuid(data, tmp_path):
    docs = build.build("0.1.0", "2026-10-28", tmp_path)
    printings = docs["AllPrintings"]["data"]
    assert len(printings) == 3 and all(PRINTING_ID.match(k) and k == r["id"] for k, r in printings.items())
    by_uuid = {e["id"]: e["key"] for e in data["prints"].values()}
    for r in printings.values():
        assert r["printKey"] == by_uuid[r["print"]]
        assert r["key"] == f"{r['printKey']}:en:{r['edition']}"  # the old readable id
        assert r["id"] == f"{r['print']}:en:{r['edition']}"
    assert set(docs["AllCards"]["data"]["46986414"]["prints"]) == set(by_uuid)


def test_ids_json_ships_the_whole_ledger(data, tmp_path):
    docs = build.build("0.1.0", "2026-10-28", tmp_path)
    assert docs["Ids"]["data"] == data
    assert set(docs["Ids"]["data"]) == set(ids.KINDS)


def test_meta_carries_ids_version(data, tmp_path):
    docs = build.build("0.1.0", "2026-10-28", tmp_path)
    assert all(d["meta"]["idsVersion"] == 1 for d in docs.values())


def test_sealed_contents_point_at_print_uuids(data, monkeypatch, tmp_path):
    key = next(iter(data["prints"].values()))["key"]
    sealed = copy.deepcopy(SEALED)
    sealed[next(iter(sealed))]["products"][0]["contents"]["cards"] = [{"print": key, "count": 1}]
    monkeypatch.setattr(ygjson, "load_sealed", lambda: sealed)
    ledger = ids.run({k: {} for k in ids.KINDS}, SETS, CARDS, ARCHETYPES, sealed, ({}, {}), {})[0]
    monkeypatch.setattr(ids, "load_ledger", lambda: ledger)
    item = build.build("0.1.0", "2026-10-28", tmp_path)["AllProducts"]["data"]["lob-booster-pack"]["contents"]["cards"][0]
    assert item["print"] == next(e["id"] for e in ledger["prints"].values() if e["key"] == key)
