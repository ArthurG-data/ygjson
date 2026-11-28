"""Load, validate and flatten ygjson sets, eras, cards, archetypes, sealed products and legality events.

Reads sets/sets.json, sets/eras.json, data/cards/<bucket>.json, data/archetypes.json, data/sealed/<set id>.json and
legality/{formats,bans}.json. Writes nothing itself: the import tools call save_json, build.py calls flatten.
"""
from __future__ import annotations

import collections
import functools
import hashlib
import html
import itertools
import json
import re
import uuid
from collections.abc import Container, Iterable, Mapping
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
# The namespace of every UUID ygjson mints: prints, cards, sets, archetypes, sealed products, printings and oracles.
YGJSON_NAMESPACE = uuid.UUID("7d674373-b170-5fd8-ab33-29bacad29ffa")  # uuid5(NAMESPACE_URL, "https://github.com/ArthurG-data/ygjson")

# TCGplayer prices a single in one subtype per edition, named so in TCGCSV's prices (subTypeName).
PRICE_SUBTYPES = {"first": "1st Edition", "unlimited": "Unlimited", "limited": "Limited"}

_REGION = re.compile(r"^[^-]+-([A-Z]+)\d")
_COLOUR_OR_ART_VARIANT = re.compile(r"^(blue|green|purple|red|silver|bronze|[a-g]|version-\d+)$")


@functools.cache
def _schema(name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((SCHEMAS / name).read_text(encoding="utf-8")),
                                format_checker=FormatChecker())


def slugify(name: str) -> str:
    """Lower case, every run of characters outside a-z0-9 becomes one hyphen. A name with nothing left (a Japanese
    one) gets x- and the first 12 hex digits of its sha1, so it is still stable and unique."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "x-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]


def dedupe_slugs(names: Iterable[str], held: Mapping[str, str] | None = None,
                 reserved: Container[str] = frozenset()) -> dict[str, str]:
    """{name: slug}. A name in `held` (the ledger's {name: slug}) keeps its slug. The other names, in sorted order,
    take their slug, else the next free -2, -3, never a slug held for another name or in `reserved`. Two current names
    held at one slug cannot both have it: the first in sorted order does, the other is treated as unheld."""
    held = held or {}
    ordered = sorted(set(names))
    out: dict[str, str] = {}
    kept: set[str] = set()
    for name in ordered:
        if name in held and held[name] not in kept:
            out[name] = held[name]
            kept.add(held[name])
    taken = kept | set(held.values())
    for name in ordered:
        if name in out:
            continue
        slug = base = slugify(name)
        n = 1
        while slug in taken or slug in reserved:
            n += 1
            slug = f"{base}-{n}"
        taken.add(slug)
        out[name] = slug
    return dict(sorted(out.items()))


def card_bucket(card_id: str) -> str:
    """The data/cards file stem for a card id: its millions, three digits."""
    return f"{int(card_id) // 1_000_000:03d}"


def print_id(set_id: str, card_id: str, number: str | None, rarity: str, variant: str | None = None) -> str:
    """A version of a print (the Blue foil, art B) adds its variant, so ids without one never change."""
    base = f"{set_id}:{card_id}:{number or ''}:{rarity}"
    return f"{base}:{variant}" if variant else base


def is_colour_or_art(slug: str) -> bool:
    """True for a foil colour (blue), an art letter (b) or a numbered art (version-2), the slugs always kept apart."""
    return bool(_COLOUR_OR_ART_VARIANT.match(slug))


def is_treatment(p: dict) -> bool:
    """True for a print that is a stamp, misprint or similar treatment of a card, not a colour or art letter it comes
    in."""
    return bool(p.get("variant")) and not is_colour_or_art(p["variant"])


def printing_id(print_id: str, language: str, edition: str) -> str:
    return f"{print_id}:{language}:{edition}"


def region_of(number: str | None) -> str | None:
    """The region letters of a set number: LOB-EN001 -> EN, LOB-001 -> None. Speed Duel numbers carry a slot letter
    after the region (LAVD-ENS05), and special editions and promos add two (TDIL-ENSE3, CYHO-ENSP1, RGBT-ENPP5), so a
    run of three or more letters is the region followed by those letters."""
    m = _REGION.match(number or "")
    if not m:
        return None
    letters = m.group(1)
    return letters[:2] if len(letters) >= 3 else letters


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


def era_of(release_date: str | None, eras: Iterable[Mapping]) -> str | None:
    """The era whose window holds the date. Dates are ISO strings, so they compare as text."""
    if not release_date:
        return None
    return next((e["code"] for e in eras if e["from"] <= release_date <= e.get("to", "9999-12-31")), None)


_NON_ALNUM = re.compile(r"[\W_]+")


def normalise(name: str) -> str:
    """A name for loose comparison: HTML entities decoded, lower case, apostrophes unified, every run of
    non-alphanumerics one space, trimmed. "Yu-Gi-Oh! 5D's" and "yu gi oh 5d s" are equal."""
    text = html.unescape(name).lower().replace("’", "'")
    return _NON_ALNUM.sub(" ", text).strip()


def fold_name(name: str) -> str:
    """A name for stricter comparison than normalise: case-folded, apostrophes unified and spaces collapsed, with its
    punctuation kept, so "Yu-Gi-Oh! 5D's" and "Yu Gi Oh 5D's" stay apart."""
    return " ".join(name.replace("’", "'").casefold().split())


_ASCII_SPACE = re.compile(r"[ \t\r\n]+")
_TEMPLATE_KEY = re.compile(r"^\|\s*[a-z_]+\s+")  # "| supports_archetypes    Power Patron": a wiki field leaked


def clean_name(name: str) -> str:
    """A name with each run of ASCII spaces, tabs and newlines made one space, and none at either end. Other spaces
    stay: a Japanese name spells some with the ideographic space U+3000."""
    return _ASCII_SPACE.sub(" ", name).strip(" ")


def clean_archetype_name(raw: str) -> str:
    """An archetype name without a leaked wiki template key (YGOPRODeck lists one), cleaned as clean_name."""
    return clean_name(_TEMPLATE_KEY.sub("", raw))


def spacing_errors(label: str, name: str) -> list[str]:
    """A message when a name has a leading, trailing or doubled space (or a tab or newline): clean_name changes it."""
    if clean_name(name) != name:
        return [f"{label}: name {name!r} has a leading, trailing or doubled space"]
    return []


def _check_eras(eras: list[dict]) -> list[str]:
    errors = [f"eras.json: era {c} is listed {n} times"
              for c, n in collections.Counter(e["code"] for e in eras).items() if n > 1]
    ordered = sorted(eras, key=lambda e: e["from"])
    for e, nxt in itertools.pairwise(ordered):
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
    era_of_set = {s["id"]: s.get("era") for s in sets}
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
        date = (s.get("releases") or [{}])[0].get("releaseDate")
        expected = era_of(date, eras) if date else era_of_set.get(s.get("parent") or "")
        if expected and s.get("era") != expected:
            errors.append(f"sets.json: set {s['id']} has era {s.get('era')}, but "
                          + (f"its release date {date} is in {expected}" if date else f"its parent's is {expected}"))
        errors += spacing_errors(f"sets.json: set {s['id']}", s["name"])
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
    set_editions = {s["id"]: s["editions"] for s in sets}
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
            for lang, name in sorted(card["names"].items()):
                errors += spacing_errors(f"card {cid} ({lang})", name)
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
                held = p.get("identifiers", {}).get("tcgplayerProductIds", [])
                for edition, product_id in p.get("tcgplayer", {}).get("editionProducts", {}).items():
                    if product_id not in held or edition not in print_editions(p, set_editions.get(p["set"], [])):
                        errors.append(f"print {pid}: editionProducts names {edition} {product_id}, which is not one "
                                      f"of its products and editions")
                for product_id in held:
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
            errors += spacing_errors(where, p["name"])
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
    errors = (_schema_errors("sets.schema.json", "sets.json", sets)
              + _schema_errors("eras.schema.json", "eras.json", eras))
    errors += _schema_errors("archetypes.schema.json", "archetypes.json", archetypes)
    for stem, body in files.items():
        errors += _schema_errors("cards.schema.json", f"cards/{stem}.json", body)
    for stem, body in sealed.items():
        errors += _schema_errors("sealed.schema.json", f"sealed/{stem}.json", body)
    if legality is not None:
        errors += _schema_errors("legality.schema.json", "legality", {"events": legality["events"]})
        errors += _schema_errors("formats.schema.json", "formats.json", {"formats": legality["formats"]})
    if errors:
        return errors  # the checks below assume the documents have the right shape

    slugs = collections.Counter(a["slug"] for a in archetypes["archetypes"])
    errors = _check_eras(eras) + _check_sets(sets, eras)
    errors += [f"archetypes.json: archetype {s} is listed {n} times" for s, n in slugs.items() if n > 1]
    for a in archetypes["archetypes"]:
        where = f"archetypes.json: archetype {a['slug']}"
        if "en" in a.get("names", {}) and a["names"]["en"] != a["name"]:
            errors.append(f"{where}: name {a['name']!r} is not names.en {a['names']['en']!r}")
        for name in [a["name"], *a.get("names", {}).values()]:
            errors += spacing_errors(where, name)
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


def print_editions(p: dict, set_editions: list[str]) -> list[str]:
    """The editions a print is sold in: its own `editions` when it has them, else its set's."""
    return p.get("editions", set_editions)


def price_of(p: dict, edition: str) -> dict | None:
    """Where TCGplayer prices the print in `edition`: {"productId", "subTypeName"}, the pair a TCGCSV price row is
    keyed by. The print's one product, else the one its `tcgplayer.editionProducts` names for the edition. None when
    the print has no product, or none of its products prices the edition."""
    ids = p.get("identifiers", {}).get("tcgplayerProductIds", [])
    product = ids[0] if len(ids) == 1 else p.get("tcgplayer", {}).get("editionProducts", {}).get(edition)
    return None if product is None else {"productId": product, "subTypeName": PRICE_SUBTYPES[edition]}


def flatten(sets: list[dict], files: dict[str, dict], archetypes: dict,
            sealed: dict[str, dict] | None = None, ledger: dict[str, dict[str, dict]] | None = None) -> dict[str, dict]:
    """The release shape: {"sets": {id: set}, "cards": {id: card with prints as print ids}, "printings": {id: printing},
    "archetypes": {slug: archetype + members}, "products": {id: sealed product}}.

    With a ledger, prints and printings carry their permanent ids: a card lists print UUIDs, a printing is keyed
    `<print uuid>:<language>:<edition>` and keeps the readable id as `key` and the print's key as `printKey`, and a
    sealed product's cards point at print UUIDs. Without one the readable ids are used throughout.

    A printing is a print in one edition: the print's editions when it has them, else its set's. It carries the
    print's product ids, `tcgplayerPrice` (see price_of) names the product and price subtype of its edition, and
    `scan` links the print's scan in its edition, when the print has one.
    archetype members are card ids in numeric order."""
    by_set = {s["id"]: s for s in sets}
    uuids = {e["key"]: e["id"] for e in ledger["prints"].values() if e["status"] == "live"} if ledger else None
    products = {p["id"]: p for body in (sealed or {}).values() for p in body["products"]}
    if uuids is not None:
        for pid, p in products.items():
            if p["contents"].get("cards"):
                products[pid] = {**p, "contents": {**p["contents"], "cards": [
                    {**item, "print": uuids[item["print"]]} for item in p["contents"]["cards"]]}}
    out: dict[str, dict] = {"sets": by_set, "cards": {}, "printings": {}, "archetypes": {}, "products": products}
    members: dict[str, list[str]] = collections.defaultdict(list)
    for body in files.values():
        for card in body["cards"]:
            cid = card["id"]
            out["cards"][cid] = {**card, "prints": [p["id"] if uuids is None else uuids[p["id"]]
                                                   for p in card["prints"]]}
            for slug in card.get("archetypes", []):
                members[slug].append(cid)
            for p in card["prints"]:
                rarity_tier = tier(p["rarity"])
                finish = is_foil(p["rarity"])
                for edition in print_editions(p, by_set[p["set"]]["editions"]):
                    key = printing_id(p["id"], "en", edition)
                    pid = key if uuids is None else printing_id(uuids[p["id"]], "en", edition)
                    out["printings"][pid] = {
                        "id": pid, **({} if uuids is None else {"key": key}),
                        "print": p["id"] if uuids is None else uuids[p["id"]],
                        **({} if uuids is None else {"printKey": p["id"]}), "card": cid, "set": p["set"],
                        **{k: p[k] for k in ("number", "region", "variant", "source") if k in p},
                        "rarity": p["rarity"],
                        **({"rarityTier": rarity_tier} if rarity_tier is not None else {}),
                        "language": "en", "edition": edition,
                        "finish": None if finish is None else "foil" if finish else "nonfoil",
                        "identifiers": p.get("identifiers", {}),
                        **({"tcgplayer": {k: v for k, v in p["tcgplayer"].items() if k != "editionProducts"}}
                           if "tcgplayer" in p else {}),
                        **({"tcgplayerPrice": price} if (price := price_of(p, edition)) else {}),
                        **({"scan": p["scans"][edition]} if edition in p.get("scans", {}) else {}),
                    }
    for a in archetypes["archetypes"]:
        out["archetypes"][a["slug"]] = {**a, "members": sorted(members.get(a["slug"], []), key=int)}
    return out
