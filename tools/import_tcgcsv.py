"""Tie TCGplayer's Yu-Gi-Oh! groups and products (TCGCSV category 2) to our sets and prints, and write review/tcgplayer-2.json.

    uv run python tools/import_tcgcsv.py

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
Whatever remains goes to review `unmatched` with the reason. A product lands on one print only. A print holds
several products only when they are the same card at the same rarity (the (Red) and (Blue) tin promos); a product
that would share a print with another card, or another rarity, goes to review `conflicts`.
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

import rarities
import tcgcsv
import ygjson
from import_ygojson import normalise

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
RULES = ("exact_name", "normalised_name", "worldwide_english", "mapping", "abbreviation", "reprint")


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
        self.touched: set[str] = set()
        for body in files.values():
            for card in body["cards"]:
                for p in card["prints"]:
                    self.add(card, p)

    def add(self, card: dict, p: dict) -> None:
        if p.get("number"):
            self.by_set_number[(p["set"], p["number"])].append((card, p))
            self.by_number[p["number"]].add(p["set"])

    def find(self, set_id: str, number: str) -> list[tuple[dict, dict]]:
        return self.by_set_number.get((set_id, number), [])

    def sort_prints(self) -> None:
        for body in self.files.values():
            for card in body["cards"]:
                card["prints"].sort(key=lambda p: p["id"])


def _product_ids(p: dict) -> list[int]:
    return p.get("identifiers", {}).get("tcgplayerProductIds", [])


def _edition_list(editions) -> list[str]:
    return [e for e in EDITION_ORDER if e in editions]


class Importer:
    def __init__(self, sets, files, groups, products, prices, mapping):
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

    # --- groups -----------------------------------------------------------------------------------------------

    def match_groups(self) -> list[dict]:
        found = match_groups(list(self.groups.values()), list(self.sets.values()), self.mapping)
        for gid, (set_id, rule) in found["matches"].items():
            self.set_of_group[gid] = set_id
            self.group_rules[rule] += 1
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
        """Put the product on the print. False (and a review entry) when the print holds another card or rarity."""
        held = [i for i in _product_ids(p) if i != prod.product_id and i in self.by_id]
        mine = (normalise(prod.base_name_and_tags()[0]), rarities.canonical(prod.rarity))
        for i in held:
            other = self.by_id[i]
            if (normalise(other.base_name_and_tags()[0]), rarities.canonical(other.rarity)) != mine:
                self.conflicts.append({"productId": prod.product_id, "name": prod.name, "groupId": prod.group_id,
                                       "print": p["id"], "heldBy": held,
                                       "reason": "the print holds a product of another name or rarity"})
                return False
        previous = self.owner.get(prod.product_id)
        if previous is not None and previous is not p:
            previous["identifiers"]["tcgplayerProductIds"].remove(prod.product_id)
            if not previous["identifiers"]["tcgplayerProductIds"]:
                del previous["identifiers"], previous["tcgplayer"]
        ids = p.setdefault("identifiers", {}).setdefault("tcgplayerProductIds", [])
        if prod.product_id not in ids:
            ids.append(prod.product_id)
            ids.sort()
        kept = p.get("tcgplayer")
        if kept is None:
            p["tcgplayer"] = {"name": prod.name, "match": match}
        elif not (kept["match"] == "number+rarity-from-tcgplayer" and match == "number+rarity"):
            kept["match"] = match  # a re-keyed print matches exactly on the next run, but keeps its label
        self.owner[prod.product_id] = p
        self.landed_in[p["set"]].add(prod.product_id)
        self.stats[p["tcgplayer"]["match"]] += 1
        return True

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
            self._review(prod, "no print has this number" + ("" if own else "; the group matched no set"))
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


def run(groups, products, prices, sets, files, mapping) -> dict:
    """Everything the tool does, on in-memory data: {"sets", "files", "review", "stats"}."""
    imp = Importer(sets, files, groups, products, prices, mapping)
    unmatched_groups = imp.match_groups()
    imp.match_singles()
    editions_changed = imp.merge_editions()
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
             "rekeyed": imp.rekeyed, "minted": imp.minted, **{k: len(v) for k, v in review.items()}}
    return {"sets": sorted(imp.sets.values(), key=lambda s: s["id"]), "files": imp.catalog.files, "review": review,
            "stats": stats}


def load_mapping(path: Path = MAPPING) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def main() -> None:
    groups = tcgcsv.groups(CACHE)
    products = {g["groupId"]: tcgcsv.products(g["groupId"], CACHE) for g in groups}
    prices = {g["groupId"]: tcgcsv.prices(g["groupId"], CACHE) for g in groups}
    out = run(groups, products, prices, ygjson.load_sets(), ygjson.load_cards(), load_mapping())
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
          f"{s['minted']} reprint prints minted")
    print(f"review: {s['groups']} groups, {s['unmatched']} unmatched singles, {s['groupAliases']} aliased groups, "
          f"{s['conflicts']} conflicts")


if __name__ == "__main__":
    main()
