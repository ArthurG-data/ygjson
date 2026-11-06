"""Load, validate and flatten ygjson sets, eras, cards, archetypes, sealed products and legality events.

Reads sets/sets.json, sets/eras.json, data/cards/<bucket>.json, data/archetypes.json, data/sealed/<set id>.json and
legality/{formats,bans}.json. Writes nothing itself: the import tools call save_json, build.py calls flatten.
"""
from __future__ import annotations

import collections
import functools
import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from rarities import is_foil, tier

ROOT = Path(__file__).resolve().parents[1]
SETS = ROOT / "sets" / "sets.json"
ERAS = ROOT / "sets" / "eras.json"
CARDS = ROOT / "data" / "cards"
ARCHETYPES = ROOT / "data" / "archetypes.json"
SEALED = ROOT / "data" / "sealed"
LEGALITY = ROOT / "legality"
SCHEMAS = ROOT / "schema"

_REGION = re.compile(r"^[^-]+-([A-Z]+)\d")


@functools.cache
def _schema(name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((SCHEMAS / name).read_text(encoding="utf-8")), format_checker=FormatChecker())


def slugify(name: str) -> str:
    """Lower case, every run of characters outside a-z0-9 becomes one hyphen. A name with nothing left (a Japanese
    one) gets x- and the first 12 hex digits of its sha1, so it is still stable and unique."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "x-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]


def dedupe_slugs(names: Iterable[str]) -> dict[str, str]:
    """{name: slug}. Names that slug alike are taken in sorted order: the first keeps the slug, the rest get -2, -3."""
    out: dict[str, str] = {}
    taken: set[str] = set()
    for name in sorted(set(names)):
        slug = base = slugify(name)
        n = 1
        while slug in taken:
            n += 1
            slug = f"{base}-{n}"
        taken.add(slug)
        out[name] = slug
    return out


def card_bucket(card_id: str) -> str:
    """The data/cards file stem for a card id: its millions, three digits."""
    return f"{int(card_id) // 1_000_000:03d}"


def print_id(set_id: str, card_id: str, number: str | None, rarity: str, variant: str | None = None) -> str:
    """A version of a print (the Blue foil, art B) adds its variant, so ids without one never change."""
    base = f"{set_id}:{card_id}:{number or ''}:{rarity}"
    return f"{base}:{variant}" if variant else base


def printing_id(print_id: str, language: str, edition: str) -> str:
    return f"{print_id}:{language}:{edition}"


def region_of(number: str | None) -> str | None:
    """The region letters of a set number: LOB-EN001 -> EN, LOB-001 -> None. Speed Duel numbers carry a slot letter
    after the region (LAVD-ENS05), so a run of three letters is the region followed by that letter."""
    m = _REGION.match(number or "")
    if not m:
        return None
    letters = m.group(1)
    return letters[:2] if len(letters) == 3 else letters


def load_sets(path: Path = SETS) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_eras(path: Path = ERAS) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_cards(cards_dir: Path = CARDS) -> dict[str, dict]:
    """{bucket: file body}, sorted by bucket."""
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(cards_dir.glob("*.json"))}


def load_archetypes(path: Path = ARCHETYPES) -> dict:
    """The file body, {"archetypes": [...]}."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_sealed(sealed_dir: Path = SEALED) -> dict[str, dict]:
    """{set id: file body}, sorted by set id."""
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(sealed_dir.glob("*.json"))}


def load_legality(legality_dir: Path = LEGALITY) -> dict:
    """{"formats": [...], "events": [...]}; no events until bans.json exists."""
    formats = json.loads((legality_dir / "formats.json").read_text(encoding="utf-8"))["formats"]
    bans = legality_dir / "bans.json"
    events = json.loads(bans.read_text(encoding="utf-8"))["events"] if bans.exists() else []
    return {"formats": formats, "events": events}


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _schema_errors(name: str, label: str, doc) -> list[str]:
    return [f"{label}: {e.json_path}: {e.message}" for e in _schema(name).iter_errors(doc)]


def _check_eras(eras: list[dict]) -> list[str]:
    errors = [f"eras.json: era {c} is listed {n} times" for c, n in collections.Counter(e["code"] for e in eras).items() if n > 1]
    ordered = sorted(eras, key=lambda e: e["from"])
    for e, nxt in zip(ordered, ordered[1:]):
        if "to" not in e:
            errors.append(f"eras.json: era {e['code']} is open-ended but {nxt['code']} starts after it")
        elif e["to"] >= nxt["from"]:
            errors.append(f"eras.json: eras {e['code']} and {nxt['code']} overlap")
    errors += [f"eras.json: era {e['code']} ends before it starts" for e in eras if "to" in e and e["to"] < e["from"]]
    return errors


def _check_sets(sets: list[dict], eras: list[dict]) -> list[str]:
    errors = []
    set_ids = collections.Counter(s["id"] for s in sets)
    errors += [f"sets.json: set {s} is listed {n} times" for s, n in set_ids.items() if n > 1]
    era_codes = {e["code"] for e in eras}
    parent_of = {s["id"]: s.get("parent") for s in sets}
    group_owner: dict[int, str] = {}
    for s in sets:
        if "parent" in s and s["parent"] not in set_ids:
            errors.append(f"sets.json: set {s['id']} has parent {s['parent']}, which is not a set")
        seen, cur = {s["id"]}, s.get("parent")
        while cur:
            if cur in seen:
                errors.append(f"sets.json: set {s['id']} is its own ancestor")
                break
            seen.add(cur)
            cur = parent_of.get(cur)
        if "era" in s and s["era"] not in era_codes:
            errors.append(f"sets.json: set {s['id']} has era {s['era']}, which is not in eras.json")
        for gid in s.get("tcgplayerGroupIds", []):
            if gid in group_owner:
                errors.append(f"sets.json: TCGplayer group {gid} is on {group_owner[gid]} and {s['id']}")
            group_owner[gid] = s["id"]
    return errors


def _check_cards(sets: list[dict], files: dict[str, dict], archetype_slugs: set[str],
                 product_owner: dict[int, str]) -> tuple[list[str], set[str], set[str]]:
    """Returns the errors, the card ids and the print ids."""
    errors = []
    set_ids = {s["id"] for s in sets}
    card_ids: collections.Counter = collections.Counter()
    print_ids: dict[str, str] = {}
    for stem, body in files.items():
        for card in body["cards"]:
            cid = card["id"]
            card_ids[cid] += 1
            if card_bucket(cid) != stem:
                errors.append(f"cards/{stem}.json: card {cid} belongs in cards/{card_bucket(cid)}.json")
            if card["name"] != card["names"]["en"]:
                errors.append(f"card {cid}: name must equal names.en")
            errors += [f"card {cid}: archetype {a} is not in archetypes.json" for a in card.get("archetypes", [])
                       if a not in archetype_slugs]
            for p in card["prints"]:
                pid = p["id"]
                if pid in print_ids:
                    errors.append(f"print {pid} is listed twice ({print_ids[pid]} and {cid})")
                print_ids[pid] = cid
                expected = print_id(p["set"], cid, p.get("number"), p["rarity"], p.get("variant"))
                if pid != expected:
                    errors.append(f"print {pid}: id must be {expected}")
                if p["set"] not in set_ids:
                    errors.append(f"print {pid}: set {p['set']} is not in sets.json")
                for product_id in p.get("identifiers", {}).get("tcgplayerProductIds", []):
                    if product_id in product_owner:
                        errors.append(f"TCGplayer product {product_id} is on {product_owner[product_id]} and {pid}")
                    product_owner[product_id] = pid
    errors += [f"card {c} is listed {n} times" for c, n in card_ids.items() if n > 1]
    return errors, set(card_ids), set(print_ids)


def _check_sealed(sets: list[dict], sealed: dict[str, dict], print_ids: set[str],
                  product_owner: dict[int, str]) -> list[str]:
    errors = []
    set_ids = {s["id"] for s in sets}
    products = collections.Counter(p["id"] for body in sealed.values() for p in body["products"])
    errors += [f"sealed product id {i} is used {n} times" for i, n in products.items() if n > 1]
    for stem, body in sealed.items():
        for p in body["products"]:
            where = f"sealed/{stem}.json: {p['id']}"
            if p["set"] != stem:
                errors.append(f"{where}: filed under {stem} but its set is {p['set']}")
            if p["set"] not in set_ids:
                errors.append(f"{where}: set {p['set']} is not in sets.json")
            for product_id in p.get("identifiers", {}).get("tcgplayerProductIds", []):
                if product_id in product_owner:
                    errors.append(f"TCGplayer product {product_id} is on {product_owner[product_id]} and {p['id']}")
                product_owner[product_id] = p["id"]
            contents = p["contents"]
            for item in contents.get("sealed", []):
                if item["product"] not in products or item["product"] == p["id"]:
                    errors.append(f"{where}: holds {item['product']}, which is not another sealed product")
            for item in contents.get("cards", []):
                if item["print"] not in print_ids:
                    errors.append(f"{where}: holds print {item['print']}, which does not exist")
            for item in contents.get("pool", []):
                if item["set"] not in set_ids:
                    errors.append(f"{where}: pool set {item['set']} is not in sets.json")
            if p["contentsStatus"] == "unknown" and any(contents.values()):
                errors.append(f"{where}: lists contents but says contentsStatus unknown")
            if p["contentsStatus"] == "complete" and any("count" not in i for k in ("sealed", "cards")
                                                       for i in contents.get(k, [])):
                errors.append(f"{where}: complete contents need a count on every item")
    return errors


def validate(sets: list[dict], eras: list[dict], files: dict[str, dict], archetypes: dict,
             sealed: dict[str, dict] | None = None, legality: dict | None = None) -> list[str]:
    """Every problem found offline, one message each. Empty when the data is valid.

    archetypes is the file body, legality is load_legality's {"formats", "events"}."""
    sealed = sealed or {}
    errors = _schema_errors("sets.schema.json", "sets.json", sets) + _schema_errors("eras.schema.json", "eras.json", eras)
    errors += _schema_errors("archetypes.schema.json", "archetypes.json", archetypes)
    for stem, body in files.items():
        errors += _schema_errors("cards.schema.json", f"cards/{stem}.json", body)
    for stem, body in sealed.items():
        errors += _schema_errors("sealed.schema.json", f"sealed/{stem}.json", body)
    if legality is not None:
        errors += _schema_errors("legality.schema.json", "legality", {"events": legality["events"]})
    if errors:
        return errors  # the checks below assume the documents have the right shape

    slugs = collections.Counter(a["slug"] for a in archetypes["archetypes"])
    errors = _check_eras(eras) + _check_sets(sets, eras)
    errors += [f"archetypes.json: archetype {s} is listed {n} times" for s, n in slugs.items() if n > 1]
    product_owner: dict[int, str] = {}
    card_errors, card_ids, print_ids = _check_cards(sets, files, set(slugs), product_owner)
    errors += card_errors + _check_sealed(sets, sealed, print_ids, product_owner)
    if legality is not None:
        format_ids = {f["id"] for f in legality["formats"]}
        for e in legality["events"]:
            if e["card"] not in card_ids:
                errors.append(f"legality: event for card {e['card']}, which does not exist")
            if e["format"] not in format_ids:
                errors.append(f"legality: event for format {e['format']}, which is not in formats.json")
    return errors


def flatten(sets: list[dict], files: dict[str, dict], archetypes: dict,
            sealed: dict[str, dict] | None = None) -> dict[str, dict]:
    """The release shape: {"sets": {id: set}, "cards": {id: card with prints as print ids}, "printings": {id: printing},
    "archetypes": {slug: archetype + members}, "products": {id: sealed product}}.

    A printing is a print in one edition: the print's editions when it has them, else its set's. TCGplayer sells
    every edition of a print under one product, so each printing carries the print's product ids. archetype members
    are card ids in numeric order."""
    by_set = {s["id"]: s for s in sets}
    out: dict[str, dict] = {"sets": by_set, "cards": {}, "printings": {}, "archetypes": {}, "products": {
        p["id"]: p for body in (sealed or {}).values() for p in body["products"]}}
    members: dict[str, list[str]] = collections.defaultdict(list)
    for body in files.values():
        for card in body["cards"]:
            cid = card["id"]
            out["cards"][cid] = {**card, "prints": [p["id"] for p in card["prints"]]}
            for slug in card.get("archetypes", []):
                members[slug].append(cid)
            for p in card["prints"]:
                rarity_tier = tier(p["rarity"])
                finish = is_foil(p["rarity"])
                for edition in p.get("editions", by_set[p["set"]]["editions"]):
                    pid = printing_id(p["id"], "en", edition)
                    out["printings"][pid] = {
                        "id": pid, "print": p["id"], "card": cid, "set": p["set"],
                        **{k: p[k] for k in ("number", "region", "variant", "source") if k in p},
                        "rarity": p["rarity"],
                        **({"rarityTier": rarity_tier} if rarity_tier is not None else {}),
                        "language": "en", "edition": edition,
                        "finish": None if finish is None else "foil" if finish else "nonfoil",
                        "identifiers": p.get("identifiers", {}),
                        **({"tcgplayer": p["tcgplayer"]} if "tcgplayer" in p else {}),
                    }
    for a in archetypes["archetypes"]:
        out["archetypes"][a["slug"]] = {**a, "members": sorted(members.get(a["slug"], []), key=int)}
    return out
