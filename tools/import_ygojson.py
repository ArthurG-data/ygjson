"""Add YGOJSON's identifiers, editions, names and series to the YGOPRODeck-led files, and write review/ygojson.json.

    uv run python tools/import_ygojson.py [--update | --commit SHA]

Reads sets/sets.json, data/cards/*.json and data/archetypes.json (written by import_ygoprodeck) and the YGOJSON
aggregate under .cache/ygojson (sets.json, cards.json, series.json), and rewrites the three files in place. The
aggregate is the commit of YGOJSON's v1/aggregate branch that sources.json pins, downloaded when the cache holds
another (see ygojson_aggregate.py); --update takes the branch's current commit instead, --commit a given one, and
sources.json records the commit read. It adds only:

  sets        identifiers.ygojsonId / yugipediaId / konamiDatabaseIds, editions (when YGOJSON states some),
              releases[0].releaseDate and releases[0].keyArt (only where the set has none). A YGOPRODeck set is
              matched to one YGOJSON set with an English release (locale en, else na, eu, ae, oc) by five rules,
              applied in order to the sets still unmatched on both sides: exact English name; normalised name plus
              prefix equal to our code; normalised name alone when unique on both sides; Yugipedia page title equal
              to our name; prefix alone when unique on both sides.
  cards       identifiers.ygojsonId / yugipediaIds, identifiers.konamiId (only when the card has none), and
              names.<lang> for every language but en. A card matches by YGOJSON's YGOPRODeck id, else by a password.
  prints      scans: {edition: url}, the Yugipedia scan of the print in each edition, from the English locales'
              cardImages of the print's matched set (see match_scans). Written afresh on every run.
  archetypes  each YGOJSON series is matched to one of our archetypes by name; a match gets names, isArchetype and
              identifiers. Archetypes with no series get isArchetype true. A series flagged archetype that we lack
              is added (source ygojson) and its members' cards gain its slug.

Everything it does not mention stays as it was, so it is idempotent and can be rerun after import_ygoprodeck.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from collections.abc import Mapping, Sequence

import decisions
import rarities
import sources
import ygjson
import ygojson_aggregate
from yugipedia import page_url

CACHE = ygjson.ROOT / ".cache" / "ygojson"
REVIEW = ygjson.ROOT / "review" / "ygojson.json"
SOURCE = "ygojson"

_EDITIONS = {"1st": "first", "unlimited": "unlimited", "limited": "limited"}
_EDITION_ORDER = ("first", "unlimited", "limited")
# The language keys the schemas accept: ja_romaji and ko_rr are romanisations, not languages.
_LANGUAGE = re.compile(r"^[a-z]{2}(-[A-Za-z]+)?$")

# YGOJSON files a set's English release under en, or, for the older sets, under the region it came out in.
ENGLISH_LOCALES = ("en", "na", "eu", "ae", "oc")
RULES = ("exact_name", "name_and_prefix", "name", "yugipedia_name", "prefix")


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
    """{our set id: (YGOJSON set, rule)} for the ygoprodeck sets of ours, by the five rules in RULES, in order."""
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
        keyed[(ygjson.normalise(g["name"]["en"]), en_prefix(g))].append(g)
    ours_keys = collections.Counter((ygjson.normalise(s["name"]), s["code"]) for s in free_ours())
    for s in free_ours():
        key = (ygjson.normalise(s["name"]), s["code"])
        if ours_keys[key] == 1 and len(keyed.get(key, [])) == 1:
            take(s, keyed[key][0], "name_and_prefix")

    # 3. normalised name alone, unique on both sides.
    named = collections.defaultdict(list)
    for g in free_theirs():
        named[ygjson.normalise(g["name"]["en"])].append(g)
    ours_names = collections.Counter(ygjson.normalise(s["name"]) for s in free_ours())
    for s in free_ours():
        name = ygjson.normalise(s["name"])
        if ours_names[name] == 1 and len(named.get(name, [])) == 1:
            take(s, named[name][0], "name")

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
        release["keyArt"] = {"url": en["image"], "source": page_url(yugipedia["name"])}


def languages(names: dict) -> dict[str, str]:
    """{language: name} for the keys that are languages, dropping romanisations and empty names, with stray spaces
    cleaned (ygjson.clean_name)."""
    return {lang: ygjson.clean_name(name) for lang, name in names.items()
            if _LANGUAGE.match(lang) and name and name.strip()}


def canonical_password(password) -> str:
    """A password without leading zeros, as our card ids write it: YGOJSON's "06850209" is our "6850209"."""
    text = str(password).strip()
    return str(int(text)) if text.isdigit() else text


def match_cards(ours: list[dict], theirs: list[dict]) -> dict[str, dict]:
    """{our card id: YGOJSON card}: by YGOJSON's YGOPRODeck id, else by a password no other match has claimed."""
    by_ygoprodeck = collections.defaultdict(list)
    by_password = collections.defaultdict(list)
    for g in theirs:
        ext = ((g.get("externalIDs") or {}).get("ygoprodeck") or {}).get("id")
        if ext is not None:
            by_ygoprodeck[str(ext)].append(g)
        for password in g.get("passwords") or []:
            by_password[canonical_password(password)].append(g)
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
    # YGOJSON's text is rewritten afresh: only what the Yugipedia stage added outlives a run.
    text = {lang: t for lang, t in (card.get("text") or {}).items() if lang == "en" or t.get("source") == "yugipedia"}
    for lang, t in (g.get("text") or {}).items():
        if lang == "en" or t.get("official") is False:
            continue
        found = {k: t[k] for k in ("effect", "pendulumEffect") if t.get(k) and t[k].strip()}
        if found and languages({lang: "x"}):
            text[lang] = found
    if text:
        card["text"] = text
    else:
        card.pop("text", None)


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
        owner = by_name.get(g["name"]["en"])
        if owner and owner["slug"] not in found and g["id"] not in used:
            found[owner["slug"]] = g
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
    a["names"] = {**languages(g["name"]), "en": a["name"]}  # our name leads: YGOJSON writes some in lower case
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


def match_scans(found: Mapping[str, tuple[dict, str]], card_found: Mapping[str, dict],
                cards: list[dict]) -> tuple[dict[str, dict[str, str]], list[dict]]:
    """{print id: {edition: scan url}} from the cardImages of each matched set's English locales (`found`, from
    match_sets; `card_found` from match_cards), and the printings
    with a scan that could not be placed. A YGOJSON printing is the locale's prefix plus its suffix (LOB-EN + 005) for
    one card. Its print is the one YGOPRODeck print of that set, card and number at its rarity, else the only
    YGOPRODeck print of that number when YGOJSON has only one printing of it there (a rarity the two disagree on, or
    one still unknown). A number we have no print of is another region's printing (AGOV-AE001) and is passed over; a
    colour version (rare-blue) is a print import_tcgcsv mints, so it is passed over too, as are the prints it mints."""
    card_of = {g["id"]: cid for cid, g in card_found.items()}
    ours: dict[tuple, list[dict]] = collections.defaultdict(list)
    for c in cards:
        for p in c["prints"]:
            if p.get("source") != "tcgplayer" and not p.get("variant"):
                ours[(p["set"], c["id"], p.get("number"))].append(p)
    scans: dict[str, dict[str, str]] = collections.defaultdict(dict)
    unplaced = []
    for sid, (g, _) in sorted(found.items()):
        for code, locale in sorted((g.get("locales") or {}).items()):
            if code not in ENGLISH_LOCALES or not locale.get("prefix"):
                continue
            images = locale.get("cardImages") or {}
            printings: dict[tuple, list[dict]] = collections.defaultdict(list)
            for content in g.get("contents", []):
                for e in content.get("cards", []) if code in content.get("locales", []) else ():
                    if e.get("card") in card_of and e.get("suffix") and "-" not in (e.get("rarity") or ""):
                        printings[(sid, card_of[e["card"]], locale["prefix"] + e["suffix"])].append(e)
            for key, entries in sorted(printings.items()):
                prints = ours.get(key, [])
                for e in entries if prints else ():
                    scanned = {_EDITIONS[ed]: urls[e["id"]] for ed, urls in images.items() if e["id"] in urls}
                    if not scanned:
                        continue
                    rarity = rarities.YGOJSON.get(e.get("rarity") or "")
                    exact = [p for p in prints if p["rarity"] == rarity]
                    twins = [x for x in entries if rarities.YGOJSON.get(x.get("rarity") or "") == rarity]
                    if rarity and len(exact) == 1 and len(twins) == 1:
                        target = exact[0]
                    elif len(prints) == 1 and len(entries) == 1:
                        target = prints[0]
                    else:
                        unplaced.append({"set": sid, "card": key[1], "number": key[2], "rarity": e.get("rarity"),
                                         "ygojsonId": e["id"],
                                         "reason": f"{_n(len(prints), 'print')} of the number, "
                                                   f"{_n(len(entries), 'YGOJSON printing')}, none settled by rarity"})
                        continue
                    for edition, url in scanned.items():
                        scans[target["id"]].setdefault(edition, url)
    return dict(scans), unplaced


def _n(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def apply_scans(cards: list[dict], scans: dict[str, dict[str, str]]) -> int:
    """Give each print the scans match_scans found for it and take away any it no longer has. Returns the number of
    prints with scans."""
    n = 0
    for c in cards:
        for p in c["prints"]:
            p.pop("scans", None)
            if p["id"] in scans:
                p["scans"] = {e: scans[p["id"]][e] for e in _EDITION_ORDER if e in scans[p["id"]]}
                n += 1
    return n


def review_body(sets: list[dict], found: dict, theirs: list[dict], cards: list[dict], card_found: dict,
                skipped: list[dict], unplaced: Sequence[dict] = ()) -> dict:
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
        "scansUnplaced": list(unplaced),
    }


def _read(name: str) -> list[dict]:
    return json.loads((CACHE / name).read_text(encoding="utf-8"))


def pinned_cache(commit: str | None = None, update: bool = False) -> str:
    """The YGOJSON commit to import, with its files in CACHE: `commit` when given, else with `update` the branch's
    current commit, else the one sources.json pins. It is downloaded when the cache holds another."""
    want = commit or (ygojson_aggregate.head() if update else sources.load().get("ygojson", {}).get("commit"))
    if want is None:
        raise SystemExit("sources.json pins no YGOJSON commit: run with --update to take the branch's current one")
    if ygojson_aggregate.cached_commit(CACHE) != want:
        print(f"downloading YGOJSON {ygojson_aggregate.BRANCH} at {want}")
        ygojson_aggregate.download(want, CACHE)
    return want


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    pick = ap.add_mutually_exclusive_group()
    pick.add_argument("--update", action="store_true", help="import the branch's current commit")
    pick.add_argument("--commit", help="import this commit (a full sha)")
    args = ap.parse_args()
    commit = pinned_cache(args.commit, args.update)
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

    scans, unplaced = match_scans(found, card_found, cards)
    with_scans = apply_scans(cards, scans)

    series = _read("series.json")
    matched, added, skipped = sync_archetypes(archetypes["archetypes"], series)
    memberships = add_memberships(cards, archetypes["archetypes"], matched)

    ygjson.save_json(ygjson.SETS, sets)
    for bucket, body in files.items():
        ygjson.save_json(ygjson.CARDS / f"{bucket}.json", body)
    ygjson.save_json(ygjson.ARCHETYPES, archetypes)
    review = review_body(sets, found, theirs, cards, card_found, skipped, unplaced)
    decisions.save_review(REVIEW, review)
    sources.record("ygojson", sources.ygojson(commit, json.loads((CACHE / "meta.json").read_text(encoding="utf-8"))))

    ours = sum(1 for s in sets if s["source"] == "ygoprodeck")
    by_rule = collections.Counter(rule for _, rule in found.values())
    print(f"sets: {len(found)} of {ours} matched ({', '.join(f'{r} {by_rule[r]}' for r in RULES)}); "
          f"{len(review['setsUnmatched'])} of ours unmatched, {len(review['ygojsonSetsUnclaimed'])} of "
          f"{len(theirs)} YGOJSON sets with an English release unclaimed")
    print(f"cards: {len(card_found)} of {len(cards)} matched, {len(review['cardsUnmatched'])} unmatched")
    print(f"prints: {with_scans} with a Yugipedia scan, {len(review['scansUnplaced'])} scans unplaced")
    own = [a for a in archetypes["archetypes"] if a["source"] != SOURCE]
    print(f"archetypes: {sum(1 for a in own if a['slug'] in matched)} of {len(own)} matched, "
          f"{len(added)} added from {len(series)} series, {len(skipped)} skipped, "
          f"{memberships} card memberships added")


if __name__ == "__main__":
    main()
