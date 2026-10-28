"""Add Yugipedia's set infobox to sets/sets.json, and write review/yugipedia.json.

    uv run python tools/import_yugipedia.py

Each set with source ygoprodeck is matched to its Yugipedia page: by identifiers.yugipediaId (written by
import_ygojson), else by title (the set's name, then the name without a leading "Yu-Gi-Oh! "). The pages come from
.cache/yugipedia (see yugipedia.py; only a page not yet cached is fetched). The {{Infobox set}} of the page gives:

  type        mappings/set_types.json from the infobox type, then its series; two name rules on top (a set named
              "...Sneak Peek..." whose infobox type is a participation card is sneak_peek, a set named
              "...: Special Edition" is special_edition). A type the mapping lacks goes to review and leaves the
              set's current type.
  series      the infobox series as written, when it has one.
  identifiers yugipediaId (only for a set found by title), konamiDatabaseIds united with every *database_id value.
  code        the prefix before the hyphen of `prefix` / `en_prefix`, only for a set whose code is UNKNOWN.
  releases[0] releaseDate when the set has none: the first date that parses of na_release_date, en_release_date,
              release_date, else the earliest of the other *_release_date values (a month-only date is the 1st).
              keyArt when the set has none and the infobox has an image: Special:FilePath of the file, the page as
              source.
  parent      a sneak_peek, special_edition or promo set (a promo only when its name says premiere or promotional
              card) gets the one booster that shares its code, whose name its name starts with, or that the two
              infoboxes' other_sets name (the child's lists the booster in italics or a link, the booster's lists the
              child). Two or more boosters go to review. A parent already on the set is kept.
  era         a set with no era takes the era of its release date, else its parent's.

Everything else on a set stays as it was, so the tool is idempotent and survives a rerun of import_ygoprodeck and
import_ygojson, which keep type, series, parent, identifiers and editions.
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

import import_ygoprodeck
import ygjson
import yugipedia

MAPPING = ygjson.ROOT / "mappings" / "set_types.json"
REVIEW = ygjson.ROOT / "review" / "yugipedia.json"
SOURCE = "ygoprodeck"

_DATABASE_ID = re.compile(r"(?:^|_)database_id$")
_RELEASE_DATE = re.compile(r"release_date$")
_PREFERRED_DATES = ("na_release_date", "en_release_date", "release_date")
CHILD_TYPES = ("sneak_peek", "special_edition", "promo")
_PROMO_CHILD = re.compile(r"premiere|promotional cards?", re.IGNORECASE)
_SNEAK_PEEK = re.compile(r"sneak peek", re.IGNORECASE)
_SPECIAL_EDITION = re.compile(r":\s*special edition\s*$", re.IGNORECASE)
_SPEED_DUEL = re.compile(r"\bspeed duel\b", re.IGNORECASE)


def load_mapping(path: Path = MAPPING) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def norm(name: str) -> str:
    """Case-folded name with apostrophes unified and spaces collapsed, for comparing set names."""
    return " ".join(name.replace("’", "'").casefold().split())


def _titles(set_name: str) -> list[str]:
    """The page titles to try for a set, in order."""
    titles = [set_name]
    if set_name.startswith("Yu-Gi-Oh! "):
        titles.append(set_name[len("Yu-Gi-Oh! "):])
    return titles


def map_type(ib: dict[str, str], name: str, mapping: dict) -> str | None:
    """Our type for an infobox, or None when its type is not in the mapping."""
    raw_type = norm(ib.get("type", ""))
    kind = mapping["types"].get(raw_type)
    if kind is None:
        return None
    series = norm(ib.get("series", ""))
    if series:
        exact = {norm(k): v for k, v in mapping["series"].items() if not k.endswith("*")}
        prefixes = sorted(((norm(k[:-1]), v) for k, v in mapping["series"].items() if k.endswith("*")),
                          key=lambda kv: -len(kv[0]))
        if series in exact:
            kind = exact[series]
        else:
            kind = next((v for p, v in prefixes if series.startswith(p)), kind)
    if "participation card" in raw_type and _SNEAK_PEEK.search(name):
        kind = "sneak_peek"
    if _SPECIAL_EDITION.search(name):
        kind = "special_edition"
    # Speed Duel is its own product line and format; Yugipedia files its boosters and boxes as plain ones.
    if _SPEED_DUEL.search(name):
        kind = "speed_duel"
    return kind


def database_ids(ib: dict[str, str]) -> list[int]:
    """Every *database_id value as an int, blanks and non-numbers skipped; a "a; b" list gives both."""
    found = set()
    for key, value in ib.items():
        if _DATABASE_ID.search(key):
            found.update(int(part) for part in (p.strip() for p in value.split(";")) if part.isdigit())
    return sorted(found)


def release_date(ib: dict[str, str]) -> str | None:
    """na, else en, else the undecorated release_date, else the earliest of the other *_release_date values."""
    for key in _PREFERRED_DATES:
        if date := yugipedia.parse_date(ib.get(key)):
            return date
    others = [yugipedia.parse_date(v) for k, v in ib.items() if _RELEASE_DATE.search(k) and k not in _PREFERRED_DATES]
    return min((d for d in others if d), default=None)


def prefix_code(ib: dict[str, str]) -> str | None:
    """The part before the hyphen of the infobox's prefix, else en_prefix (LOB-EN -> LOB)."""
    for key in ("prefix", "en_prefix"):
        first = ib.get(key, "").split(";")[0].strip()
        if first and first.split("-")[0].strip():
            return first.split("-")[0].strip()
    return None


def key_art(ib: dict[str, str], title: str) -> dict | None:
    image = ib.get("image", "").split(";")[0].strip()
    if not image:
        return None
    return {"url": yugipedia.file_url(image), "source": yugipedia.page_url(title)}


def apply_infobox(s: dict, ib: dict[str, str], page: dict, write_id: bool, mapping: dict, eras: list[dict],
                  stats: collections.Counter, review_unmapped: list[dict]) -> None:
    """Fold one infobox into set s, touching only the fields the module docstring lists."""
    kind = map_type(ib, s["name"], mapping)
    if kind is None:
        review_unmapped.append({"id": s["id"], "name": s["name"], "type": ib.get("type", ""),
                                "series": ib.get("series", "")})
    else:
        s["type"] = kind
    if ib.get("series"):
        s["series"] = ib["series"]
    ids = dict(s.get("identifiers", {}))
    if write_id:
        ids["yugipediaId"] = page["pageid"]
    db_ids = sorted({*ids.get("konamiDatabaseIds", []), *database_ids(ib)})
    if db_ids:
        ids["konamiDatabaseIds"] = db_ids
    if ids:
        s["identifiers"] = ids
    if s["code"] == "UNKNOWN" and (code := prefix_code(ib)):
        s["code"] = code
        stats["codes"] += 1
    release = s["releases"][0]
    if not release.get("releaseDate") and (date := release_date(ib)):
        release["releaseDate"] = date
        stats["dates"] += 1
    if not release.get("keyArt") and (art := key_art(ib, page["title"])):
        release["keyArt"] = art
        stats["keyArt"] += 1
    if "era" not in s and release.get("releaseDate") and (era := import_ygoprodeck.era_of(release["releaseDate"], eras)):
        s["era"] = era


def _child_eligible(s: dict) -> bool:
    return s["type"] in ("sneak_peek", "special_edition") or (s["type"] == "promo" and bool(_PROMO_CHILD.search(s["name"])))


def find_parents(sets: list[dict], raw_boxes: dict[str, dict[str, str]]) -> tuple[dict, dict]:
    """({child id: (booster id, evidence)}, {child id: [booster ids]}) for the children without a parent.

    Evidence is code, name or other_sets, joined with + when several name the same booster. raw_boxes is
    {set id: infobox_raw} for the sets that have a page."""
    boosters = [s for s in sets if s["type"] == "booster"]
    by_name = collections.defaultdict(list)
    for b in boosters:
        by_name[norm(b["name"])].append(b)
        if b["name"].startswith("Yu-Gi-Oh! "):
            by_name[norm(b["name"][len("Yu-Gi-Oh! "):])].append(b)
    # booster id -> the names its other_sets points at, whole or by item.
    listed = {}
    for b in boosters:
        raw = raw_boxes.get(b["id"], {}).get("other_sets", "")
        listed[b["id"]] = {norm(n) for n in yugipedia.named_in(raw)} | {norm(i) for i in yugipedia.clean(raw).split(";")}
    found, ambiguous = {}, {}
    for s in sorted(sets, key=lambda s: s["id"]):
        if "parent" in s or not _child_eligible(s):
            continue
        evidence = collections.defaultdict(set)
        for b in boosters:
            if b["id"] != s["id"] and s["code"] != "UNKNOWN" and b["code"] == s["code"]:
                evidence[b["id"]].add("code")
        child = norm(s["name"])
        starts = [b for b in boosters if b["id"] != s["id"] and re.match(re.escape(norm(b["name"])) + r"(?![a-z0-9])", child)]
        # A booster whose name starts another matched booster's name is the shorter, vaguer match: keep the longest.
        starts = [b for b in starts if not any(o is not b and norm(o["name"]).startswith(norm(b["name"])) for o in starts)]
        for b in starts:
            evidence[b["id"]].add("name")
        for name in yugipedia.named_in(raw_boxes.get(s["id"], {}).get("other_sets", "")):
            for b in by_name.get(norm(name), []):
                if b["id"] != s["id"]:
                    evidence[b["id"]].add("other_sets")
        for b in boosters:
            if b["id"] != s["id"] and child in listed[b["id"]]:
                evidence[b["id"]].add("other_sets")
        if len(evidence) == 1:
            (bid, kinds), = evidence.items()
            found[s["id"]] = (bid, "+".join(k for k in ("code", "name", "other_sets") if k in kinds))
        elif evidence:
            ambiguous[s["id"]] = sorted(evidence)
    return found, ambiguous


def inherit_eras(sets: list[dict]) -> int:
    """A set with no era takes its parent's (parents first, so a chain resolves). Returns how many got one."""
    by_id = {s["id"]: s for s in sets}
    count = 0
    changed = True
    while changed:
        changed = False
        for s in sets:
            parent = by_id.get(s.get("parent"))
            if "era" not in s and parent and "era" in parent:
                s["era"] = parent["era"]
                count += 1
                changed = True
    return count


def resolve_pages(sets: list[dict], cache: Path = yugipedia.DEFAULT_CACHE) -> tuple[dict, collections.Counter]:
    """{set id: (page, found_by_title)} for the sets whose page exists, and how many were found each way."""
    pages: dict[str, tuple[dict, bool]] = {}
    how = collections.Counter()
    ours = [s for s in sets if s["source"] == SOURCE]
    by_id = yugipedia.pages_by_id([s["identifiers"]["yugipediaId"] for s in ours
                                   if "yugipediaId" in s.get("identifiers", {})], cache)
    for s in ours:
        page = by_id.get(s.get("identifiers", {}).get("yugipediaId"))
        if page:
            pages[s["id"]] = (page, False)
            how["id"] += 1
            continue
        for title in _titles(s["name"]):
            if page := yugipedia.page_by_title(title, cache):
                pages[s["id"]] = (page, True)
                how["title"] += 1
                break
        else:
            how["missing"] += 1
    return pages, how


def build(sets: list[dict], pages: dict, eras: list[dict], mapping: dict) -> tuple[dict, collections.Counter, dict]:
    """Apply the pages to the sets in place. Returns the review body, the counters and the parent evidence counts."""
    stats = collections.Counter()
    no_page, no_infobox, unmapped, shared = [], [], [], []
    raw_boxes = {}
    # A page belongs to one set: the one that already holds its id, else the first set (by id) that found it by
    # title. A title that redirects to a page another set owns (Magic Ruler -> Spell Ruler) still gives its infobox
    # but not the id, so identifiers.yugipediaId stays unique.
    owner = {p["pageid"]: sid for sid, (p, by_title) in pages.items() if not by_title}
    for sid, (p, by_title) in sorted(pages.items()):
        if by_title:
            owner.setdefault(p["pageid"], sid)
    for s in sorted(sets, key=lambda s: s["id"]):
        if s["source"] != SOURCE:
            continue
        found = pages.get(s["id"])
        if found is None:
            no_page.append({"id": s["id"], "name": s["name"]})
            continue
        page, by_title = found
        write_id = by_title and owner[page["pageid"]] == s["id"]
        if by_title and not write_id:
            shared.append({"id": s["id"], "name": s["name"], "page": page["title"], "pageid": page["pageid"],
                           "ownedBy": owner[page["pageid"]]})
        raw = yugipedia.infobox_raw(yugipedia.wikitext(page))
        if raw is None:
            no_infobox.append({"id": s["id"], "name": s["name"]})
            continue
        ib = {k: yugipedia.clean(v) for k, v in raw.items()}
        raw_boxes[s["id"]] = raw
        apply_infobox(s, ib, page, write_id, mapping, eras, stats, unmapped)
    found_parents, ambiguous = find_parents(sets, raw_boxes)
    by_id = {s["id"]: s for s in sets}
    evidence = collections.Counter()
    for child, (parent, kinds) in found_parents.items():
        by_id[child]["parent"] = parent
        evidence[kinds] += 1
    stats["parents"] = len(found_parents)
    stats["erasInherited"] = inherit_eras(sets)
    review = {
        "noPage": no_page,
        "noInfobox": no_infobox,
        "unmappedType": unmapped,
        "sharedPage": shared,
        "parentCandidates": [{"id": c, "name": by_id[c]["name"], "candidates": ids} for c, ids in sorted(ambiguous.items())],
    }
    return review, stats, evidence


def main() -> None:
    sets = ygjson.load_sets()
    mapping = load_mapping()
    pages, how = resolve_pages(sets)
    review, stats, evidence = build(sets, pages, ygjson.load_eras(), mapping)
    ygjson.save_json(ygjson.SETS, sets)
    ygjson.save_json(REVIEW, review)
    types = collections.Counter(s["type"] for s in sets)
    print(f"pages: {how['id']} by id, {how['title']} by title, {how['missing']} missing "
          f"({len(review['noInfobox'])} without an infobox)")
    print("types: " + ", ".join(f"{k} {v}" for k, v in sorted(types.items(), key=lambda kv: (-kv[1], kv[0]))))
    print(f"parents set: {stats['parents']} (" + ", ".join(f"{k} {v}" for k, v in sorted(evidence.items())) +
          f"), {len(review['parentCandidates'])} ambiguous, {sum('parent' in s for s in sets)} sets have one")
    print(f"dates filled: {stats['dates']}, key art filled: {stats['keyArt']}, codes filled: {stats['codes']}, "
          f"eras inherited: {stats['erasInherited']}, unmapped types: {len(review['unmappedType'])}")


if __name__ == "__main__":
    main()
