import copy
import json
import re

import pytest
from test_ygjson import ARCHETYPES, CARDS, ERAS, LEGALITY, SEALED, SETS

import build
import decisions
import ids
import sources
import ygjson

REVIEWS = {"tcgplayer-2": {"unmatched": [{"productId": 1}, {"productId": 2}], "groups": [],
                           "ignored": {"unmatched": [{"productId": 3}]}},
           "rarities": {"duplicateRows": 51, "unknown": [{"rarity": "New"}]}}
MANIFEST = {"ygoprodeck": {"databaseVersion": "147.67", "lastUpdate": "2026-11-04 16:00:24"},
            "ygojson": {"commit": "5d97ede58b68994c3e99a43d419ed5d2c44c7284", "increment": 1559},
            "tcgcsv": {"modifiedOn": "2026-11-05"}, "yugipedia": {"pages": 1216, "fetchedThrough": "2026-11-05"}}


@pytest.fixture
def data(monkeypatch):
    monkeypatch.setattr(ygjson, "load_sets", lambda: SETS)
    monkeypatch.setattr(ygjson, "load_eras", lambda: ERAS)
    monkeypatch.setattr(ygjson, "load_cards", lambda: CARDS)
    monkeypatch.setattr(ygjson, "load_archetypes", lambda: ARCHETYPES)
    monkeypatch.setattr(ygjson, "load_sealed", lambda: SEALED)
    monkeypatch.setattr(ygjson, "load_legality", lambda: LEGALITY)
    monkeypatch.setattr(sources, "load", lambda: copy.deepcopy(MANIFEST))
    monkeypatch.setattr(decisions, "load_reviews", lambda: copy.deepcopy(REVIEWS))
    ledger = ids.run({k: {} for k in ids.KINDS}, SETS, CARDS, ARCHETYPES, SEALED, ({}, {}), {})[0]
    monkeypatch.setattr(ids, "load_ledger", lambda: ledger)
    monkeypatch.setattr(ids, "load_hand", lambda: ({}, {}))
    return ledger


def test_meta_sources_is_the_committed_manifest(data):
    docs = build.build("0.0.0-dev", "2026-10-28")
    assert set(docs) == {"AllSets", "AllCards", "AllPrintings", "AllArchetypes", "AllProducts", "Legality", "Ids"}
    counts = {"rarities.unknown": 1, "tcgplayer-2.groups": 0, "tcgplayer-2.unmatched": 2}  # ignored items left out
    assert all(d["meta"] == {"version": "0.0.0-dev", "date": "2026-10-28", "sources": MANIFEST, "idsVersion": 2,
                             "reviewCounts": counts} for d in docs.values())


@pytest.mark.parametrize("manifest", [{}, {**MANIFEST, "ygojson": {"commit": "main", "increment": 1559}}])
def test_a_missing_or_malformed_manifest_is_refused(data, monkeypatch, manifest):
    monkeypatch.setattr(sources, "load", lambda: manifest)
    with pytest.raises(SystemExit) as e:
        build.build("0.1.0", "2026-10-28")
    assert "sources.json" in str(e.value)


def test_every_file_shares_one_meta_and_the_documented_keys(data):
    docs = build.build("0.1.0", "2026-10-28")
    assert len({json.dumps(d["meta"], sort_keys=True) for d in docs.values()}) == 1
    assert list(docs["AllSets"]["data"]) == ["legend-of-blue-eyes-white-dragon"]
    assert list(docs["AllCards"]["data"]) == ["46986414"]
    assert len(docs["AllPrintings"]["data"]) == 3  # 2 editions of the first print, 1 of the second
    assert list(docs["AllArchetypes"]["data"]) == ["dark-magician"]
    assert list(docs["AllProducts"]["data"]) == ["lob-booster-pack"]
    assert set(docs["Legality"]["data"]) == {"formats", "events"}


def test_invalid_data_is_refused(data, monkeypatch):
    bad = {"046": {"cards": [{**CARDS["046"]["cards"][0], "archetypes": ["no-such-archetype"]}]}}
    monkeypatch.setattr(ygjson, "load_cards", lambda: bad)
    with pytest.raises(SystemExit) as e:
        build.build("0.1.0", "2026-10-28")
    assert "refusing to build" in str(e.value) and "no-such-archetype" in str(e.value)


def test_data_the_ledger_does_not_match_is_refused(data, monkeypatch):
    ledger = {**data, "cards": {"other": {**data["cards"]["46986414"], "id": "other"}}}
    monkeypatch.setattr(ids, "load_ledger", lambda: ledger)
    with pytest.raises(SystemExit) as e:
        build.build("0.1.0", "2026-10-28")
    assert "refusing to build" in str(e.value) and "card '46986414': no live ledger entry" in str(e.value)


PRINTING_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:en:(first|unlimited|limited)$")


def test_release_printings_are_keyed_by_uuid(data):
    docs = build.build("0.1.0", "2026-10-28")
    printings = docs["AllPrintings"]["data"]
    assert len(printings) == 3 and all(PRINTING_ID.match(k) and k == r["id"] for k, r in printings.items())
    by_uuid = {e["id"]: e["key"] for e in data["prints"].values()}
    for r in printings.values():
        assert r["printKey"] == by_uuid[r["print"]]
        assert r["key"] == f"{r['printKey']}:en:{r['edition']}"  # the old readable id
        assert r["id"] == f"{r['print']}:en:{r['edition']}"
    assert set(docs["AllCards"]["data"]["46986414"]["prints"]) == set(by_uuid)


def test_ids_json_ships_the_whole_ledger(data):
    docs = build.build("0.1.0", "2026-10-28")
    assert docs["Ids"]["data"] == data
    assert set(docs["Ids"]["data"]) == set(ids.KINDS)


def test_build_meta_ids_version_is_2(data):
    docs = build.build("0.1.0", "2026-10-28")
    assert all(d["meta"]["idsVersion"] == 2 for d in docs.values())


def test_sealed_contents_point_at_print_uuids(data, monkeypatch):
    key = next(iter(data["prints"].values()))["key"]
    sealed = copy.deepcopy(SEALED)
    sealed[next(iter(sealed))]["products"][0]["contents"]["cards"] = [{"print": key, "count": 1}]
    monkeypatch.setattr(ygjson, "load_sealed", lambda: sealed)
    ledger = ids.run({k: {} for k in ids.KINDS}, SETS, CARDS, ARCHETYPES, sealed, ({}, {}), {})[0]
    monkeypatch.setattr(ids, "load_ledger", lambda: ledger)
    item = build.build("0.1.0", "2026-10-28")["AllProducts"]["data"]["lob-booster-pack"]["contents"]["cards"][0]
    assert item["print"] == next(e["id"] for e in ledger["prints"].values() if e["key"] == key)
