import json

import pytest

import build
import ygjson
from test_ygjson import ARCHETYPES, CARDS, ERAS, LEGALITY, SEALED, SETS


@pytest.fixture
def data(monkeypatch):
    monkeypatch.setattr(ygjson, "load_sets", lambda: SETS)
    monkeypatch.setattr(ygjson, "load_eras", lambda: ERAS)
    monkeypatch.setattr(ygjson, "load_cards", lambda: CARDS)
    monkeypatch.setattr(ygjson, "load_archetypes", lambda: ARCHETYPES)
    monkeypatch.setattr(ygjson, "load_sealed", lambda: SEALED)
    monkeypatch.setattr(ygjson, "load_legality", lambda: LEGALITY)


def test_without_a_cache_meta_has_no_sources(data, tmp_path):
    docs = build.build("0.0.0-dev", "2026-10-28", tmp_path)
    assert set(docs) == {"AllSets", "AllCards", "AllPrintings", "AllArchetypes", "AllProducts", "Legality"}
    assert all(d["meta"] == {"version": "0.0.0-dev", "date": "2026-10-28"} for d in docs.values())


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
