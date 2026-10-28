"""Report where every TCGplayer Yu-Gi-Oh! product (TCGCSV category 2) ended up in the data.

    uv run python tools/coverage.py [--strict]

A product is in exactly one place, tested in this order:
  print:<match>  on a print (identifiers.tcgplayerProductIds), <match> being how import_tcgcsv tied it;
  sealed         on a sealed product;
  accessory      a sealed-looking product import_sealed skips (a binder, a card box);
  pending        in a group that has no set yet and whose publishedOn is after today;
  review         in review/tcgplayer-2.json (unmatched, conflicts) or review/sealed.json (noSet).
Anything else is UNACCOUNTED. --strict exits 1 if there is any.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import sys

import import_sealed
import import_tcgcsv
import tcgcsv
import ygjson


def classify(groups: list[dict], products: dict[int, list[tcgcsv.Product]], sets: list[dict], files: dict[str, dict],
             sealed: dict[str, dict], review: dict, sealed_review: dict, today: str
             ) -> tuple[collections.Counter, list[tuple[int, str]]]:
    """(Counter of (kind, place), the unaccounted (product id, name))."""
    where: dict[int, str] = {}
    for body in files.values():
        for card in body["cards"]:
            for p in card["prints"]:
                for product_id in p.get("identifiers", {}).get("tcgplayerProductIds", []):
                    where[product_id] = "print:" + p.get("tcgplayer", {}).get("match", "?")
    for body in sealed.values():
        for p in body["products"]:
            for product_id in p.get("identifiers", {}).get("tcgplayerProductIds", []):
                where[product_id] = "sealed"
    in_review = {r["productId"] for key in ("unmatched", "conflicts") for r in review.get(key, [])}
    in_review |= {r["productId"] for r in sealed_review.get("noSet", [])}
    owned = {gid for s in sets for gid in s.get("tcgplayerGroupIds", [])}
    published = {g["groupId"]: (g.get("publishedOn") or "")[:10] for g in groups}
    tally: collections.Counter = collections.Counter()
    missing: list[tuple[int, str]] = []
    for gid in sorted(products):
        pending = gid not in owned and published.get(gid, "") > today
        for prod in products[gid]:
            kind = "single" if prod.is_single else "sealed"
            place = where.get(prod.product_id)
            if place is None and not prod.is_single and import_sealed.category(prod.name) == "accessory":
                place = "accessory"
            elif place is None and pending:
                place = "pending"
            elif place is None and prod.product_id in in_review:
                place = "review"
            if place is None:
                missing.append((prod.product_id, prod.name))
                place = "UNACCOUNTED"
            tally[(kind, place)] += 1
    return tally, missing


def _read(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--strict", action="store_true", help="exit 1 if any product is unaccounted for")
    args = ap.parse_args()
    groups = tcgcsv.groups(import_tcgcsv.CACHE)
    products = {g["groupId"]: tcgcsv.products(g["groupId"], import_tcgcsv.CACHE) for g in groups}
    files = ygjson.load_cards()
    tally, missing = classify(groups, products, ygjson.load_sets(), files, ygjson.load_sealed(),
                              _read(import_tcgcsv.REVIEW), _read(import_sealed.REVIEW), datetime.date.today().isoformat())
    for (kind, place), n in sorted(tally.items()):
        print(f"{kind:7} {place:36} {n:6}")
    print(f"\n{sum(tally.values())} products, {len(missing)} unaccounted for")
    for product_id, name in missing[:20]:
        print(f"  {product_id}: {name}")
    prints = [p for body in files.values() for c in body["cards"] for p in c["prints"]]
    held = sum(1 for p in prints if p.get("identifiers", {}).get("tcgplayerProductIds"))
    print(f"prints: {len(prints)}, with a TCGplayer product: {held}")
    if args.strict and missing:
        sys.exit(1)


if __name__ == "__main__":
    main()
