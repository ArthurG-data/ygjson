import gzip
import hashlib
import json
import sqlite3

from test_ygjson import ARCHETYPES, CARDS, LEGALITY, PRINT_A, SEALED, SETS

import ids
import package
import ygjson


def docs():
    ledger = ids.run({k: {} for k in ids.KINDS}, SETS, CARDS, ARCHETYPES, SEALED, ({}, {}), {})[0]
    flat = ygjson.flatten(SETS, CARDS, ARCHETYPES, SEALED, ledger)
    meta = {"version": "1.2.3", "date": "2026-11-27"}
    data = {"AllSets": flat["sets"], "AllCards": flat["cards"], "AllPrintings": flat["printings"],
            "AllArchetypes": flat["archetypes"], "AllProducts": flat["products"], "Legality": LEGALITY, "Ids": ledger}
    return {name: {"meta": meta, "data": body} for name, body in data.items()}


def write(dist):
    for name, doc in docs().items():
        (dist / f"{name}.json").write_text(json.dumps(doc), encoding="utf-8")


def test_the_database_holds_each_record_as_columns_and_the_rest_as_json(tmp_path):
    path = tmp_path / "x.sqlite"
    package.load(docs(), path)
    db = sqlite3.connect(path)
    q = lambda sql, *a: db.execute(sql, a).fetchall()  # noqa: E731
    assert q("SELECT value FROM meta WHERE key = 'version'") == [('"1.2.3"',)]
    assert q("SELECT name, monster_type, atk, json_extract(data, '$.typeline') FROM cards") == [
        ("Dark Magician", "Spellcaster", 2500, '["Spellcaster","Normal"]')]
    assert q("SELECT language, name FROM card_names") == [("en", "Dark Magician")]
    first = q("""SELECT number, edition, tcgplayer_product_id, tcgplayer_subtype, json_extract(data, '$.identifiers')
                 FROM printings WHERE key = ?""", f"{PRINT_A}:en:first")
    assert first == [("LOB-EN005", "first", 10, "1st Edition", '{"tcgplayerProductIds":[10]}')]
    assert "tcgplayerPrice" not in q("SELECT data FROM printings WHERE key = ?", f"{PRINT_A}:en:first")[0][0]
    assert q("SELECT archetype, card FROM archetype_members") == [("dark-magician", "46986414")]
    assert q("SELECT id, category FROM products") == [("lob-booster-pack", "booster_pack")]
    assert q("SELECT card, format, status, effective FROM legality_events") == [("46986414", "tcg", "limited", "2005-03-01")]
    assert q("SELECT kind, status FROM ids WHERE key = ?", PRINT_A) == [("prints", "live")]
    assert q("SELECT count(*) FROM former_keys") == [(0,)]


def test_a_former_key_resolves_to_its_id(tmp_path):
    d = docs()
    entry = next(iter(d["Ids"]["data"]["prints"].values()))
    entry["formerKeys"] = ["old:key"]
    package.load(d, tmp_path / "x.sqlite")
    assert sqlite3.connect(tmp_path / "x.sqlite").execute(
        "SELECT kind, id FROM former_keys WHERE key = 'old:key'").fetchall() == [("prints", entry["id"])]


def test_gzip_is_the_same_bytes_every_time_and_unpacks_to_the_source(tmp_path):
    src = tmp_path / "a.json"
    src.write_text('{"a": 1}', encoding="utf-8")
    package.gzip_file(src, tmp_path / "1.gz")
    package.gzip_file(src, tmp_path / "2.gz")
    assert (tmp_path / "1.gz").read_bytes() == (tmp_path / "2.gz").read_bytes()
    assert gzip.decompress((tmp_path / "1.gz").read_bytes()) == src.read_bytes()


def test_package_writes_the_gzips_the_database_and_checksums_of_every_asset(tmp_path):
    write(tmp_path)
    assets = package.package(tmp_path)
    names = [p.name for p in assets]
    assert "AllPrintings.json" in names and "AllPrintings.json.gz" in names and "ygjson.sqlite.gz" in names
    assert "ygjson.sqlite" not in names and names[-1] == "SHA256SUMS"
    sums = dict(reversed(line.split("  ")) for line in (tmp_path / "SHA256SUMS").read_text().splitlines())
    assert sorted(sums) == sorted(names[:-1])
    assert all(hashlib.sha256((tmp_path / n).read_bytes()).hexdigest() == h for n, h in sums.items())
