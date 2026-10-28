"""Write sets/sets.json, data/cards/<bucket>.json, data/archetypes.json and review/rarities.json from YGOPRODeck.

    uv run python tools/import_ygoprodeck.py [--refresh]

YGOPRODeck is the lead source: a set is one distinct set name, a card is one YGOPRODeck card id, a print is one
(set, card, set number, rarity). The files are merged with what is already on disk by id: this tool owns the facts
YGOPRODeck states, and keeps what the later tools add (identifiers, names in other languages, TCGplayer matches,
parents, series, refined types and editions), so it can be rerun after any of them.
"""
from __future__ import annotations

import argparse
import collections
import html
import re
from pathlib import Path
from urllib.parse import quote

import rarities
import ygjson
import ygoprodeck

REVIEW = ygjson.ROOT / "review" / "rarities.json"
SOURCE = "ygoprodeck"

# Set type by name, first match wins, case-insensitive. Tins sit before the rest so Mega-Tins and Collectible Tins
# are tins; "tin" is a word here, not a substring (Destiny).
_TYPE_RULES: tuple[tuple[str, str], ...] = (
    (r"structure deck", "structure_deck"),
    (r"starter deck|\bstarter\b", "starter_deck"),
    (r"\btins?\b", "tin"),
    (r"special edition|deluxe edition|advanced? edition|secret edition|gold edition", "special_edition"),
    (r"sneak peek|sneak preview", "sneak_peek"),
    (r"duel terminal", "duel_terminal"),
    (r"speed duel", "speed_duel"),
    (r"promo|\bprize\b|participation|championship|\bjudge\b|\bjump\b", "promo"),
    (r"collector'?s set|\bcollection\b|\blegendary\b|box set|mega pack", "box_set"),
)
_TYPE_PATTERNS = tuple((re.compile(p, re.IGNORECASE), t) for p, t in _TYPE_RULES)

_KINDS = {"Spell Card": "spell", "Trap Card": "trap", "Token": "token", "Skill Card": "skill"}
_RANK_FRAMES = {"xyz", "xyz_pendulum"}
_PREFIX = re.compile(r"^([^-]+)-")
# What a print id can hold for a set number; YGOPRODeck's one placeholder (MF03-EN0??) is treated as no number.
_NUMBER = re.compile(r"^[A-Za-z0-9-]+$")
# Set fields this tool writes; everything else on an existing set is kept.
_SET_KEYS = ("code", "name", "source")


def set_type(name: str) -> str:
    for pattern, kind in _TYPE_PATTERNS:
        if pattern.search(name):
            return kind
    return "booster"


def set_editions(name: str) -> list[str]:
    """Placeholder until import_ygojson and import_tcgcsv state the real editions."""
    return ["limited"] if "limited edition" in name.lower() else ["unlimited"]


def era_of(release_date: str | None, eras: list[dict]) -> str | None:
    """The era whose window holds the date. Dates are ISO strings, so they compare as text."""
    if not release_date:
        return None
    return next((e["code"] for e in eras if e["from"] <= release_date <= e.get("to", "9999-12-31")), None)


def collisions(slugs: dict[str, str]) -> dict[str, list[str]]:
    """{plain slug: [names]} for the names whose slug was changed to stay unique, with the names they clashed with."""
    by_plain = collections.defaultdict(list)
    for name in slugs:
        by_plain[ygjson.slugify(name)].append(name)
    return {slug: sorted(names) for slug, names in sorted(by_plain.items()) if len(names) > 1}


def _prefix_of(number: str) -> str | None:
    m = _PREFIX.match(number)
    return m.group(1) if m else None


def _number_prefixes(card_list: list[dict]) -> dict[str, str]:
    """{set name: its most common set-number prefix}, for sets cardsets.php gives no code."""
    counts: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for card in card_list:
        for row in card.get("card_sets", []):
            prefix = _prefix_of(row.get("set_code") or "")
            if prefix:
                counts[row["set_name"]][prefix] += 1
    return {name: max(sorted(c), key=c.__getitem__) for name, c in counts.items()}


def build_sets(card_list: list[dict], set_list: list[dict], eras: list[dict], existing: list[dict]
               ) -> tuple[list[dict], dict[str, str]]:
    """Returns the sets sorted by id and {set name: set id}. Existing sets that are not YGOPRODeck's (source
    tcgplayer) are kept as they are."""
    listed = {s["set_name"]: s for s in set_list}
    raw_names = set(listed) | {r["set_name"] for c in card_list for r in c.get("card_sets", [])}
    # YGOPRODeck escapes one name ("Legendary 5D&apos;s Decks"); the dataset carries the decoded text.
    decoded = {raw: html.unescape(raw) for raw in raw_names}
    slugs = ygjson.dedupe_slugs(decoded.values())
    ids = {raw: slugs[decoded[raw]] for raw in raw_names}
    prefixes = _number_prefixes(card_list)
    old = {s["id"]: s for s in existing}
    out = []
    for raw_name, set_id in sorted(ids.items(), key=lambda kv: kv[1]):
        info = listed.get(raw_name, {})
        name = decoded[raw_name]
        code = info.get("set_code") or prefixes.get(raw_name) or "UNKNOWN"
        s = {"id": set_id, "code": code, "name": name, "source": SOURCE,
             "type": set_type(name), "editions": set_editions(name)}
        prev = old.get(set_id, {})
        # What an earlier run or a later tool decided wins over the placeholder defaults.
        for key in ("type", "editions", "series", "parent", "tcgplayerGroupIds", "identifiers"):
            if key in prev:
                s[key] = prev[key]
        release = dict(prev["releases"][0]) if prev.get("releases") else {"language": "en"}
        release["name"] = name
        if info.get("tcg_date"):
            release["releaseDate"] = info["tcg_date"]
        if info.get("set_image"):
            release["keyArt"] = {"url": info["set_image"], "source": f"https://ygoprodeck.com/sets/{quote(code)}"}
        s["releases"] = [release]
        era = era_of(release.get("releaseDate"), eras) or prev.get("era")
        if era:
            s["era"] = era
        out.append(s)
    out += [s for s in existing if s.get("source") != SOURCE and s["id"] not in ids.values()]
    return sorted(out, key=lambda s: s["id"]), ids


def _present(value) -> bool:
    return value is not None


def card_entry(raw: dict) -> dict:
    """The card without its prints."""
    card_id = str(raw["id"])
    frame = raw["frameType"]
    misc = (raw.get("misc_info") or [{}])[0]
    kind = _KINDS.get(raw["type"], "monster")
    card: dict = {"id": card_id, "name": raw["name"], "names": {"en": raw["name"]}, "kind": kind, "frame": frame,
                  "hasEffect": bool(misc.get("has_effect")), "isTuner": "Tuner" in raw["type"],
                  "identifiers": {"ygoprodeckId": raw["id"]}}
    if raw["id"] < 100_000_000:
        card["passcode"] = raw["id"]
    if misc.get("konami_id") is not None:
        card["identifiers"]["konamiId"] = misc["konami_id"]
    if raw.get("attribute"):
        card["attribute"] = raw["attribute"].lower()
    if raw.get("race"):
        card["monsterType"] = raw["race"]
    if _present(raw.get("level")):
        card["rank" if frame in _RANK_FRAMES else "level"] = raw["level"]
    if _present(raw.get("linkval")):
        card["linkRating"] = raw["linkval"]
    if raw.get("linkmarkers"):
        card["linkArrows"] = raw["linkmarkers"]
    if _present(raw.get("scale")):
        card["scale"] = raw["scale"]
    for src, dst in (("atk", "atk"), ("def", "def")):
        if raw.get(src) not in (None, -1):
            card[dst] = raw[src]
    if typeline := [t for t in raw.get("typeline") or [] if t]:  # one card has [""]
        card["typeline"] = typeline
    if raw.get("archetype"):
        card["archetypes"] = []  # filled in by the caller, which holds the slug table
    for src, dst in (("tcg_date", "tcgDate"), ("ocg_date", "ocgDate")):
        if misc.get(src):
            card[dst] = misc[src]
    images = []
    for img in raw.get("card_images", []):
        image = {"id": img["id"], "card": img["image_url"]}
        if img.get("image_url_small"):
            image["small"] = img["image_url_small"]
        if img.get("image_url_cropped"):
            image["art"] = img["image_url_cropped"]
        images.append(image)
    if images:
        card["images"] = images
    return card


def build_prints(raw: dict, set_ids: dict[str, str]) -> tuple[list[dict], int, list[str]]:
    """The card's prints sorted by id, the number of duplicate rows skipped, and the raw strings that mapped to
    unknown (one per kept row). A row is a duplicate when an earlier row has the same print id, which covers
    exact repeats and two spellings of one rarity."""
    card_id = str(raw["id"])
    prints: dict[str, dict] = {}
    duplicates, unknown = 0, []
    for row in raw.get("card_sets", []):
        raw_rarity = row.get("set_rarity")
        rarity = rarities.canonical(raw_rarity)
        number = row.get("set_code") if _NUMBER.match(row.get("set_code") or "") else None
        set_id = set_ids[row["set_name"]]
        pid = ygjson.print_id(set_id, card_id, number, rarity)
        if pid in prints:
            duplicates += 1
            continue
        p = {"id": pid, "set": set_id, "rarity": rarity}
        if number:
            p["number"] = number
            region = ygjson.region_of(number)
            if region:
                p["region"] = region
        if rarity == rarities.UNKNOWN:
            unknown.append(raw_rarity)
            if raw_rarity:
                p["rawRarity"] = raw_rarity
        prints[pid] = p
    return [prints[k] for k in sorted(prints)], duplicates, unknown


def merge_card(card: dict, prev: dict | None, tcgplayer_sets: set[str], foreign_slugs: set[str] = frozenset()) -> dict:
    """Fold what other tools added to the card on disk into the freshly built one. foreign_slugs are the
    archetypes another tool owns (source ygojson): their memberships on the card are kept, YGOPRODeck's own
    archetype is taken fresh."""
    if prev is None:
        return card
    card["names"] = {**{k: v for k, v in prev.get("names", {}).items() if k != "en"}, **card["names"]}
    # A Konami id YGOPRODeck lacks but YGOJSON gave stays; one YGOPRODeck gives wins.
    card["identifiers"] = {**{k: v for k, v in prev.get("identifiers", {}).items() if k != "ygoprodeckId"},
                           **card["identifiers"]}
    kept = [a for a in prev.get("archetypes", []) if a in foreign_slugs]
    if kept:
        card["archetypes"] = sorted(set(card.get("archetypes", [])) | set(kept))
    old_prints = {p["id"]: p for p in prev.get("prints", [])}
    for p in card["prints"]:
        for key in ("identifiers", "tcgplayer", "editions"):
            if key in old_prints.get(p["id"], {}):
                p[key] = old_prints[p["id"]][key]
    ours = {p["id"] for p in card["prints"]}
    card["prints"] += [p for p in prev.get("prints", []) if p["id"] not in ours and p["set"] in tcgplayer_sets]
    card["prints"].sort(key=lambda p: p["id"])
    return card


def build_cards(card_list: list[dict], set_ids: dict[str, str], archetype_slugs: dict[str, str],
                existing: dict[str, dict], tcgplayer_sets: set[str] = frozenset(),
                foreign_slugs: set[str] = frozenset()) -> tuple[dict[str, dict], dict]:
    """Returns {bucket: file body} and the counts: duplicates and the unknown rarity strings."""
    old = {c["id"]: c for body in existing.values() for c in body["cards"]}
    files: dict[str, list[dict]] = collections.defaultdict(list)
    duplicates, unknown = 0, collections.Counter()
    for raw in sorted(card_list, key=lambda r: r["id"]):
        card = card_entry(raw)
        if "archetypes" in card:
            card["archetypes"] = [archetype_slugs[raw["archetype"]]]
        card["prints"], dup, unk = build_prints(raw, set_ids)
        duplicates += dup
        unknown.update(unk)
        files[ygjson.card_bucket(card["id"])].append(merge_card(card, old.get(card["id"]), tcgplayer_sets, foreign_slugs))
    # A card another tool added and YGOPRODeck lacks stays where it is.
    seen = {c["id"] for cards in files.values() for c in cards}
    for cid, prev in old.items():
        if cid not in seen:
            files[ygjson.card_bucket(cid)].append(prev)
    bodies = {bucket: {"cards": sorted(cards, key=lambda c: int(c["id"]))} for bucket, cards in sorted(files.items())}
    return bodies, {"duplicates": duplicates, "unknown": unknown}


def build_archetypes(card_list: list[dict], listed: list[str], existing: dict) -> tuple[dict, dict[str, str]]:
    names = set(listed) | {c["archetype"] for c in card_list if c.get("archetype")}
    slugs = ygjson.dedupe_slugs(names)
    old = {a["slug"]: a for a in existing.get("archetypes", [])}
    out = []
    for name, slug in slugs.items():
        a = {"slug": slug, "name": name, "source": SOURCE}
        for key in ("names", "isArchetype", "identifiers"):
            if key in old.get(slug, {}):
                a[key] = old[slug][key]
        out.append(a)
    out += [a for a in existing.get("archetypes", []) if a["slug"] not in slugs.values() and a.get("source") != SOURCE]
    return {"archetypes": sorted(out, key=lambda a: a["slug"])}, slugs


def review_body(unknown: collections.Counter, duplicates: int) -> dict:
    rows = sorted(unknown.items(), key=lambda kv: (-kv[1], kv[0]))
    return {"unknown": [{"rarity": raw, "prints": n} for raw, n in rows], "duplicateRows": duplicates}


def load_existing_cards() -> dict[str, dict]:
    return ygjson.load_cards() if ygjson.CARDS.exists() else {}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="download the YGOPRODeck files again")
    refresh = parser.parse_args().refresh
    cache = ygoprodeck.DEFAULT_CACHE
    card_list = ygoprodeck.cards(cache, refresh)
    set_list = ygoprodeck.sets(cache, refresh)
    archetype_names = ygoprodeck.archetypes(cache, refresh)

    existing_sets = ygjson.load_sets() if ygjson.SETS.exists() else []
    existing_archetypes = ygjson.load_archetypes() if ygjson.ARCHETYPES.exists() else {}
    sets, set_ids = build_sets(card_list, set_list, ygjson.load_eras(), existing_sets)
    archetypes, archetype_slugs = build_archetypes(card_list, archetype_names, existing_archetypes)
    tcgplayer_sets = {s["id"] for s in sets if s["source"] != SOURCE}
    foreign_slugs = {a["slug"] for a in archetypes["archetypes"] if a.get("source") != SOURCE}
    files, counts = build_cards(card_list, set_ids, archetype_slugs, load_existing_cards(), tcgplayer_sets, foreign_slugs)

    ygjson.save_json(ygjson.SETS, sets)
    for bucket, body in files.items():
        ygjson.save_json(ygjson.CARDS / f"{bucket}.json", body)
    ygjson.save_json(ygjson.ARCHETYPES, archetypes)
    ygjson.save_json(REVIEW, review_body(counts["unknown"], counts["duplicates"]))

    set_collisions, archetype_collisions = collisions(set_ids), collisions(archetype_slugs)
    print(f"{len(sets)} sets, {sum(len(b['cards']) for b in files.values())} cards, "
          f"{sum(len(c['prints']) for b in files.values() for c in b['cards'])} prints, "
          f"{len(archetypes['archetypes'])} archetypes, {sum(counts['unknown'].values())} unknown-rarity rows, "
          f"{counts['duplicates']} duplicate rows, {len(set_collisions)} set slug collisions, "
          f"{len(archetype_collisions)} archetype slug collisions")
    for label, found in (("set", set_collisions), ("archetype", archetype_collisions)):
        for slug, names in found.items():
            print(f"  {label} {slug}: {names}")


if __name__ == "__main__":
    main()
