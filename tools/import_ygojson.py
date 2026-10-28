"""Add YGOJSON's identifiers, editions, names and series to the YGOPRODeck-led files, and write review/ygojson.json.

    uv run python tools/import_ygojson.py

Reads sets/sets.json, data/cards/*.json and data/archetypes.json (written by import_ygoprodeck) and the YGOJSON
aggregate under .cache/ygojson (sets.json, cards.json, series.json), and rewrites the three files in place, adding
only:

  sets        identifiers.ygojsonId / yugipediaId / konamiDatabaseIds, editions (when YGOJSON states some),
              releases[0].releaseDate and releases[0].keyArt (only where the set has none). A YGOPRODeck set is
              matched to one YGOJSON set with an English release (locale en, else na, eu, ae, oc) by five rules,
              applied in order to the sets still unmatched on both sides: exact English name; normalised name plus
              prefix equal to our code; normalised name alone when unique on both sides; Yugipedia page title equal
              to our name; prefix alone when unique on both sides.
  cards       identifiers.ygojsonId / yugipediaIds, identifiers.konamiId (only when the card has none), and
              names.<lang> for every language but en. A card matches by YGOJSON's YGOPRODeck id, else by a password.
  archetypes  each YGOJSON series is matched to one of our archetypes by name; a match gets names, isArchetype and
              identifiers. Archetypes with no series get isArchetype true. A series flagged archetype that we lack
              is added (source ygojson) and its members' cards gain its slug.

Everything it does not mention stays as it was, so it is idempotent and can be rerun after import_ygoprodeck.
"""
from __future__ import annotations

import collections
import html
import json
import re
from pathlib import Path
from urllib.parse import quote

import ygjson

CACHE = ygjson.ROOT / ".cache" / "ygojson"
REVIEW = ygjson.ROOT / "review" / "ygojson.json"
SOURCE = "ygojson"

_EDITIONS = {"1st": "first", "unlimited": "unlimited", "limited": "limited"}
_EDITION_ORDER = ("first", "unlimited", "limited")
# The language keys the schemas accept: ja_romaji and ko_rr are romanisations, not languages.
_LANGUAGE = re.compile(r"^[a-z]{2}(-[A-Za-z]+)?$")
_NON_ALNUM = re.compile(r"[\W_]+")
# Characters MediaWiki leaves unescaped in a page title.
_WIKI_SAFE = ";@$!*(),/~:"

# YGOJSON files a set's English release under en, or, for the older sets, under the region it came out in.
ENGLISH_LOCALES = ("en", "na", "eu", "ae", "oc")
RULES = ("exact_name", "name_and_prefix", "name", "yugipedia_name", "prefix")


def normalise(name: str) -> str:
    """Lower case, apostrophes unified, every run of non-alphanumerics one space, trimmed."""
    text = html.unescape(name).lower().replace("’", "'")
    return _NON_ALNUM.sub(" ", text).strip()


def english(ygo_set: dict) -> dict:
    """The set's English locale: en, else the first regional English one (na, eu, ae, oc)."""
    locales = ygo_set["locales"]
    return locales[next(code for code in ENGLISH_LOCALES if code in locales)]


def en_prefix(ygo_set: dict) -> str | None:
    """The English prefix before its hyphen (LOB-EN -> LOB, AST- -> AST), None when the locale has none."""
    prefix = english(ygo_set).get("prefix")
    return prefix.split("-", 1)[0] if prefix else None


def yugipedia_name(ygo_set: dict) -> str | None:
    return ((ygo_set.get("externalIDs") or {}).get("yugipedia") or {}).get("name")


def en_sets(ygo_sets: list[dict]) -> list[dict]:
    """The YGOJSON sets with an English release and an English name, the only ones that can be one of ours."""
    return [s for s in ygo_sets if any(c in (s.get("locales") or {}) for c in ENGLISH_LOCALES)
            and (s.get("name") or {}).get("en")]


def match_sets(ours: list[dict], theirs: list[dict]) -> dict[str, tuple[dict, str]]:
    """{our set id: (YGOJSON set, rule)} for the ygoprodeck sets of ours, by the four rules in RULES."""
    ours = sorted((s for s in ours if s["source"] == "ygoprodeck"), key=lambda s: s["id"])
    found: dict[str, tuple[dict, str]] = {}
    claimed: set[str] = set()

    def free_ours():
        return [s for s in ours if s["id"] not in found]

    def free_theirs():
        return [g for g in theirs if g["id"] not in claimed]

    def take(s, g, rule):
        found[s["id"]] = (g, rule)
        claimed.add(g["id"])

    # 1. exact English name. Two YGOJSON sets with one name are told apart by prefix.
    by_name = collections.defaultdict(list)
    for g in free_theirs():
        by_name[g["name"]["en"]].append(g)
    for s in free_ours():
        cands = [g for g in by_name.get(s["name"], []) if g["id"] not in claimed]
        if len(cands) > 1:
            cands = [g for g in cands if en_prefix(g) == s["code"]]
        if len(cands) == 1:
            take(s, cands[0], "exact_name")

    # 2. normalised name and prefix == code, unique on both sides.
    keyed = collections.defaultdict(list)
    for g in free_theirs():
        keyed[(normalise(g["name"]["en"]), en_prefix(g))].append(g)
    ours_keys = collections.Counter((normalise(s["name"]), s["code"]) for s in free_ours())
    for s in free_ours():
        key = (normalise(s["name"]), s["code"])
        if ours_keys[key] == 1 and len(keyed.get(key, [])) == 1:
            take(s, keyed[key][0], "name_and_prefix")

    # 3. normalised name alone, unique on both sides.
    named = collections.defaultdict(list)
    for g in free_theirs():
        named[normalise(g["name"]["en"])].append(g)
    ours_names = collections.Counter(normalise(s["name"]) for s in free_ours())
    for s in free_ours():
        key = normalise(s["name"])
        if ours_names[key] == 1 and len(named.get(key, [])) == 1:
            take(s, named[key][0], "name")

    # 4. the Yugipedia page title equals our name: YGOJSON names two sets alike (the 25th Anniversary reprints) but
    # their pages differ.
    titled = collections.defaultdict(list)
    for g in free_theirs():
        if yugipedia_name(g):
            titled[yugipedia_name(g)].append(g)
    ours_exact = collections.Counter(s["name"] for s in free_ours())
    for s in free_ours():
        if ours_exact[s["name"]] == 1 and len(titled.get(s["name"], [])) == 1:
            take(s, titled[s["name"]][0], "yugipedia_name")

    # 5. our code == the English prefix, unique on both sides.
    prefixed = collections.defaultdict(list)
    for g in free_theirs():
        if en_prefix(g):
            prefixed[en_prefix(g)].append(g)
    ours_codes = collections.Counter(s["code"] for s in free_ours())
    for s in free_ours():
        if ours_codes[s["code"]] == 1 and len(prefixed.get(s["code"], [])) == 1:
            take(s, prefixed[s["code"]][0], "prefix")
    return found


def yugipedia_page(name: str) -> str:
    return "https://yugipedia.com/wiki/" + quote(name.replace(" ", "_"), safe=_WIKI_SAFE)


def apply_set(s: dict, g: dict) -> None:
    """Fold the matched YGOJSON set into ours, touching only the fields the module docstring lists."""
    en = english(g)
    ids = s.setdefault("identifiers", {})
    ids["ygojsonId"] = g["id"]
    yugipedia = (g.get("externalIDs") or {}).get("yugipedia") or {}
    if yugipedia.get("id") is not None:
        ids["yugipediaId"] = yugipedia["id"]
    db_ids = (en.get("externalIDs") or {}).get("dbIDs")
    if db_ids:
        ids["konamiDatabaseIds"] = sorted({*ids.get("konamiDatabaseIds", []), *(int(i) for i in db_ids)})
    editions = {_EDITIONS[e] for e in en.get("editions") or [] if e in _EDITIONS}
    if editions:
        s["editions"] = [e for e in _EDITION_ORDER if e in editions]
    release = s["releases"][0]
    if en.get("date") and not release.get("releaseDate"):
        release["releaseDate"] = en["date"]
    if en.get("image") and yugipedia.get("name") and not release.get("keyArt"):
        release["keyArt"] = {"url": en["image"], "source": yugipedia_page(yugipedia["name"])}


def languages(names: dict) -> dict[str, str]:
    """{language: name} for the keys that are languages, dropping romanisations and empty names."""
    return {lang: name for lang, name in names.items() if _LANGUAGE.match(lang) and name}


def match_cards(ours: list[dict], theirs: list[dict]) -> dict[str, dict]:
    """{our card id: YGOJSON card}: by YGOJSON's YGOPRODeck id, else by a password no other match has claimed."""
    by_ygoprodeck = collections.defaultdict(list)
    by_password = collections.defaultdict(list)
    for g in theirs:
        ext = ((g.get("externalIDs") or {}).get("ygoprodeck") or {}).get("id")
        if ext is not None:
            by_ygoprodeck[str(ext)].append(g)
        for password in g.get("passwords") or []:
            by_password[str(password)].append(g)
    found: dict[str, dict] = {}
    claimed: set[str] = set()
    for card in ours:
        cands = by_ygoprodeck.get(card["id"], [])
        if len(cands) == 1 and cands[0]["id"] not in claimed:
            found[card["id"]] = cands[0]
            claimed.add(cands[0]["id"])
    for card in ours:
        if card["id"] in found:
            continue
        cands = [g for g in by_password.get(card["id"], []) if g["id"] not in claimed]
        if len(cands) == 1:
            found[card["id"]] = cands[0]
            claimed.add(cands[0]["id"])
    return found


def apply_card(card: dict, g: dict) -> None:
    ids = card["identifiers"]
    ids["ygojsonId"] = g["id"]
    yugipedia = [e["id"] for e in (g.get("externalIDs") or {}).get("yugipedia") or [] if e.get("id") is not None]
    if yugipedia:
        ids["yugipediaIds"] = sorted(set(yugipedia))
    db_id = (g.get("externalIDs") or {}).get("dbID")
    if db_id is not None and "konamiId" not in ids:
        ids["konamiId"] = int(db_id)
    for lang, name in languages({k: (v or {}).get("name") for k, v in (g.get("text") or {}).items()}).items():
        if lang != "en":
            card["names"][lang] = name


def match_series(archetypes: list[dict], series: list[dict]) -> dict[str, dict]:
    """{our archetype slug: series}: exact name first, then case-insensitively where one archetype and one series
    are left with that lower-cased name."""
    by_name = {a["name"]: a for a in archetypes}
    by_id = {g["id"]: g for g in series}
    found: dict[str, dict] = {}
    # A series we matched on an earlier run keeps its archetype, so two series that share a name stay put.
    for a in archetypes:
        g = by_id.get((a.get("identifiers") or {}).get("ygojsonId"))
        if g and g["name"]["en"].casefold() == a["name"].casefold():
            found[a["slug"]] = g
    used = {g["id"] for g in found.values()}
    # Series that share a name: the one flagged archetype first, then by id, whatever order the file is in.
    for g in sorted(series, key=lambda g: (not g["archetype"], g["id"])):
        a = by_name.get(g["name"]["en"])
        if a and a["slug"] not in found and g["id"] not in used:
            found[a["slug"]] = g
            used.add(g["id"])
    used = {g["id"] for g in found.values()}
    left_a = collections.defaultdict(list)
    for a in archetypes:
        if a["slug"] not in found:
            left_a[a["name"].casefold()].append(a)
    left_g = collections.defaultdict(list)
    for g in series:
        if g["id"] not in used:
            left_g[g["name"]["en"].casefold()].append(g)
    for key, group in left_g.items():
        if len(group) == 1 and len(left_a.get(key, [])) == 1:
            found[left_a[key][0]["slug"]] = group[0]
    return found


def apply_archetype(a: dict, g: dict) -> None:
    a["names"] = languages(g["name"])
    a["isArchetype"] = bool(g["archetype"])
    a.setdefault("identifiers", {})["ygojsonId"] = g["id"]
    yugipedia = (g.get("externalIDs") or {}).get("yugipedia") or {}
    if yugipedia.get("id") is not None:
        a["identifiers"]["yugipediaId"] = yugipedia["id"]


def sync_archetypes(archetypes: list[dict], series: list[dict]) -> tuple[dict[str, dict], list[dict], list[dict]]:
    """Update the archetype list in place. Returns {slug: series} for the archetypes that matched, the added
    archetypes, and the series skipped because their slug was taken."""
    matched = match_series(archetypes, series)
    for a in archetypes:
        if a["slug"] in matched:
            apply_archetype(a, matched[a["slug"]])
        else:
            a.setdefault("isArchetype", True)  # YGOPRODeck lists only true archetypes
    taken = {a["slug"] for a in archetypes}
    used = {g["id"] for g in matched.values()}
    added, skipped = [], []
    for g in sorted(series, key=lambda g: (g["name"]["en"], g["id"])):
        if g["id"] in used or not g["archetype"]:
            continue
        slug = ygjson.slugify(g["name"]["en"])
        if slug in taken:
            skipped.append(g)
            continue
        a = {"slug": slug, "name": g["name"]["en"], "source": SOURCE}
        apply_archetype(a, g)
        taken.add(slug)
        archetypes.append(a)
        matched[slug] = g
        added.append(a)
    archetypes.sort(key=lambda a: a["slug"])
    return matched, added, skipped


def add_memberships(cards: list[dict], archetypes: list[dict], matched: dict[str, dict]) -> int:
    """Give each of our cards named in a ygojson-sourced archetype's series the archetype's slug. Archetypes
    YGOPRODeck lists keep the members YGOPRODeck gives. Returns the number of memberships added."""
    members = collections.defaultdict(list)  # YGOJSON card uuid -> slugs
    for a in archetypes:
        if a["source"] == SOURCE and a["slug"] in matched:
            for uuid in matched[a["slug"]].get("members") or []:
                members[uuid].append(a["slug"])
    count = 0
    for card in cards:
        slugs = members.get(card["identifiers"].get("ygojsonId"))
        if slugs:
            merged = sorted({*card.get("archetypes", []), *slugs})
            count += len(merged) - len(card.get("archetypes", []))
            card["archetypes"] = merged
    return count


def review_body(sets: list[dict], found: dict, theirs: list[dict], cards: list[dict], card_found: dict,
                skipped: list[dict]) -> dict:
    claimed = {g["id"] for g, _ in found.values()}
    by_id = {s["id"]: s for s in sets}
    return {
        "setsUnmatched": [{"id": s["id"], "name": s["name"], "code": s["code"]}
                          for s in sorted(sets, key=lambda s: s["id"])
                          if s["source"] == "ygoprodeck" and s["id"] not in found],
        "ygojsonSetsUnclaimed": [{"id": g["id"], "name": g["name"]["en"], "prefix": english(g).get("prefix")}
                                 for g in sorted(theirs, key=lambda g: (g["name"]["en"], g["id"]))
                                 if g["id"] not in claimed],
        "cardsUnmatched": [{"id": c["id"], "name": c["name"]} for c in sorted(cards, key=lambda c: int(c["id"]))
                           if c["id"] not in card_found],
        "archetypesSkipped": [{"id": g["id"], "name": g["name"]["en"], "slug": ygjson.slugify(g["name"]["en"])}
                              for g in sorted(skipped, key=lambda g: (g["name"]["en"], g["id"]))],
        # Not asked for by the spec: the matches that were not by exact name, for a human to eyeball.
        "setsMatchedByFallback": [{"id": sid, "name": by_id[sid]["name"], "ygojsonName": g["name"]["en"],
                                   "code": by_id[sid]["code"], "prefix": english(g).get("prefix"), "rule": rule}
                                  for sid, (g, rule) in sorted(found.items()) if rule != "exact_name"],
    }


def _read(name: str) -> list[dict]:
    return json.loads((CACHE / name).read_text(encoding="utf-8"))


def main() -> None:
    sets = ygjson.load_sets()
    files = ygjson.load_cards()
    archetypes = ygjson.load_archetypes()
    cards = [c for body in files.values() for c in body["cards"]]

    theirs = en_sets(_read("sets.json"))
    found = match_sets(sets, theirs)
    by_id = {s["id"]: s for s in sets}
    for sid, (g, _) in found.items():
        apply_set(by_id[sid], g)

    card_found = match_cards(cards, _read("cards.json"))
    by_card = {c["id"]: c for c in cards}
    for cid, g in card_found.items():
        apply_card(by_card[cid], g)

    series = _read("series.json")
    matched, added, skipped = sync_archetypes(archetypes["archetypes"], series)
    memberships = add_memberships(cards, archetypes["archetypes"], matched)

    ygjson.save_json(ygjson.SETS, sets)
    for bucket, body in files.items():
        ygjson.save_json(ygjson.CARDS / f"{bucket}.json", body)
    ygjson.save_json(ygjson.ARCHETYPES, archetypes)
    review = review_body(sets, found, theirs, cards, card_found, skipped)
    ygjson.save_json(REVIEW, review)

    ours = sum(1 for s in sets if s["source"] == "ygoprodeck")
    by_rule = collections.Counter(rule for _, rule in found.values())
    print(f"sets: {len(found)} of {ours} matched ({', '.join(f'{r} {by_rule[r]}' for r in RULES)}); "
          f"{len(review['setsUnmatched'])} of ours unmatched, {len(review['ygojsonSetsUnclaimed'])} of "
          f"{len(theirs)} YGOJSON sets with an English release unclaimed")
    print(f"cards: {len(card_found)} of {len(cards)} matched, {len(review['cardsUnmatched'])} unmatched")
    own = [a for a in archetypes["archetypes"] if a["source"] != SOURCE]
    print(f"archetypes: {sum(1 for a in own if a['slug'] in matched)} of {len(own)} matched, "
          f"{len(added)} added from {len(series)} series, {len(skipped)} skipped, "
          f"{memberships} card memberships added")


if __name__ == "__main__":
    main()
