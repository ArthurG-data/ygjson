"""Package the release files: a .json.gz beside each dist/*.json, the SQLite database, and SHA256SUMS.

    uv run python tools/package.py

Run after build.py (and changelog.py). Everything is made from the JSON files in dist/, so each format holds what
the JSON holds:

  <name>.json.gz   each dist/<name>.json gzipped, with no name or time in the header, so a rebuild of the same JSON
                   gives the same bytes.
  ygjson.sqlite    one table per kind of record (see SCHEMA): the fields most queries filter on are columns (COLUMNS),
                   and `data` holds the record's other fields as JSON, for SQLite's json_extract. A card's names are
                   the card_names table, an archetype's members archetype_members, and a printing's tcgplayerPrice
                   the tcgplayer_product_id and tcgplayer_subtype columns. Shipped gzipped as ygjson.sqlite.gz.
  SHA256SUMS       the SHA-256 of every file the release attaches, in the format `sha256sum -c SHA256SUMS` checks.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sqlite3
from collections.abc import Collection, Iterable, Mapping
from pathlib import Path

import ygjson

DIST = ygjson.ROOT / "dist"
DATABASE = "ygjson.sqlite"
SUMS = "SHA256SUMS"

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);  -- the build's meta, each value as JSON
CREATE TABLE sets (id TEXT PRIMARY KEY, code TEXT, name TEXT NOT NULL, type TEXT, series TEXT, parent TEXT,
                   era TEXT, release_date TEXT, data TEXT NOT NULL);
CREATE TABLE cards (id TEXT PRIMARY KEY, passcode INTEGER, name TEXT NOT NULL, kind TEXT, frame TEXT, attribute TEXT,
                    monster_type TEXT, level INTEGER, rank INTEGER, link_rating INTEGER, atk INTEGER, def INTEGER,
                    data TEXT NOT NULL);
CREATE TABLE card_names (card TEXT NOT NULL REFERENCES cards(id), language TEXT NOT NULL, name TEXT NOT NULL,
                         PRIMARY KEY (card, language)) WITHOUT ROWID;
CREATE TABLE printings (id TEXT PRIMARY KEY, key TEXT NOT NULL, print TEXT NOT NULL, print_key TEXT,
                        card TEXT NOT NULL REFERENCES cards(id), "set" TEXT NOT NULL REFERENCES sets(id),
                        number TEXT, region TEXT, rarity TEXT NOT NULL, rarity_tier INTEGER, variant TEXT,
                        language TEXT NOT NULL, edition TEXT NOT NULL, finish TEXT, scan TEXT,
                        tcgplayer_product_id INTEGER, tcgplayer_subtype TEXT, data TEXT NOT NULL);
CREATE TABLE archetypes (slug TEXT PRIMARY KEY, name TEXT NOT NULL, is_archetype INTEGER, source TEXT,
                         data TEXT NOT NULL);
CREATE TABLE archetype_members (archetype TEXT NOT NULL REFERENCES archetypes(slug),
                                card TEXT NOT NULL REFERENCES cards(id), PRIMARY KEY (archetype, card)) WITHOUT ROWID;
CREATE TABLE products (id TEXT PRIMARY KEY, "set" TEXT REFERENCES sets(id), category TEXT, name TEXT NOT NULL,
                       contents_status TEXT, release_date TEXT, data TEXT NOT NULL);
CREATE TABLE formats (id TEXT PRIMARY KEY, name TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE legality_events (card TEXT NOT NULL REFERENCES cards(id), format TEXT NOT NULL REFERENCES formats(id),
                              status TEXT NOT NULL, effective TEXT, in_force_by TEXT, source TEXT,
                              data TEXT NOT NULL);
CREATE TABLE ids (kind TEXT NOT NULL, id TEXT NOT NULL, key TEXT, status TEXT NOT NULL, data TEXT NOT NULL,
                  PRIMARY KEY (kind, id)) WITHOUT ROWID;
-- The keys a print or printing id had before its current one (formerKeys, formerIds), to resolve a stored key.
CREATE TABLE former_keys (kind TEXT NOT NULL, key TEXT NOT NULL, id TEXT NOT NULL);
CREATE INDEX printings_card ON printings(card);
CREATE INDEX printings_set ON printings("set");
CREATE INDEX printings_print ON printings(print);
CREATE INDEX printings_number ON printings(number);
CREATE INDEX printings_tcgplayer ON printings(tcgplayer_product_id);
CREATE INDEX card_names_name ON card_names(name);
CREATE INDEX archetype_members_card ON archetype_members(card);
CREATE INDEX products_set ON products("set");
CREATE INDEX legality_events_card ON legality_events(card);
CREATE INDEX ids_key ON ids(key);
CREATE INDEX former_keys_key ON former_keys(key);
"""


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


# {table: [(column, the record's field)]}: the columns filled from a record's fields of the same meaning, in the
# table's column order. `data` holds every other field of the record.
COLUMNS: dict[str, list[tuple[str, str]]] = {
    "sets": [("id", "id"), ("code", "code"), ("name", "name"), ("type", "type"), ("series", "series"),
             ("parent", "parent"), ("era", "era")],
    "cards": [("id", "id"), ("passcode", "passcode"), ("name", "name"), ("kind", "kind"), ("frame", "frame"),
              ("attribute", "attribute"), ("monster_type", "monsterType"), ("level", "level"), ("rank", "rank"),
              ("link_rating", "linkRating"), ("atk", "atk"), ("def", "def")],
    "printings": [("id", "id"), ("key", "key"), ("print", "print"), ("print_key", "printKey"), ("card", "card"),
                  ("set", "set"), ("number", "number"), ("region", "region"), ("rarity", "rarity"),
                  ("rarity_tier", "rarityTier"), ("variant", "variant"), ("language", "language"),
                  ("edition", "edition"), ("finish", "finish"), ("scan", "scan")],
    "archetypes": [("slug", "slug"), ("name", "name"), ("is_archetype", "isArchetype"), ("source", "source")],
    "products": [("id", "id"), ("set", "set"), ("category", "category"), ("name", "name"),
                 ("contents_status", "contentsStatus"), ("release_date", "releaseDate")],
    "formats": [("id", "id"), ("name", "name")],
    "legality_events": [("card", "card"), ("format", "format"), ("status", "status"), ("effective", "effective"),
                        ("in_force_by", "inForceBy"), ("source", "source")],
}


def _row(table: str, record: dict, extra: Mapping[str, object] = {}, drop: Collection[str] = ()) -> tuple:
    """The row of `record` in `table`: its COLUMNS, then `extra` columns, then the rest of the record as JSON."""
    fields = [f for _, f in COLUMNS[table]]
    rest = {k: v for k, v in record.items() if k not in fields and k not in drop}
    return (*(record.get(f) for f in fields), *extra.values(), _json(rest))


def _rows(db: sqlite3.Connection, table: str, rows: Iterable[tuple]) -> None:
    rows = list(rows)
    if rows:
        db.executemany(f'INSERT INTO {table} VALUES ({", ".join("?" * len(rows[0]))})', rows)


def load(docs: dict[str, dict], path: Path) -> None:
    """Write the SQLite database of the release documents `docs` ({file name: {"meta", "data"}}) to `path`."""
    path.unlink(missing_ok=True)
    db = sqlite3.connect(path)
    try:
        db.executescript(SCHEMA)
        _rows(db, "meta", ((k, _json(v)) for k, v in sorted(docs["AllSets"]["meta"].items())))
        _rows(db, "sets", (_row("sets", s, {"release_date": (s.get("releases") or [{}])[0].get("releaseDate")})
                           for s in docs["AllSets"]["data"].values()))
        cards = docs["AllCards"]["data"].values()
        _rows(db, "cards", (_row("cards", c, drop=["names"]) for c in cards))
        _rows(db, "card_names", ((c["id"], lang, name) for c in cards for lang, name in sorted(c["names"].items())))
        def price(p: dict) -> dict:
            found = p.get("tcgplayerPrice", {})
            return {"tcgplayer_product_id": found.get("productId"), "tcgplayer_subtype": found.get("subTypeName")}

        _rows(db, "printings", (_row("printings", p, price(p), drop=["tcgplayerPrice"])
                                for p in docs["AllPrintings"]["data"].values()))
        archetypes = docs["AllArchetypes"]["data"].values()
        _rows(db, "archetypes", (_row("archetypes", a, drop=["members"]) for a in archetypes))
        _rows(db, "archetype_members", ((a["slug"], c) for a in archetypes for c in a.get("members", [])))
        _rows(db, "products", (_row("products", p) for p in docs["AllProducts"]["data"].values()))
        legality = docs["Legality"]["data"]
        _rows(db, "formats", (_row("formats", f) for f in legality["formats"]))
        _rows(db, "legality_events", (_row("legality_events", e) for e in legality["events"]))
        ledger = docs["Ids"]["data"]
        _rows(db, "ids", ((kind, i, e.get("key"), e["status"],
                           _json({k: v for k, v in e.items() if k not in ("id", "key", "status")}))
                          for kind, entries in sorted(ledger.items()) for i, e in sorted(entries.items())))
        former = {"prints": "formerKeys", "printings": "formerIds"}
        _rows(db, "former_keys", ((kind, key, i) for kind, field in former.items()
                                  for i, e in sorted(ledger.get(kind, {}).items()) for key in e.get(field, [])))
        db.commit()
        db.execute("VACUUM")
    finally:
        db.close()


def gzip_file(src: Path, dest: Path) -> None:
    """`src` gzipped to `dest`, with no file name or time in the header: the same input gives the same bytes."""
    with src.open("rb") as raw, dest.open("wb") as out, \
            gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=0, compresslevel=9) as packed:
        shutil.copyfileobj(raw, packed)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def package(dist: Path = DIST) -> list[Path]:
    """Write the .json.gz files, the gzipped database and SHA256SUMS into `dist`; returns the files to attach."""
    sources = sorted(dist.glob("*.json"))
    docs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sources}
    assets = list(sources)
    for src in sources:
        gzip_file(src, dist / f"{src.name}.gz")
        assets.append(dist / f"{src.name}.gz")
    database = dist / DATABASE
    load(docs, database)
    gzip_file(database, dist / f"{DATABASE}.gz")
    assets.append(dist / f"{DATABASE}.gz")
    lines = [f"{sha256(p)}  {p.name}\n" for p in sorted(assets, key=lambda p: p.name)]
    (dist / SUMS).write_text("".join(lines), encoding="utf-8")
    return sorted(assets, key=lambda p: p.name) + [dist / SUMS]


def main() -> None:
    for path in package():
        print(f"  {path.name} {path.stat().st_size:,} bytes")
    print(f"  ({DATABASE} unpacked: {(DIST / DATABASE).stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
