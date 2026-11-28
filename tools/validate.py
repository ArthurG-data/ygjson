"""Check every ygjson file against its schema and against the others. Exits 1 on any problem.

    uv run python tools/validate.py [--online]

Covers sets, eras, cards, archetypes, sealed products and the legality events (see ygjson.validate), then the id
ledger under ids/ against that data and mappings/ids.json (see ids.check), then sources.json against its schema and
against each cache under .cache that exists (see sources.problems), then the hand decisions of mappings/ignore.json
and mappings/print_overrides.json (see decisions.problems). --online also
asks TCGCSV whether every TCGplayer product id on a print or a sealed product still exists in category 2. It
downloads the catalogue into a temporary directory, never .cache, so it sees what TCGplayer lists today; that is
one request per group, about 660, half a second apart.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import decisions
import ids
import sources
import tcgcsv
import ygjson


def online_errors(files: dict[str, dict], sealed: dict[str, dict], cache: Path | None = None) -> list[str]:
    """One message per TCGplayer product id on a print or sealed product that category 2 no longer lists."""
    cache = cache or Path(tempfile.mkdtemp(prefix="ygjson-online-"))
    live = {p.product_id for g in tcgcsv.groups(cache) for p in tcgcsv.products(g["groupId"], cache)}
    errors = []
    for body in files.values():
        for card in body["cards"]:
            for p in card["prints"]:
                errors += [f"print {p['id']}: TCGplayer product {i} is gone from category {tcgcsv.CATEGORY}"
                           for i in p.get("identifiers", {}).get("tcgplayerProductIds", []) if i not in live]
    for body in sealed.values():
        for p in body["products"]:
            errors += [f"sealed product {p['id']}: TCGplayer product {i} is gone from category {tcgcsv.CATEGORY}"
                       for i in p.get("identifiers", {}).get("tcgplayerProductIds", []) if i not in live]
    return errors


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--online", action="store_true", help="also check every TCGplayer product id against TCGCSV")
    args = ap.parse_args()
    sets, eras, files = ygjson.load_sets(), ygjson.load_eras(), ygjson.load_cards()
    archetypes, sealed, legality = ygjson.load_archetypes(), ygjson.load_sealed(), ygjson.load_legality()
    errors = ygjson.validate(sets, eras, files, archetypes, sealed, legality)
    if not errors:
        errors = ids.check(ids.load_ledger(), sets, files, archetypes, sealed, ids.load_hand())
    errors += sources.problems(sources.load())
    errors += decisions.problems(decisions.load_ignore(), decisions.load_print_overrides(), decisions.load_reviews(),
                                 files, sets)
    if not errors and args.online:
        errors = online_errors(files, sealed)
    for e in errors:
        print(e)
    if errors:  # flatten assumes data that passed the checks: a print naming a missing set would end in a traceback
        print(f"{len(errors)} problems")
        sys.exit(1)
    flat = ygjson.flatten(sets, files, archetypes, sealed)
    print(f"0 problems in {len(flat['sets'])} sets, {len(flat['cards'])} cards, "
          f"{len(flat['printings'])} printings, {len(flat['archetypes'])} archetypes, "
          f"{len(flat['products'])} sealed products, {len(legality['events'])} legality events")


if __name__ == "__main__":
    main()
