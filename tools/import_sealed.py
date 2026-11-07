"""Write data/sealed/<set id>.json and review/sealed.json from TCGplayer's sealed Yu-Gi-Oh! products and YGOJSON.

    uv run python tools/import_sealed.py

A sealed product is a TCGCSV category 2 product with neither a card number nor a rarity, in a group that
import_tcgcsv matched to a set (sets.json lists the group in tcgplayerGroupIds). A product in any other group goes
to review `noSet`. Its category comes from its name (ordered rules, first match wins, see CATEGORY_RULES); an
`accessory` (a binder, a card box for a field center) is skipped, so it is in no file and no review list. The id is
the slug of the product name without its edition tag ([1st Edition], [Unlimited], - 1st Edition), so the 1st
Edition and Unlimited products of one box share a slug: the first edition keeps it and the rest get -2, -3.

Contents are written only where a rule or a source states them:
- booster_box: 24 of the group's one booster pack with the same edition tag (complete); a mini box or tuck box
  lists the pack without a count (partial);
- case: 12 of the group's one booster box with the same tag (complete);
- display: the group's one booster pack, structure deck or starter deck with the same tag, without a count (partial);
- booster_pack: a `pool` of its set, with the edition from its tag (partial);
- structure_deck, starter_deck, deck, tin, mega_tin, special_edition: the prints of its set, without counts
  (partial), only when the set is a kind of set that holds just that product's cards, else unknown;
- anything else: unknown.
Then every product YGOJSON names the same (normalised English name, "X (Box)" read as "X Booster Box") gains
identifiers.ygojsonId and the packs YGOJSON lists for it: a pack of one of our sets becomes a `sealed` entry
for that set's booster pack with YGOJSON's quantity, a pack that names a card becomes a `cards` entry for the
card's print in that set. When YGOJSON states contents, they replace the rule-written `cards`, and the product is
`complete` if every pack resolved with a quantity.
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

import tcgcsv
import ygjson
from import_ygojson import normalise

CACHE = ygjson.ROOT / ".cache" / "tcgcsv"
YGOJSON = ygjson.ROOT / ".cache" / "ygojson" / "sealedProducts.json"
REVIEW = ygjson.ROOT / "review" / "sealed.json"

# (category, regex on the lower-cased name). First match wins, so containers come before what they contain, and
# accessories come first so "Deck Box" is not a deck. Words are anchored where a substring misleads: "tin" is in
# "Haunting", "ots" in "lots", "case" in "briefcase".
CATEGORY_RULES: tuple[tuple[str, str], ...] = (
    ("accessory", r"\bsleeves?\b|playmat|\bbinder\b|deck box|card case|field center|token$|\bdice\b|\bcoins?\b|\bcounters?\b"),
    ("case", r"\bcase\b"),
    ("display", r"display|\[set of"),
    ("booster_box", r"booster box|mini booster box|tuck box"),
    ("booster_pack", r"booster pack|sleeved booster|blister"),
    ("structure_deck", r"structure deck"),
    ("starter_deck", r"starter deck|starter"),
    ("deck", r"deck"),
    ("mega_tin", r"mega.?tin"),
    ("tin", r"\btins?\b"),
    ("special_edition", r"special edition|deluxe edition|advanced edition|secret edition|gold edition|super edition|\bse\b"),
    ("collectors_set", r"collector|collection|legendary|box set|mega pack|set$"),
    ("promo_pack", r"promo|participation|tournament pack|\bots\b"),
    ("bundle", r"bundle|value box|advent|\bkit\b"),
)
_RULES = tuple((category, re.compile(rx)) for category, rx in CATEGORY_RULES)

# Which kinds of set a deck, tin or special edition may list the prints of.
CONTENT_SETS = {
    "structure_deck": {"structure_deck", "starter_deck", "speed_duel", "box_set"},
    "starter_deck": {"structure_deck", "starter_deck", "speed_duel", "box_set"},
    "deck": {"structure_deck", "starter_deck", "speed_duel", "box_set"},
    "tin": {"tin", "box_set", "promo"},
    "mega_tin": {"tin", "box_set", "promo"},
    "special_edition": {"special_edition", "box_set"},
}
BOX_PACKS = 24  # a booster box holds this many packs unless its name says otherwise: "(36 packs)", "(24 count)"
CASE_BOXES = 12
_EDITION_BRACKET = re.compile(r"\s*\[[^\]]*(?:1st|unlimited|limited edition)[^\]]*\]", re.IGNORECASE)
_EDITION_DASH = re.compile(r"\s+-\s+(?:1st|unlimited) edition\s*$", re.IGNORECASE)
_PACK_COUNT = re.compile(r"\((\d+) (?:count|packs?)\)", re.IGNORECASE)
_EDITION_RANK = {"first": 0, None: 1, "unlimited": 2, "limited": 3}


def category(name: str) -> str:
    lower = name.lower()
    return next((c for c, rx in _RULES if rx.search(lower)), "other")


def edition_tag(name: str) -> str | None:
    """The edition a product name states: first, unlimited or limited, else None."""
    lower = name.lower()
    if "1st edition" in lower:
        return "first"
    if "unlimited" in lower:
        return "unlimited"
    if "limited edition" in lower:
        return "limited"
    return None


def strip_edition(name: str) -> str:
    return _EDITION_DASH.sub("", _EDITION_BRACKET.sub("", name)).strip()


def box_packs(name: str) -> int:
    m = _PACK_COUNT.search(name)
    return int(m.group(1)) if m else BOX_PACKS


def _is_mini(name: str) -> bool:
    return bool(re.search(r"\bmini\b|tuck box", name.lower()))


def assign_ids(records: list[dict]) -> None:
    """Give each record its slug id: names that slug alike (once the edition tag is gone) are ordered 1st Edition,
    untagged, Unlimited, Limited, then by product id; the first keeps the slug and the rest get -2, -3."""
    by_slug: dict[str, list[dict]] = collections.defaultdict(list)
    for r in records:
        by_slug[ygjson.slugify(strip_edition(r["name"]))].append(r)
    taken: set[str] = set()
    for slug, group in sorted(by_slug.items()):
        group.sort(key=lambda r: (_EDITION_RANK[r["tag"]], r["productId"]))
        n = 0
        for r in group:
            n += 1
            cand = slug if n == 1 else f"{slug}-{n}"
            while cand in taken:
                n += 1
                cand = f"{slug}-{n}"
            taken.add(cand)
            r["id"] = cand


class Context:
    """What the content rules look at: the records by group, the sets, and each set's prints."""

    def __init__(self, records: list[dict], sets: list[dict], files: dict[str, dict]):
        self.by_group: dict[int, list[dict]] = collections.defaultdict(list)
        self.by_set: dict[str, list[dict]] = collections.defaultdict(list)
        for r in records:
            self.by_group[r["groupId"]].append(r)
            self.by_set[r["set"]].append(r)
        self.sets = {s["id"]: s for s in sets}
        self.prints: dict[str, list[str]] = collections.defaultdict(list)
        self.card_prints: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
        self.card_of_uuid: dict[str, str] = {}
        for body in files.values():
            for card in body["cards"]:
                if uuid := card.get("identifiers", {}).get("ygojsonId"):
                    self.card_of_uuid[uuid] = card["id"]
                for p in card["prints"]:
                    if ygjson.is_treatment(p):  # a deck holds the plain card, not its stamp or misprint
                        continue
                    self.prints[p["set"]].append(p["id"])
                    self.card_prints[(card["id"], p["set"])].append(p["id"])
        for ids in self.prints.values():
            ids.sort()
        self.set_of_uuid = {s["identifiers"]["ygojsonId"]: s["id"] for s in sets if s.get("identifiers", {}).get("ygojsonId")}

    def one(self, rec: dict, wanted: tuple[str, ...]) -> dict | None:
        """The one record of the group, in the first of the wanted categories that has any, with rec's edition tag."""
        for cat in wanted:
            found = [r for r in self.by_group[rec["groupId"]] if r["category"] == cat and r["tag"] == rec["tag"]
                     and r is not rec and not _is_mini(r["name"])]
            if found:
                return found[0] if len(found) == 1 else None
        return None


def rule_contents(rec: dict, ctx: Context) -> tuple[dict, str]:
    """(contents, status) from the product's category and its neighbours in the group."""
    cat = rec["category"]
    if cat == "booster_box":
        pack = ctx.one(rec, ("booster_pack",))
        if pack is None:
            return {}, "unknown"
        if _is_mini(rec["name"]):
            return {"sealed": [{"product": pack["id"]}]}, "partial"
        return {"sealed": [{"product": pack["id"], "count": box_packs(rec["name"])}]}, "complete"
    if cat == "case":
        box = ctx.one(rec, ("booster_box",))
        return ({"sealed": [{"product": box["id"], "count": CASE_BOXES}]}, "complete") if box else ({}, "unknown")
    if cat == "display":
        unit = ctx.one(rec, ("booster_pack", "structure_deck", "starter_deck"))
        return ({"sealed": [{"product": unit["id"]}]}, "partial") if unit else ({}, "unknown")
    if cat == "booster_pack":
        pool = {"set": rec["set"]}
        if rec["tag"]:
            pool["editions"] = [rec["tag"]]
        return {"pool": [pool]}, "partial"
    if cat in CONTENT_SETS and ctx.sets[rec["set"]]["type"] in CONTENT_SETS[cat] and ctx.prints.get(rec["set"]):
        return {"cards": [{"print": p} for p in ctx.prints[rec["set"]]]}, "partial"
    return {}, "unknown"


def _ygojson_keys(name: str) -> set[str]:
    keys = {normalise(name)}
    if name.endswith(" (Box)"):
        keys.add(normalise(name.removesuffix(" (Box)")) + " booster box")
    return keys


def _tcgplayer_key(rec: dict) -> str:
    return normalise(_PACK_COUNT.sub("", strip_edition(rec["name"])))


def _en_contents(product: dict) -> list[dict]:
    """The packs of the first contents entry that covers English."""
    for entry in product.get("contents") or []:
        if "en" in entry.get("locales", ["en"]):
            return entry.get("packs") or []
    return []


def merge_ygojson(records: list[dict], ygo_products: list[dict], ctx: Context) -> list[dict]:
    """Add YGOJSON's id and contents to the records it matches by name. Returns the YGOJSON products with an
    English release that matched none."""
    by_key: dict[str, list[dict]] = collections.defaultdict(list)
    for r in records:
        by_key[_tcgplayer_key(r)].append(r)
        if r["category"] == "special_edition":  # "X: Special Edition Box" is YGOJSON's "X: Special Edition"
            by_key[re.sub(r" (individual )?box$", "", _tcgplayer_key(r))].append(r)
    unmatched = []
    for g in sorted(ygo_products, key=lambda g: g["id"]):
        name = (g.get("name") or {}).get("en")
        if not name:
            continue
        hits = [r for key in sorted(_ygojson_keys(name)) for r in by_key.get(key, [])]
        hits = list({r["productId"]: r for r in hits}.values())
        if not hits:
            if "en" in (g.get("locales") or {}):
                unmatched.append({"id": g["id"], "name": name})
            continue
        for r in hits:
            r["ygojsonId"] = g["id"]
            _apply_packs(r, _en_contents(g), ctx)
    return unmatched


def _apply_packs(rec: dict, packs: list[dict], ctx: Context) -> None:
    sealed, cards, resolved_all = [], [], bool(packs)
    for pack in packs:
        set_id = ctx.set_of_uuid.get(pack["set"])
        if "card" in pack:
            prints = ctx.card_prints.get((ctx.card_of_uuid.get(pack["card"]), set_id), []) if set_id else []
            if len(prints) == 1:
                cards.append({"print": prints[0], "count": 1})
            else:
                resolved_all = False
            continue
        packs_of_set = [r for r in ctx.by_set.get(set_id, []) if r["category"] == "booster_pack"] if set_id else []
        same = [r for r in packs_of_set if r["tag"] == rec["tag"]] or packs_of_set
        if len(same) == 1:
            item = {"product": same[0]["id"]}
            if "qty" in pack:
                item["count"] = pack["qty"]
            else:
                resolved_all = False
            sealed.append(item)
        else:
            resolved_all = False
    if not (sealed or cards):
        return
    contents = rec["contents"]
    if sealed:
        kept = {i["product"]: i for i in contents.get("sealed", [])}
        for item in sealed:  # YGOJSON's quantity wins; a pack it gives no quantity keeps the rule's count
            kept[item["product"]] = {**kept.get(item["product"], {}), **item}
        contents["sealed"] = list(kept.values())
    if cards:
        contents["cards"] = cards
    elif resolved_all:
        contents.pop("cards", None)
    rec["status"] = "complete" if resolved_all else rec["status"] if rec["status"] != "unknown" else "partial"


def build(groups: list[dict], products: dict[int, list[tcgcsv.Product]], sets: list[dict], files: dict[str, dict],
          ygo_products: list[dict]) -> dict:
    """{"files": {set id: file body}, "review": {...}, "stats": {...}} from in-memory data."""
    set_of_group = {gid: s["id"] for s in sets for gid in s.get("tcgplayerGroupIds", [])}
    group_names = {g["groupId"]: g["name"] for g in groups}
    records, no_set, accessories = [], [], 0
    for gid in sorted(products):
        for prod in sorted(products[gid], key=lambda p: p.product_id):
            if prod.is_single:
                continue
            cat = category(prod.name)
            if cat == "accessory":
                accessories += 1
            elif gid not in set_of_group:
                no_set.append({"productId": prod.product_id, "name": prod.name, "groupId": gid,
                               "group": group_names.get(gid, "")})
            else:
                records.append({"productId": prod.product_id, "groupId": gid, "set": set_of_group[gid], "category": cat,
                                "name": prod.name, "tag": edition_tag(prod.name), "url": prod.url,
                                "releasedOn": prod.released_on})
    assign_ids(records)
    ctx = Context(records, sets, files)
    for r in records:
        r["contents"], r["status"] = rule_contents(r, ctx)
    unmatched = merge_ygojson(records, ygo_products, ctx)
    bodies: dict[str, list[dict]] = collections.defaultdict(list)
    for r in records:
        bodies[r["set"]].append(product_body(r))
    out = {sid: {"products": sorted(ps, key=lambda p: p["id"])} for sid, ps in sorted(bodies.items())}
    review = {"noSet": no_set,
              "other": [{"productId": r["productId"], "name": r["name"], "set": r["set"]} for r in records
                        if r["category"] == "other"],
              "ygojsonUnmatched": unmatched}
    stats = {"products": len(records), "accessories": accessories, "noSet": len(no_set),
             "categories": dict(sorted(collections.Counter(r["category"] for r in records).items())),
             "status": dict(sorted(collections.Counter(r["status"] for r in records).items())),
             "ygojson": sum(1 for r in records if r.get("ygojsonId")), "ygojsonUnmatched": len(unmatched)}
    return {"files": out, "review": review, "stats": stats}


def product_body(r: dict) -> dict:
    ids: dict = {"tcgplayerProductIds": [r["productId"]]}
    sources = [r["url"] or f"https://www.tcgplayer.com/product/{r['productId']}"]
    if r.get("ygojsonId"):
        ids["ygojsonId"] = r["ygojsonId"]
        sources.append(f"ygojson:{r['ygojsonId']}")
    body = {"id": r["id"], "set": r["set"], "category": r["category"], "name": r["name"], "identifiers": ids,
            "contentsStatus": r["status"], "contents": r["contents"], "sources": sources}
    if r["releasedOn"]:
        body["releaseDate"] = r["releasedOn"]
    return body


def main() -> None:
    groups = tcgcsv.groups(CACHE)
    products = {g["groupId"]: tcgcsv.products(g["groupId"], CACHE) for g in groups}
    ygo = json.loads(YGOJSON.read_text(encoding="utf-8")) if YGOJSON.exists() else []
    out = build(groups, products, ygjson.load_sets(), ygjson.load_cards(), ygo)
    ygjson.SEALED.mkdir(parents=True, exist_ok=True)
    for stale in ygjson.SEALED.glob("*.json"):
        stale.unlink()
    for set_id, body in out["files"].items():
        ygjson.save_json(ygjson.SEALED / f"{set_id}.json", body)
    ygjson.save_json(REVIEW, out["review"])
    s = out["stats"]
    print(f"{s['products']} sealed products in {len(out['files'])} sets; {s['accessories']} accessories skipped, "
          f"{s['noSet']} in groups with no set")
    print("categories: " + ", ".join(f"{n} {c}" for c, n in s["categories"].items()))
    print("contents: " + ", ".join(f"{n} {c}" for c, n in s["status"].items()))
    print(f"YGOJSON: {s['ygojson']} products matched, {s['ygojsonUnmatched']} English products unmatched; "
          f"review: {len(out['review']['other'])} other")


if __name__ == "__main__":
    main()
