"""Tie TCGplayer's Yu-Gi-Oh! groups and products (TCGCSV category 2) to our sets and prints, and write review/tcgplayer-2.json.

    uv run python tools/import_tcgcsv.py [--refresh]

Reads sets/sets.json and data/cards/*.json (written by import_ygoprodeck and refined by import_ygojson and
import_yugipedia), .cache/tcgcsv, and mappings/tcgplayer_groups.json ({groupId: {"set": id, "why": evidence}}), and
rewrites the first two in place, adding only:

  sets    tcgplayerGroupIds (union), editions (union with the price subtypes of the set's singles: 1st Edition is first,
          Unlimited unlimited, Limited limited), and one new set for each "(2020 Date Reprint)" or "(2020 Reprint)"
          group (id "<parent id>-2020-reprint", source tcgplayer, the parent's code, type, era and editions).
  prints  identifiers.tcgplayerProductIds, tcgplayer {name, match}, editions (when a print's own products are priced
          in fewer editions than its set), and the prints of a reprint set (copies of the parent's prints that the
          group's singles name). A print whose YGOPRODeck rarity was unknown takes TCGplayer's.

A group is matched to a set by five rules, each over the groups and sets still free: exact name; normalised name;
normalised name after dropping " (Worldwide English)"; the hand-kept mapping; the abbreviation before its hyphen
equal to the code of one set of a compatible type (an "-SE" or "-ENSE" abbreviation only matches a special edition,
and nothing else does). Groups that match no set go to review `groups`.

A single is tied to a print in three passes, so a fuzzy match never takes a print an exact one wants:
  1. (Number, canonical Rarity) in the group's set                     -> number+rarity
  2. the group's set has the number, and either exactly one print of that number has an unknown rarity (it takes
     TCGplayer's rarity and a new id)                                  -> number+rarity-from-tcgplayer
     or exactly one print has that number at all                       -> number
  3. no set, or the number is not in the group's set: the number is in exactly one other set (the set is named
     differently on TCGplayer), tried with the same rules there        -> number-other-set
  4. no print anywhere has the number: the product's name is exactly one card, and its rarity is known. The print is
     minted (source tcgplayer), in the group's set, or in a set minted for a group that matched none -> minted
Whatever remains goes to review `unmatched` with the reason. A product lands on one print only. A print holds
several products only when they are the same card at the same rarity; a product that would share a print with another
card, or another rarity, goes to review `conflicts`.

A product whose name carries a variant tag (variant_of) has a price of its own: Zaborg the Thunder Monarch is 129.99
in Blue and 4.49 in Green under one number and rarity. It lands on its own print, a copy of the base print with
`variant` set, and the base print keeps only the unmarked product, if there is one.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

import rarities
import tcgcsv
import ygjson
from import_ygojson import normalise
from import_ygoprodeck import era_of, set_type

CACHE = ygjson.ROOT / ".cache" / "tcgcsv"
REVIEW = ygjson.ROOT / "review" / "tcgplayer-2.json"
MAPPING = ygjson.ROOT / "mappings" / "tcgplayer_groups.json"
SOURCE = "tcgplayer"

# A group named "<base> (<suffix>)" is a later printing of the set called <base>.
CHILD = re.compile(r"^(?P<base>.*?)\s*\((?P<suffix>2020 Date Reprint|2020 Reprint|25th Anniversary Edition)\)$")
SUFFIX_SLUGS = {"2020 Date Reprint": "2020-reprint", "2020 Reprint": "2020-reprint",
                "25th Anniversary Edition": "25th-anniversary-edition"}
WORLDWIDE = " (Worldwide English)"
SUBTYPES = {"1st Edition": "first", "Unlimited": "unlimited", "Limited": "limited"}
EDITION_ORDER = ("first", "unlimited", "limited")
RULES = ("exact_name", "normalised_name", "worldwide_english", "mapping", "abbreviation", "reprint", "minted")
MINTED = "minted"
_SKILL_CARD = " (Skill Card)"

# The tags that name a separately priced version of one print: a foil colour, an art letter, a numbered art. Rarity and
# treatment tags are not here: a rarity is already part of the print, and the stamps and alternate arts stay on it.
_VARIANT_TAG = re.compile(r"^(Blue|Green|Purple|Red|Silver|Bronze|[A-G]|Version \d+)$")
# A treatment on top of a variant is a further version the catalogue has no print for.
_TREATMENT_TAG = re.compile(r"stamp|alternate art|extended art|new art|misprint|emblazoned|oversized|japanese artwork", re.I)
_TOKEN_PREFIX = "Token: "


def unplaceable_tags(prod: tcgcsv.Product) -> bool:
    """True when the tags name versions no one print can hold: two variants, or a variant with a treatment."""
    tags = prod.base_name_and_tags()[1]
    variants = [t for t in tags if _VARIANT_TAG.match(t)]
    return len(variants) > 1 or (len(variants) == 1 and any(_TREATMENT_TAG.search(t) for t in tags))


def has_rarity_tag(prod: tcgcsv.Product) -> bool:
    """True when the name itself says which rarity this is, beyond the Rarity field: "(PCR)", "(Secret Rare)"."""
    return any(not _VARIANT_TAG.match(t) and not _TREATMENT_TAG.search(t) for t in prod.base_name_and_tags()[1])


def variant_of(prod: tcgcsv.Product) -> str | None:
    """The variant slug in a product's name tags, or None when it has none or more than one."""
    found = [t for t in prod.base_name_and_tags()[1] if _VARIANT_TAG.match(t)]
    return ygjson.slugify(found[0]) if len(found) == 1 else None


def split_child(name: str) -> tuple[str, str] | None:
    """(base name, suffix) of a "<base> (2020 Date Reprint)" style group name, else None."""
    m = CHILD.match(name)
    return (m["base"], m["suffix"]) if m else None


def _is_se(abbreviation: str) -> bool:
    """A special-edition abbreviation: the part after the hyphen ends in SE (MVP1-SE, CBLZ-ENSE)."""
    parts = abbreviation.split("-")
    return len(parts) > 1 and parts[1].endswith("SE")


def _code(abbreviation: str) -> str:
    return abbreviation.split("-")[0].upper()


def match_groups(groups: list[dict], sets: list[dict], mapping: dict) -> dict:
    """{"matches": {groupId: (set id, rule)}, "reprints": {groupId: [parent set ids]}, "children": {groupId: [parent
    set ids]}, "unmatched": [group]}.

    Only sets that came from YGOPRODeck are candidates. A group named "<base> (<suffix>)" (see CHILD) hangs off the
    set called <base>. When no set has the group's exact name it is a "reprint" and the Importer mints its set;
    when one has, the group matches that set by name as any other and is listed under "children" instead, so its
    prints can still be copied from the parent. The possible parents are the set matched to the group of the base
    name, the set of that name, and the sets with the group's code, in that order (the Importer keeps the one that
    holds most of the group's numbers)."""
    ordered = sorted(groups, key=lambda g: g["groupId"])
    ours = sorted((s for s in sets if s["source"] != SOURCE), key=lambda s: s["id"])
    matches: dict[int, tuple[str, str]] = {}
    claimed: set[str] = set()
    names = {s["name"] for s in ours}
    child_of = {g["groupId"]: split_child(g["name"]) for g in ordered if split_child(g["name"])}
    reprint_ids = {gid for gid in child_of if next(g["name"] for g in ordered if g["groupId"] == gid) not in names}

    def free_groups():
        return [g for g in ordered if g["groupId"] not in matches and g["groupId"] not in reprint_ids]

    def free_sets():
        return [s for s in ours if s["id"] not in claimed]

    def take(g, set_id, rule):
        matches[g["groupId"]] = (set_id, rule)
        claimed.add(set_id)

    def unique_pairs(group_key, set_key, rule, any_set=False):
        """Match the free groups and sets whose key is shared by exactly one of each. With any_set a set that
        another group already took stays a candidate."""
        gs, ss = collections.defaultdict(list), collections.defaultdict(list)
        for g in free_groups():
            key = group_key(g)
            if key is not None:
                gs[key].append(g)
        for s in (ours if any_set else free_sets()):
            ss[set_key(s)].append(s)
        for key, found in gs.items():
            if len(found) == 1 and len(ss.get(key, [])) == 1:
                take(found[0], ss[key][0]["id"], rule)

    unique_pairs(lambda g: g["name"], lambda s: s["name"], "exact_name")
    unique_pairs(lambda g: normalise(g["name"]), lambda s: normalise(s["name"]), "normalised_name")
    unique_pairs(lambda g: normalise(g["name"].removesuffix(WORLDWIDE)) if g["name"].endswith(WORLDWIDE) else None,
                 lambda s: normalise(s["name"]), "worldwide_english", any_set=True)
    known = {s["id"] for s in ours}
    for g in free_groups():
        entry = mapping.get(str(g["groupId"]))
        if entry and entry["set"] in known:
            take(g, entry["set"], "mapping")
    unique_pairs(lambda g: (_code(g["abbreviation"]), _is_se(g["abbreviation"])) if g["abbreviation"] else None,
                 lambda s: (s["code"].upper(), s["type"] == "special_edition"), "abbreviation")

    by_group_name = {g["name"]: matches[g["groupId"]][0] for g in ordered if g["groupId"] in matches}
    by_name = {s["name"]: s["id"] for s in ours}
    by_code = collections.defaultdict(list)
    for s in ours:
        by_code[s["code"].upper()].append(s["id"])
    parents: dict[int, list[str]] = {}
    for g in ordered:
        if g["groupId"] not in child_of or (g["groupId"] not in reprint_ids and g["groupId"] not in matches):
            continue
        base = child_of[g["groupId"]][0]
        own = matches.get(g["groupId"], (None,))[0]
        candidates = [by_group_name.get(base), by_name.get(base), *by_code.get(_code(g["abbreviation"] or ""), [])]
        candidates = list(dict.fromkeys(c for c in candidates if c and c != own))
        if candidates:
            parents[g["groupId"]] = candidates
    reprints = {gid: c for gid, c in parents.items() if gid in reprint_ids}
    children = {gid: c for gid, c in parents.items() if gid not in reprint_ids}
    done = set(matches) | set(reprints)
    return {"matches": matches, "reprints": reprints, "children": children,
            "unmatched": [g for g in ordered if g["groupId"] not in done]}


def mint_reprint_set(group: dict, parent: dict, taken: set[str], old: dict | None) -> dict:
    """The set for a reprint or anniversary group, carrying the parent's code, type, era and editions. An existing
    one (an earlier run) keeps its identifiers."""
    base, suffix = split_child(group["name"])
    set_id = old["id"] if old else _free_id(f"{parent['id']}-{SUFFIX_SLUGS[suffix]}", taken)
    name = group["name"] if suffix.startswith("25th") else f"{base} (2020 Date Reprint)"
    release: dict = {"language": "en", "name": name}
    if group.get("publishedOn"):
        release["releaseDate"] = group["publishedOn"][:10]
    s = {"id": set_id, "code": parent["code"], "name": name, "type": parent["type"],
         "editions": list(parent["editions"]), "parent": parent["id"], "source": SOURCE,
         "tcgplayerGroupIds": [group["groupId"]], "releases": [release]}
    if "era" in parent:
        s["era"] = parent["era"]
    if old and "identifiers" in old:
        s["identifiers"] = old["identifiers"]
    return s


def _free_id(base: str, taken: set[str]) -> str:
    set_id, n = base, 1
    while set_id in taken:
        n += 1
        set_id = f"{base}-{n}"
    return set_id


class Catalog:
    """The cards in memory, indexed by (set, number) and by number, over the prints that have a number."""

    def __init__(self, files: dict[str, dict]):
        self.files = files
        self.by_set_number: dict[tuple[str, str], list[tuple[dict, dict]]] = collections.defaultdict(list)
        self.by_number: dict[str, set[str]] = collections.defaultdict(set)
        self.by_name: dict[str, list[dict]] = collections.defaultdict(list)
        self.by_alias: dict[str, list[dict]] = collections.defaultdict(list)
        self.by_id: dict[str, dict] = {}
        self.touched: set[str] = set()
        for body in files.values():
            for card in body["cards"]:
                self.by_name[normalise(card["name"].removesuffix(_SKILL_CARD))].append(card)
                for p in card["prints"]:
                    self.add(card, p)
        # An alias is a weaker claim than a name, so a product is read as an alias only when no card has that name.
        for body in files.values():
            for card in body["cards"]:
                for alias in card.get("aliases", []):
                    if normalise(alias) not in self.by_name:
                        self.by_alias[normalise(alias)].append(card)

    def add(self, card: dict, p: dict) -> None:
        self.by_id[p["id"]] = p
        # A variant is reached through its base print, so a number lookup never sees it as a second candidate.
        if p.get("number") and not p.get("variant"):
            self.by_set_number[(p["set"], p["number"])].append((card, p))
            self.by_number[p["number"]].add(p["set"])

    def find(self, set_id: str, number: str) -> list[tuple[dict, dict]]:
        return self.by_set_number.get((set_id, number), [])

    def card_named(self, base_name: str) -> dict | None:
        """The one card with this name. "Token: Sheep" reads as a token card, "Sheep Token" or "Sheep", and never as
        the monster or spell a token shows: "Token: Grinder Golem" is not the card Grinder Golem."""
        is_token = base_name.startswith(_TOKEN_PREFIX)
        short = base_name.removeprefix(_TOKEN_PREFIX)
        for name in ([f"{short} Token", short] if is_token else [base_name]):
            found = self.by_name.get(normalise(name)) or self.by_alias.get(normalise(name), [])
            if is_token:
                found = [c for c in found if c.get("kind") == "token"]
            if found:
                return found[0] if len(found) == 1 else None
        return None

    def attach(self, card: dict, fields: dict) -> dict:
        """The print with this id on the card, adding it if it is new."""
        found = self.by_id.get(fields["id"])
        if found is not None:
            return found
        card["prints"].append(fields)
        self.add(card, fields)
        return fields

    def sort_prints(self) -> None:
        for body in self.files.values():
            for card in body["cards"]:
                card["prints"].sort(key=lambda p: p["id"])


def _product_ids(p: dict) -> list[int]:
    return p.get("identifiers", {}).get("tcgplayerProductIds", [])


def _remove_minted(sets: list[dict], files: dict[str, dict]) -> None:
    """Drop what an earlier run minted, so each run decides again and a rule fixed today leaves nothing behind. A product
    on a removed print goes back through the rules. Reprint sets (they have a parent) are not minted this way."""
    for body in files.values():
        for card in body["cards"]:
            card["prints"] = [p for p in card["prints"] if p.get("source") != SOURCE]


def _drop_empty_minted_prints(files: dict[str, dict]) -> None:
    """A minted print exists to hold a product. One whose product was refused, or moved to a variant, is dropped, or a shop
    listing could price a print no source vouches for."""
    for body in files.values():
        for card in body["cards"]:
            card["prints"] = [p for p in card["prints"] if p.get("source") != SOURCE or _product_ids(p)]


def _drop_empty_minted_sets(sets: list[dict], files: dict[str, dict]) -> list[dict]:
    used = {p["set"] for body in files.values() for card in body["cards"] for p in card["prints"]}
    return [s for s in sets if s["source"] != SOURCE or "parent" in s or s["id"] in used]


def _edition_list(editions) -> list[str]:
    return [e for e in EDITION_ORDER if e in editions]


class Importer:
    def __init__(self, sets, files, groups, products, prices, mapping, eras=None):
        self.sets = {s["id"]: s for s in sets}
        self.groups = {g["groupId"]: g for g in groups}
        self.products = products  # {groupId: [Product]}
        self.by_id = {p.product_id: p for ps in products.values() for p in ps}
        self.subtypes: dict[int, set[str]] = collections.defaultdict(set)
        for rows in prices.values():
            for row in rows:
                if row["subTypeName"] in SUBTYPES:
                    self.subtypes[row["productId"]].add(SUBTYPES[row["subTypeName"]])
        self.catalog = Catalog(files)
        self.stats = collections.Counter()
        self.group_rules = collections.Counter()
        self.unmatched: list[dict] = []
        self.conflicts: list[dict] = []
        self.aliases: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
        self.landed_in: dict[str, set[int]] = collections.defaultdict(set)  # set id -> product ids
        self.owner: dict[int, dict] = {}  # product id -> the print that holds it
        for body in files.values():
            for card in body["cards"]:
                for p in card["prints"]:
                    for pid in _product_ids(p):
                        self.owner[pid] = p
        self.mapping = mapping
        self.set_of_group: dict[int, str] = {}
        self.rekeyed = 0
        self.minted = 0
        self.sold_as: dict[str, set[str]] = collections.defaultdict(set)  # card id -> TCGplayer's base names for it
        self.minted_prints = 0
        self.minted_variants = 0
        self.eras = eras or []

    # --- groups -----------------------------------------------------------------------------------------------

    def match_groups(self) -> list[dict]:
        found = match_groups(list(self.groups.values()), list(self.sets.values()), self.mapping)
        for gid, (set_id, rule) in found["matches"].items():
            self.set_of_group[gid] = set_id
            self.group_rules[rule] += 1
        # A set an earlier run minted for a group is that group's set; the name rules never consider it.
        for s in self.sets.values():
            if s["source"] == SOURCE and s["id"] not in self.set_of_group.values():
                for gid in s.get("tcgplayerGroupIds", []):
                    if gid in self.groups and gid not in found["reprints"]:
                        self.set_of_group.setdefault(gid, s["id"])
                        s["editions"] = self._group_editions(gid, s["type"])
        taken = set(self.sets)
        for gid, candidates in found["reprints"].items():
            parent_id = self.best_parent(gid, candidates)
            parent = self.sets[parent_id]
            old = next((s for s in self.sets.values() if gid in s.get("tcgplayerGroupIds", []) and s["source"] == SOURCE),
                       None)
            minted = mint_reprint_set(self.groups[gid], parent, taken, old)
            taken.add(minted["id"])
            self.sets[minted["id"]] = minted
            self.set_of_group[gid] = minted["id"]
            self.group_rules["reprint"] += 1
            self.mint_prints(gid, parent_id, minted["id"])
        for gid, candidates in found["children"].items():
            self.mint_prints(gid, self.best_parent(gid, candidates), self.set_of_group[gid])
        for gid, set_id in self.set_of_group.items():
            s = self.sets[set_id]
            s["tcgplayerGroupIds"] = sorted(set(s.get("tcgplayerGroupIds", [])) | {gid})
        return found["unmatched"]

    def best_parent(self, gid: int, candidates: list[str]) -> str:
        """The candidate set that holds the most of the group's numbers; the first on a tie."""
        numbers = {p.number for p in self.products.get(gid, []) if p.is_single and p.number}
        return max(candidates, key=lambda c: sum(bool(self.catalog.find(c, n)) for n in numbers))

    def mint_prints(self, gid: int, parent_id: str, target_id: str) -> None:
        """Copy into the target set the parent prints the group's singles name. A single names a print by its number
        and rarity; when the parent has the number only at other rarities and just one card holds it, the print is
        minted at TCGplayer's rarity (an anniversary edition reprints a card in a new rarity). A rarity TCGplayer
        spells in a way we cannot read, or a number whose print here is still of unknown rarity, is left to the
        singles rules."""
        singles = sorted((p for p in self.products.get(gid, []) if p.is_single and p.number), key=lambda p: p.product_id)
        for prod in singles:
            rarity = rarities.canonical(prod.rarity)
            parents = self.catalog.find(parent_id, prod.number)
            if rarity == rarities.UNKNOWN or not parents:
                continue
            exact = [(c, p) for c, p in parents if p["rarity"] == rarity]
            if exact:
                hit = self._pick(exact, prod)
            else:
                hit = parents[0] if len({c["id"] for c, _ in parents}) == 1 else None
            if hit is None:
                continue
            card, p = hit
            pid = ygjson.print_id(target_id, card["id"], p["number"], rarity)
            if any(q["id"] == pid or (q["set"] == target_id and q.get("number") == p["number"]
                                      and q["rarity"] == rarities.UNKNOWN) for q in card["prints"]):
                continue
            copy = {k: v for k, v in p.items() if k in ("number", "region")} | {"id": pid, "set": target_id, "rarity": rarity}
            card["prints"].append(copy)
            self.catalog.add(card, copy)
            self.minted += 1

    # --- singles ----------------------------------------------------------------------------------------------

    def _pick(self, found: list[tuple[dict, dict]], prod: tcgcsv.Product) -> tuple[dict, dict] | None:
        """The one print among `found`, using the product's name to tell two cards apart; None when still two."""
        if len(found) == 1:
            return found[0]
        base = normalise(prod.base_name_and_tags()[0])
        named = [c for c in found if normalise(c[0]["name"]) == base]
        return named[0] if len(named) == 1 else None

    def _exact(self, set_id: str, prod: tcgcsv.Product, rarity: str):
        """("hit", (card, print)) | ("ambiguous", n) | None."""
        found = [(c, p) for c, p in self.catalog.find(set_id, prod.number) if p["rarity"] == rarity]
        if not found:
            return None
        hit = self._pick(found, prod)
        return ("hit", hit) if hit else ("ambiguous", len(found))

    def _fallback(self, set_id: str, prod: tcgcsv.Product, rarity: str):
        """Rules 2 and 3 in `set_id`: ("rekey" | "number", (card, print)) | ("ambiguous", n) | None."""
        here = self.catalog.find(set_id, prod.number)
        if not here:
            return None
        if rarity != rarities.UNKNOWN:
            unknown = [(c, p) for c, p in here if p["rarity"] == rarities.UNKNOWN]
            if unknown:
                hit = self._pick(unknown, prod)
                return ("rekey", hit) if hit else ("ambiguous", len(unknown))
        hit = self._pick(here, prod) if len(here) == 1 else None
        return ("number", hit) if hit else ("ambiguous", len(here))

    def _rekey(self, card: dict, p: dict, set_id: str, rarity: str) -> bool:
        new_id = ygjson.print_id(set_id, card["id"], p.get("number"), rarity)
        if any(q["id"] == new_id for q in card["prints"]):
            return False
        p["id"], p["rarity"] = new_id, rarity
        p.pop("rawRarity", None)
        self.rekeyed += 1
        return True

    def _review(self, prod: tcgcsv.Product, reason: str) -> None:
        self.unmatched.append({"productId": prod.product_id, "name": prod.name, "groupId": prod.group_id,
                               "number": prod.number, "rarity": prod.rarity, "reason": reason})

    def _land(self, card: dict, p: dict, prod: tcgcsv.Product, match: str) -> bool:
        """Put the product on the print, or on the print's variant when the product names one. False (and a review
        entry) when the print holds another card or rarity. A variant print is created only after those checks, so a
        refused product leaves no empty print behind."""
        if unplaceable_tags(prod):
            self._review(prod, "its tags name two versions, and no print can hold both")
            return False
        # A base print and its variants are one card at one rarity, so a stranger is refused whichever of them it hits.
        family = [q for q in card["prints"]
                  if (q["set"], q.get("number"), q["rarity"]) == (p["set"], p.get("number"), p["rarity"])]
        held = sorted(i for q in family for i in _product_ids(q) if i != prod.product_id and i in self.by_id)
        mine = (normalise(prod.base_name_and_tags()[0]), rarities.canonical(prod.rarity))
        for i in held:
            other = self.by_id[i]
            theirs = (normalise(other.base_name_and_tags()[0]), rarities.canonical(other.rarity))
            sibling_id = ygjson.print_id(p["set"], card["id"], p.get("number"), mine[1])
            if theirs != mine and theirs[0] == mine[0] and mine[1] != rarities.UNKNOWN and sibling_id != p["id"] \
                    and has_rarity_tag(prod):
                # The same card at another rarity under one number, as its name says: "Number 107 (PCR)" in RA04. A
                # rarity only the Rarity field states stays a conflict, because a mislabel would become a real print.
                sibling = {k: p[k] for k in ("number", "region", "set") if k in p}
                fields = {"id": sibling_id, **sibling, "rarity": mine[1], "source": SOURCE}
                return self._land(card, self.catalog.attach(card, fields), prod, MINTED)
            if theirs != mine:
                self.conflicts.append({"productId": prod.product_id, "name": prod.name, "groupId": prod.group_id,
                                       "print": p["id"], "heldBy": held,
                                       "reason": "the print holds a product of another name or rarity"})
                return False
        variant = variant_of(prod)
        if variant and not p.get("variant"):
            p = self._variant_print(card, p, variant)
        previous = self.owner.get(prod.product_id)
        if previous is not None and previous is not p:
            remaining = previous["identifiers"]["tcgplayerProductIds"]
            remaining.remove(prod.product_id)
            if not remaining:
                del previous["identifiers"], previous["tcgplayer"]
            elif previous["tcgplayer"]["name"] == prod.name and remaining[0] in self.by_id:
                previous["tcgplayer"]["name"] = self.by_id[remaining[0]].name
        ids = p.setdefault("identifiers", {}).setdefault("tcgplayerProductIds", [])
        if prod.product_id not in ids:
            ids.append(prod.product_id)
            ids.sort()
        if p.get("source") == SOURCE and not p.get("variant"):
            match = MINTED
        kept = p.get("tcgplayer")
        if kept is None:
            p["tcgplayer"] = {"name": prod.name, "match": match}
        elif kept["match"] != MINTED and not (kept["match"] == "number+rarity-from-tcgplayer" and match == "number+rarity"):
            kept["match"] = match  # a re-keyed or minted print matches exactly on the next run, but keeps its label
        self.owner[prod.product_id] = p
        self.landed_in[p["set"]].add(prod.product_id)
        self.sold_as[card["id"]].add(prod.base_name_and_tags()[0])
        self.stats[p["tcgplayer"]["match"]] += 1
        return True

    def _variant_print(self, card: dict, base: dict, variant: str) -> dict:
        """The base print's copy for this variant, created on first sight."""
        pid = ygjson.print_id(base["set"], card["id"], base.get("number"), base["rarity"], variant)
        before = len(card["prints"])
        copy = {k: base[k] for k in ("number", "region", "set", "rarity") if k in base}
        found = self.catalog.attach(card, {"id": pid, **copy, "variant": variant, "source": SOURCE})
        self.minted_variants += len(card["prints"]) - before
        return found

    def _group_set(self, prod: tcgcsv.Product) -> str:
        """The set of the product's group, minting one for a group that matched none. A rerun finds its earlier set
        by the group id, because a minted set is never a candidate for the name rules."""
        gid = prod.group_id
        if gid in self.set_of_group:
            return self.set_of_group[gid]
        group = self.groups[gid]
        old = next((s for s in self.sets.values() if gid in s.get("tcgplayerGroupIds", []) and s["source"] == SOURCE), None)
        if old is None:
            released = (group.get("publishedOn") or "")[:10] or None
            release: dict = {"language": "en", "name": group["name"]}
            if released:
                release["releaseDate"] = released
            kind = set_type(group["name"])
            old = {"id": _free_id(ygjson.slugify(group["name"]), set(self.sets)),
                   "code": _code(group.get("abbreviation") or "") or prod.number.split("-")[0],
                   "name": group["name"], "type": kind, "editions": self._group_editions(gid, kind),
                   "source": SOURCE, "tcgplayerGroupIds": [gid], "releases": [release]}
            era = era_of(released, self.eras)
            if era:
                old["era"] = era
            self.sets[old["id"]] = old
            self.group_rules[MINTED] += 1
        self.set_of_group[gid] = old["id"]
        return old["id"]

    def _group_editions(self, gid: int, kind: str) -> list[str]:
        """The editions TCGplayer prices a group's singles in. With no prices they are a guess: a promo is limited."""
        singles = (p.product_id for p in self.products.get(gid, []) if p.is_single)
        priced = _edition_list(set().union(*(self.subtypes.get(i, set()) for i in singles)))
        return priced or (["limited"] if kind == "promo" else ["unlimited"])

    def _mint_print(self, prod: tcgcsv.Product) -> str | None:
        """Mint a print for a product whose number no print has. None on success, else why it was not minted."""
        rarity = rarities.canonical(prod.rarity)
        if rarity == rarities.UNKNOWN:
            return "no print has this number, and its rarity is unknown"
        if prod.number == "N/A":
            return "no print has this number, and TCGplayer's number is N/A"
        card = self.catalog.card_named(prod.base_name_and_tags()[0])
        if card is None:
            return "no print has this number, and its name is not one card"
        set_id = self._group_set(prod)
        fields = {"id": ygjson.print_id(set_id, card["id"], prod.number, rarity), "set": set_id, "number": prod.number,
                  "rarity": rarity, "source": SOURCE}
        region = ygjson.region_of(prod.number)
        if region:
            fields["region"] = region
        before = len(card["prints"])
        p = self.catalog.attach(card, fields)
        self.minted_prints += len(card["prints"]) - before
        return None if self._land(card, p, prod, MINTED) else "the minted print holds another product"

    def _apply(self, hit, kind: str, set_id: str, prod: tcgcsv.Product, rarity: str, label: str | None) -> bool:
        card, p = hit
        if kind == "rekey":
            if not self._rekey(card, p, set_id, rarity):
                self._review(prod, "re-keying the unknown-rarity print would duplicate an existing print")
                return False
            label = label or "number+rarity-from-tcgplayer"
        return self._land(card, p, prod, label or ("number" if kind == "number" else "number+rarity"))

    def match_singles(self) -> None:
        singles = sorted((p for ps in self.products.values() for p in ps if p.is_single), key=lambda p: p.product_id)
        pending: list[tcgcsv.Product] = []
        for prod in singles:
            set_id = self.set_of_group.get(prod.group_id)
            rarity = rarities.canonical(prod.rarity)
            if not prod.number:
                self._review(prod, "TCGplayer gives it no card number")
                continue
            res = self._exact(set_id, prod, rarity) if set_id and rarity != rarities.UNKNOWN else None
            if res is None:
                pending.append(prod)
            elif res[0] == "ambiguous":
                self._review(prod, f"ambiguous: {res[1]} prints of {prod.number} at {rarity}")
            else:
                self._apply(res[1], "exact", set_id, prod, rarity, "number+rarity")
        pending3: list[tcgcsv.Product] = []
        for prod in pending:
            set_id = self.set_of_group.get(prod.group_id)
            rarity = rarities.canonical(prod.rarity)
            res = self._fallback(set_id, prod, rarity) if set_id else None
            if res is None:
                pending3.append(prod)
            elif res[0] == "ambiguous":
                self._review(prod, f"ambiguous: {res[1]} prints of {prod.number} in the set, none at {rarity}")
            else:
                self._apply(res[1], res[0], set_id, prod, rarity, None)
        for prod in pending3:
            self._other_set(prod)

    def _other_set(self, prod: tcgcsv.Product) -> None:
        own = self.set_of_group.get(prod.group_id)
        others = sorted(self.catalog.by_number.get(prod.number, set()) - {own})
        # A reprint set holds copies of its parent's prints, so it does not make the number ambiguous.
        others = [s for s in others if self.sets[s]["source"] != SOURCE] or others
        if not others:
            reason = self._mint_print(prod)
            if reason:
                self._review(prod, reason)
            return
        if len(others) > 1:
            self._review(prod, f"the number is in {len(others)} other sets: {', '.join(others[:5])}")
            return
        target, rarity = others[0], rarities.canonical(prod.rarity)
        res = self._exact(target, prod, rarity) if rarity != rarities.UNKNOWN else None
        res = ("exact", res[1]) if res and res[0] == "hit" else res or self._fallback(target, prod, rarity)
        if res is None or res[0] == "ambiguous":
            self._review(prod, f"ambiguous in {target}" if res else f"no print of {target} has this number")
            return
        if self._apply(res[1], res[0], target, prod, rarity, "number-other-set"):
            self.aliases[prod.group_id][target] += 1

    # --- editions ---------------------------------------------------------------------------------------------

    def merge_aliases(self) -> int:
        """Add to each card the names TCGplayer sells it under. A name another card has is left out, or a listing for
        that card could price this one. Returns how many cards have aliases."""
        with_aliases = 0
        for body in self.catalog.files.values():
            for card in body["cards"]:
                own = normalise(card["name"])
                aliases = [*card.get("aliases", []), *sorted(self.sold_as.get(card["id"], ()))]
                # A name another card has, or a bare passcode, could price the wrong card.
                kept = sorted({a for a in aliases if normalise(a) != own and normalise(a) not in self.catalog.by_name
                               and not a.isdigit()})
                card.pop("aliases", None)
                if kept:
                    card["aliases"] = kept
                    with_aliases += 1
        return with_aliases

    def merge_editions(self) -> int:
        """Union each set's editions with the subtypes priced on the products that landed in it, then give a print
        its own editions when its products are priced in fewer. Returns the number of sets whose editions changed."""
        changed = 0
        for set_id, ids in self.landed_in.items():
            s = self.sets[set_id]
            seen = set().union(*(self.subtypes.get(i, set()) for i in ids))
            merged = _edition_list(set(s["editions"]) | seen)
            if merged != s["editions"]:
                s["editions"] = merged
                changed += 1
        for body in self.catalog.files.values():
            for card in body["cards"]:
                for p in card["prints"]:
                    own = set().union(*(self.subtypes.get(i, set()) for i in _product_ids(p)))
                    set_editions = set(self.sets[p["set"]]["editions"])
                    if own and own < set_editions:
                        p["editions"] = _edition_list(own)
        return changed


def run(groups, products, prices, sets, files, mapping, eras=None) -> dict:
    """Everything the tool does, on in-memory data: {"sets", "files", "review", "stats"}."""
    _remove_minted(sets, files)
    imp = Importer(sets, files, groups, products, prices, mapping, eras)
    unmatched_groups = imp.match_groups()
    imp.match_singles()
    _drop_empty_minted_prints(imp.catalog.files)
    editions_changed = imp.merge_editions()
    cards_with_aliases = imp.merge_aliases()
    imp.catalog.sort_prints()
    group_review = []
    for g in unmatched_groups:
        code = _code(g["abbreviation"] or "")
        group_review.append({"groupId": g["groupId"], "name": g["name"], "abbreviation": g["abbreviation"],
                             "candidates": sorted(s["id"] for s in imp.sets.values()
                                                  if code and s["code"].upper() == code)})
    aliases = [{"groupId": gid, "name": imp.groups[gid]["name"], "setsHit": dict(sorted(hits.items()))}
               for gid, hits in sorted(imp.aliases.items())]
    review = {"groups": group_review, "unmatched": sorted(imp.unmatched, key=lambda r: r["productId"]), "groupAliases": aliases,
              "conflicts": sorted(imp.conflicts, key=lambda r: r["productId"])}
    stats = {"matches": dict(sorted(imp.stats.items())), "groupRules": dict(imp.group_rules),
             "groupsUnmatched": len(unmatched_groups), "setsEditionsChanged": editions_changed,
             "rekeyed": imp.rekeyed, "minted": imp.minted, "mintedPrints": imp.minted_prints,
             "mintedVariants": imp.minted_variants, "cardsWithAliases": cards_with_aliases,
             **{k: len(v) for k, v in review.items()}}
    kept_sets = _drop_empty_minted_sets(list(imp.sets.values()), imp.catalog.files)
    return {"sets": sorted(kept_sets, key=lambda s: s["id"]), "files": imp.catalog.files, "review": review,
            "stats": stats}


def load_mapping(path: Path = MAPPING) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="download TCGCSV again (about 1,300 requests)")
    refresh = parser.parse_args().refresh
    groups = tcgcsv.groups(CACHE, refresh)
    products = {g["groupId"]: tcgcsv.products(g["groupId"], CACHE, refresh) for g in groups}
    prices = {g["groupId"]: tcgcsv.prices(g["groupId"], CACHE, refresh) for g in groups}
    out = run(groups, products, prices, ygjson.load_sets(), ygjson.load_cards(), load_mapping(), ygjson.load_eras())
    ygjson.save_json(ygjson.SETS, out["sets"])
    for bucket, body in out["files"].items():
        ygjson.save_json(ygjson.CARDS / f"{bucket}.json", body)
    ygjson.save_json(REVIEW, out["review"])
    s = out["stats"]
    print(f"{len(groups)} groups: " + ", ".join(f"{n} by {rule}" for rule, n in s["groupRules"].items())
          + f", {s['groupsUnmatched']} unmatched")
    singles = sum(1 for ps in products.values() for p in ps if p.is_single)
    print(f"{singles} singles: " + ", ".join(f"{n} {kind}" for kind, n in s["matches"].items()))
    print(f"{s['rekeyed']} prints re-keyed to TCGplayer's rarity, {s['setsEditionsChanged']} sets' editions changed, "
          f"{s['minted']} reprint prints, {s['mintedPrints']} prints and {s['mintedVariants']} variants minted, "
          f"{s['cardsWithAliases']} cards with aliases")
    print(f"review: {s['groups']} groups, {s['unmatched']} unmatched singles, {s['groupAliases']} aliased groups, "
          f"{s['conflicts']} conflicts")


if __name__ == "__main__":
    main()
