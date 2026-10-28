"""Write dist/AllSets.json, AllCards.json, AllPrintings.json, AllArchetypes.json, AllProducts.json and Legality.json.
Refuses to build invalid data.

    uv run python tools/build.py --version 0.1.0

Every file is {"meta": {"version", "date", "sources"}, "data": ...}. `sources` says which snapshot of each source the
data was last imported from, read from the caches under .cache when they are there: YGOPRODeck's database_version,
YGOJSON's increment, and the latest modifiedOn among TCGCSV's groups. A source whose cache file is missing is left
out, so the build needs nothing from .cache and runs in CI from the committed data alone.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

import ygjson

DIST = ygjson.ROOT / "dist"
CACHE = ygjson.ROOT / ".cache"


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def sources(cache: Path = CACHE) -> dict:
    """The snapshot of each source the caches hold: {"ygoprodeck": "147.60", "ygojson": 1559, "tcgcsv": "2026-10-27"}."""
    out: dict = {}
    if (dbver := _read(cache / "ygoprodeck" / "dbver.json")):
        out["ygoprodeck"] = dbver[0]["database_version"]
    if (meta := _read(cache / "ygojson" / "meta.json")):
        out["ygojson"] = meta["increment"]
    if (groups := _read(cache / "tcgcsv" / "2_groups.json")):
        out["tcgcsv"] = max(g["modifiedOn"] for g in groups["results"])[:10]
    return out


def build(version: str, today: str, cache: Path = CACHE) -> dict[str, dict]:
    """{file name: document} for the six release files. Exits with the problems when the data is invalid."""
    sets, eras, files = ygjson.load_sets(), ygjson.load_eras(), ygjson.load_cards()
    archetypes, sealed, legality = ygjson.load_archetypes(), ygjson.load_sealed(), ygjson.load_legality()
    errors = ygjson.validate(sets, eras, files, archetypes, sealed, legality)
    if errors:
        sys.exit("refusing to build:\n" + "\n".join(errors))
    flat = ygjson.flatten(sets, files, archetypes, sealed)
    meta = {"version": version, "date": today, "sources": sources(cache)}
    if not meta["sources"]:
        del meta["sources"]
    data = {"AllSets": flat["sets"], "AllCards": flat["cards"], "AllPrintings": flat["printings"],
            "AllArchetypes": flat["archetypes"], "AllProducts": flat["products"], "Legality": legality}
    return {name: {"meta": meta, "data": body} for name, body in data.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="0.0.0-dev")
    args = ap.parse_args()
    docs = build(args.version, datetime.date.today().isoformat())
    DIST.mkdir(exist_ok=True)
    for name, doc in docs.items():
        (DIST / f"{name}.json").write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    count = {name: len(doc["data"]) for name, doc in docs.items()}
    print(f"dist/ written: {count['AllSets']} sets, {count['AllCards']} cards, {count['AllPrintings']} printings, "
          f"{count['AllArchetypes']} archetypes, {count['AllProducts']} sealed products, "
          f"{len(docs['Legality']['data']['events'])} legality events")
    for name in docs:
        print(f"  {name}.json {(DIST / f'{name}.json').stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
