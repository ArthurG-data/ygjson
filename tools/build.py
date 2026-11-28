"""Write dist/AllSets.json, AllCards.json, AllPrintings.json, AllArchetypes.json, AllProducts.json,
Legality.json and Ids.json.
Refuses to build invalid data, or data the id ledger under ids/ does not match.

    uv run python tools/build.py --version 0.2.0

Every file is {"meta": {"version", "date", "sources", "idsVersion", "reviewCounts"}, "data": ...}. Ids.json holds
the id ledger as loaded; the other files name prints by their permanent ids. `sources` says which snapshot of each
source the data was imported from, copied from the committed sources.json (see sources.py), so the build needs
nothing from .cache and runs in CI from the committed data alone. `reviewCounts` is {"<review file>.<list>": items}
for what the review files still hold to settle (decisions.review_counts), the number to bring down.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys

import decisions
import ids
import sources
import ygjson

DIST = ygjson.ROOT / "dist"
IDS_VERSION = 1


def build(version: str, today: str) -> dict[str, dict]:
    """{file name: document} for the seven release files. Exits with the problems when the data is invalid or the
    ledger does not match it."""
    sets, eras, files = ygjson.load_sets(), ygjson.load_eras(), ygjson.load_cards()
    archetypes, sealed, legality = ygjson.load_archetypes(), ygjson.load_sealed(), ygjson.load_legality()
    errors = ygjson.validate(sets, eras, files, archetypes, sealed, legality)
    ledger = ids.load_ledger()
    if not errors:
        errors = ids.check(ledger, sets, files, archetypes, sealed, ids.load_hand())
    manifest = sources.load()
    errors += sources.problems(manifest, cache=None)
    if errors:
        sys.exit("refusing to build:\n" + "\n".join(errors))
    flat = ygjson.flatten(sets, files, archetypes, sealed, ledger)
    meta = {"version": version, "date": today, "sources": manifest, "idsVersion": IDS_VERSION,
            "reviewCounts": decisions.review_counts(decisions.load_reviews())}
    data = {"AllSets": flat["sets"], "AllCards": flat["cards"], "AllPrintings": flat["printings"],
            "AllArchetypes": flat["archetypes"], "AllProducts": flat["products"], "Legality": legality, "Ids": ledger}
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
    counts = docs["AllSets"]["meta"]["reviewCounts"]
    print(f"review: {sum(counts.values()):,} items to settle (" + ", ".join(f"{k} {n}" for k, n in counts.items() if n)
          + ")")
    for name in docs:
        print(f"  {name}.json {(DIST / f'{name}.json').stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
