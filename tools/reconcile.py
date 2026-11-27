"""Facts about prints and the rules that carry permanent ids across a rebuild. Pure functions: no file IO.

Used by the build; see tools/ids.py for the ledger itself.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

import ids
import ygjson


@dataclass(frozen=True)
class PrintFacts:
    key: str
    set: str
    card: str
    number: str
    rarity: str
    variant: str | None
    products: frozenset[int]


def parse_key(key: str, products: Iterable[int] = ()) -> PrintFacts:
    """Split a readable key (set:card:number:rarity[:variant]) into its parts; the number may be empty."""
    parts = key.split(":", 4)
    if len(parts) < 4:
        raise ValueError(f"not a print key: {key!r}")
    set_id, card, number, rarity = parts[:4]
    variant = parts[4] if len(parts) == 5 else None
    return PrintFacts(key, set_id, card, number, rarity, variant, frozenset(products))


def current_prints(files: dict[str, dict]) -> list[PrintFacts]:
    """The facts of every print in the data/cards bodies, sorted by key."""
    found = [parse_key(p["id"], (p.get("identifiers") or {}).get("tcgplayerProductIds", []))
             for body in files.values() for card in body.get("cards", []) for p in card.get("prints", [])]
    return sorted(found, key=lambda f: f.key)


def rekey_card(key: str, card_successor: Mapping[str, str]) -> str:
    """The key with its card part replaced when that card is retired with one successor."""
    parts = key.split(":", 2)
    if len(parts) < 3 or parts[1] not in card_successor:
        return key
    parts[1] = card_successor[parts[1]]
    return ":".join(parts)


def reconcile_prints(entries: dict[str, dict], current: list[PrintFacts], card_successor: Mapping[str, str] = {},
                     hand: Mapping[str, str] = {}) -> tuple[dict[str, dict], dict[str, str]]:
    """Decide the ledger id each current print carries: (new print entries, {current key: id}).

    A newcomer (a print no live entry has) takes, by the first rule that settles it: 1 the id of a retired entry that
    had its key (the smallest when several had it), 2 the id of the one orphan (a live entry whose print is gone) that
    held a TCGplayer product no other current print holds, when that orphan is of the newcomer's card, 3 the one
    orphan at its (set, card, number), 4 the one orphan at its (card, number, rarity, variant) in another set, when the
    number is not empty, 5 the retired id `hand` gives it (one that is not a retired id is ignored), 6 a new id. Each
    rule is a pass over what is still unmatched. Orphans left are retired with the successors `_successor_places`
    finds. A retired entry that had a current key (as its key or a former key) gains that key's id as a successor, so
    a reader holding it reaches the print now at its key. `entries` is not modified.
    """
    out = {i: {k: list(v) if isinstance(v, list) else v for k, v in e.items()} for i, e in sorted(entries.items())}
    facts = {p.key: p for p in current}
    carried, orphans = _carry_live(out, facts, card_successor)
    newcomers = {k: facts[k] for k in sorted(facts) if k not in carried}

    revivable = {i for i, e in out.items() if e["status"] == "retired"}
    _revive(out, newcomers, revivable, carried)
    _settle(_by_product(facts, newcomers, orphans), newcomers, orphans, carried)
    _settle(_by_place(newcomers, orphans, lambda f: (f.set, f.card, f.number)), newcomers, orphans, carried)
    _settle([(k, i) for k, i in _by_place(newcomers, orphans, lambda f: (f.card, f.number, f.rarity, f.variant))
             if newcomers[k].number and newcomers[k].set != orphans[i].set], newcomers, orphans, carried)
    _hand(hand, newcomers, revivable, carried)
    taken = set(out)
    for key in newcomers:
        carried[key] = ids.mint(key, taken)
        taken.add(carried[key])
        out[carried[key]] = {"id": carried[key], "key": key, "formerKeys": [], "status": "live", "successors": [],
                             "products": []}

    for key, i in carried.items():
        e = out[i]
        if e["key"] != key:
            if e["key"] not in e["formerKeys"]:
                e["formerKeys"].append(e["key"])
            e["key"] = key
        e.update(status="live", successors=[], products=sorted(facts[key].products))

    successors = _successor_index(current, carried)
    for i, f in sorted(orphans.items()):
        found = next((successors[n].get(at) for n, at in enumerate(_successor_places(f))
                      if at is not None and successors[n].get(at)), [])
        out[i].update(status="retired", successors=sorted(set(found)))
    for e in out.values():
        if e["status"] == "retired":
            back = {carried[k] for k in [e["key"], *e["formerKeys"]] if k in carried}
            if not back <= set(e["successors"]):
                e["successors"] = sorted(set(e["successors"]) | back)
    return dict(sorted(out.items())), dict(sorted(carried.items()))


def printings_of(sets: list[dict], files: dict[str, dict]) -> list[tuple[str, str, str]]:
    """(print key, language, edition) of every printing `ygjson.flatten` emits, sorted."""
    editions = {s["id"]: s["editions"] for s in sets}
    return sorted((p["id"], "en", edition) for body in files.values() for card in body.get("cards", [])
                  for p in card.get("prints", []) for edition in ygjson.print_editions(p, editions[p["set"]]))


def reconcile_printings(entries: dict[str, dict], printings: list[tuple[str, str, str]], print_ids: Mapping[str, str],
                        print_entries: Mapping[str, dict]) -> dict[str, dict]:
    """Update the printing ledger, keyed by printing id (`<print id>:<language>:<edition>`).

    A printing in `printings` is live: it keeps its entry's id, its `key` is refreshed and a changed key goes to
    `formerIds`. A live entry not in `printings` is retired. Its successors are, when its print is retired, the same
    language and edition on each successor print if that printing is live, else all of that print's live printings; when
    its print is live (the edition was dropped), the print's other live printings. An entry already retired and not
    emitted is left as it is.
    `entries` is not modified.
    """
    out = {i: {k: list(v) if isinstance(v, list) else v for k, v in e.items()} for i, e in sorted(entries.items())}
    live_ids: dict[str, str] = {}
    for key, language, edition in printings:
        pid = f"{print_ids[key]}:{language}:{edition}"
        readable = ygjson.printing_id(key, language, edition)
        live_ids[pid] = readable
        entry = out.setdefault(pid, {"id": pid, "key": readable, "formerIds": [], "status": "live", "successors": []})
        if entry["key"] != readable:
            if entry["key"] not in entry["formerIds"]:
                entry["formerIds"].append(entry["key"])
            entry["key"] = readable
        entry["status"], entry["successors"] = "live", []
    by_print: dict[str, list[str]] = defaultdict(list)
    for pid in live_ids:
        by_print[pid.split(":", 2)[0]].append(pid)
    for pid, entry in out.items():
        if pid in live_ids or entry["status"] == "retired":
            continue
        print_id, language, edition = pid.split(":", 2)
        owner = print_entries.get(print_id)
        entry["status"] = "retired"
        if owner is None:
            entry["successors"] = []
        elif owner["status"] == "retired":
            # The successor print's printing in the same language and edition, else all of its live printings.
            tail = f":{language}:{edition}"
            entry["successors"] = sorted({i for s in owner["successors"]
                                          for i in ([s + tail] if s + tail in live_ids else by_print.get(s, []))})
        else:
            entry["successors"] = sorted(by_print.get(print_id, []))
    return dict(sorted(out.items()))


def reconcile_cards(entries: dict[str, dict], cards: list[dict]) -> tuple[dict[str, dict], dict[str, str]]:
    """Update the card ledger: (new card entries, {retired card id: its one successor}).

    A card in `cards` is live: its `name` and `konamiId` (kept from the entry when the card has none) are refreshed.
    A live entry whose card is gone is retired; its successor is the one current card with its name, else the one
    with its konamiId. With none or several it has no successor. An entry already retired is left as it is.
    `entries` is not modified.
    """
    out = {i: {k: list(v) if isinstance(v, list) else v for k, v in e.items()} for i, e in sorted(entries.items())}
    current = {c["id"]: c for c in cards}
    for cid in sorted(current):
        card = current[cid]
        entry = {"id": cid, "name": card["name"], "status": "live", "successors": []}
        konami = (card.get("identifiers") or {}).get("konamiId", out.get(cid, {}).get("konamiId"))
        if konami is not None:
            entry["konamiId"] = konami
        out[cid] = entry
    by_name: dict[str, list[str]] = defaultdict(list)
    by_konami: dict[int, list[str]] = defaultdict(list)
    for cid, card in sorted(current.items()):
        by_name[card["name"]].append(cid)
        if (card.get("identifiers") or {}).get("konamiId") is not None:
            by_konami[card["identifiers"]["konamiId"]].append(cid)

    successor: dict[str, str] = {}
    for cid, entry in out.items():
        if cid in current or entry["status"] == "retired":
            continue
        named = by_name.get(entry["name"], [])
        konami = by_konami.get(entry.get("konamiId"), []) if entry.get("konamiId") is not None else []
        found = named if len(named) == 1 else konami if len(konami) == 1 else named if len(named) > 1 else konami
        entry["status"] = "retired"
        if len(found) == 1:
            entry["successors"] = [found[0]]
            successor[cid] = found[0]
        else:
            entry["successors"] = []
    return dict(sorted(out.items())), dict(sorted(successor.items()))


def set_identity(s: dict) -> set[str]:
    """The ids a set carries that survive a rename: its YGOJSON id, Yugipedia page id, Konami database ids and
    TCGplayer group ids. A group is on one set only (validate.py refuses one on two), so a set import_tcgcsv minted
    for a group and a later set holding that group are the same set."""
    ident = s.get("identifiers") or {}
    found = {f"konami:{i}" for i in ident.get("konamiDatabaseIds", [])}
    found |= {f"tcgplayer:{g}" for g in s.get("tcgplayerGroupIds", [])}
    if "ygojsonId" in ident:
        found.add(f"ygojson:{ident['ygojsonId']}")
    if "yugipediaId" in ident:
        found.add(f"yugipedia:{ident['yugipediaId']}")
    return found


def set_evidence(s: dict) -> dict:
    """What a set's ledger entry keeps to name a successor once the set is gone: its code and first release date."""
    found = {"code": s["code"]} if "code" in s else {}
    releases = s.get("releases") or []
    if releases and releases[0].get("releaseDate"):
        found["releaseDate"] = releases[0]["releaseDate"]
    return found


def archetype_identity(a: dict) -> set[str]:
    """The id an archetype carries that survives a rename: its YGOJSON id."""
    ident = a.get("identifiers") or {}
    return {f"ygojson:{ident['ygojsonId']}"} if "ygojsonId" in ident else set()


def reconcile_slugs(entries: dict[str, dict], current: list[dict], name_field: str,
                    identity: Callable[[dict], set[str]], merges: Mapping[str, str] = {}, *, id_field: str = "id",
                    evidence: Callable[[dict], dict] = lambda r: {}) -> tuple[dict[str, dict], list[dict]]:
    """Update a slug ledger (sets, archetypes): (new entries, rename rows sorted by "from").

    A record in `current` (its slug at `id_field`) is live: its name joins `names`, its identity (sorted) and
    `evidence` fields are refreshed, keeping a stored value the record lacks. A slug new to the ledger gets an entry,
    unless it is a rename: it shares an identity with exactly one live slug gone in this call, and that slug shares
    one with no other new slug. Then the old entry stays live and gains the new name, the new slug gets no entry, and
    a row {"from", "to", "name"} asks for the import to run again. A live slug gone otherwise is retired: a key of
    `merges` with the merge target as successor, else with the one remaining new slug whose `code` and `releaseDate`
    equal the entry's, if exactly one. An entry already retired and not current is left as it is. `entries` is not
    modified.
    """
    out = {i: {k: list(v) if isinstance(v, list) else v for k, v in e.items()} for i, e in sorted(entries.items())}
    records = {r[id_field]: r for r in current}
    new = [i for i in sorted(records) if i not in out]
    gone = [i for i, e in out.items() if e["status"] == "live" and i not in records and i not in merges]
    found = {i: set(identity(records[i])) for i in new}
    stored = {i: set(out[i].get("identity", [])) for i in gone}
    hits_of_gone = {g: [n for n in new if stored[g] & found[n]] for g in gone}
    hits_of_new = {n: [g for g in gone if stored[g] & found[n]] for n in new}
    renamed = {g: hits[0] for g, hits in hits_of_gone.items() if len(hits) == 1 and hits_of_new[hits[0]] == [g]}
    renamed_to = set(renamed.values())

    def refresh(entry: dict, record: dict) -> None:
        if record[name_field] not in entry["names"]:
            entry["names"].append(record[name_field])
        entry["status"], entry["successors"] = "live", []
        ident = sorted(identity(record))
        if ident:
            entry["identity"] = ident
        entry.update({k: v for k, v in evidence(record).items() if v is not None})

    for i, record in sorted(records.items()):
        if i in renamed_to:
            continue
        refresh(out.setdefault(i, {"id": i, "names": [], "status": "live", "successors": []}), record)
    for g, n in renamed.items():
        refresh(out[g], records[n])
    remaining = [n for n in new if n not in renamed_to]
    for g in [i for i, e in out.items() if e["status"] == "live" and i not in records and i not in renamed]:
        e = out[g]
        if g in merges:
            successors = [merges[g]]
        elif "code" in e and "releaseDate" in e:
            same = [n for n in remaining if {k: evidence(records[n]).get(k) for k in ("code", "releaseDate")}
                    == {"code": e["code"], "releaseDate": e["releaseDate"]}]
            successors = same if len(same) == 1 else []
        else:
            successors = []
        e["status"], e["successors"] = "retired", successors
    renames = [{"from": g, "to": n, "name": records[n][name_field]} for g, n in renamed.items()]
    return dict(sorted(out.items())), sorted(renames, key=lambda r: r["from"])


def reconcile_sealed(entries: dict[str, dict], products: list[dict]) -> dict[str, dict]:
    """Update the sealed ledger, keyed by slug: a product in `products` is live with its first TCGplayer product id; a
    live entry whose product is gone is retired with no successor. `entries` is not modified."""
    out = {i: {k: list(v) if isinstance(v, list) else v for k, v in e.items()} for i, e in sorted(entries.items())}
    current = {p["id"]: p for p in products}
    for i, p in sorted(current.items()):
        out[i] = {"id": i, "tcgplayerProductId": p["identifiers"]["tcgplayerProductIds"][0], "status": "live",
                  "successors": []}
    for i, e in out.items():
        if i not in current and e["status"] == "live":
            e["status"], e["successors"] = "retired", []
    return dict(sorted(out.items()))


def _carry_live(out: dict[str, dict], facts: Mapping[str, PrintFacts],
                card_successor: Mapping[str, str]) -> tuple[dict[str, str], dict[str, PrintFacts]]:
    """({current key: id} for live entries still at a current key, {id: facts} of the live entries left: the orphans).

    An entry at the key itself claims the print before one that reaches it through `rekey_card`.
    """
    live = [(i, e["key"], rekey_card(e["key"], card_successor)) for i, e in out.items() if e["status"] == "live"]
    carried: dict[str, str] = {}
    for i, key, _ in live:
        if key in facts:
            carried[key] = i
    claimed = set(carried.values())
    orphans: dict[str, PrintFacts] = {}
    for i, _, rekeyed in live:
        if i in claimed:
            continue
        if rekeyed in facts and rekeyed not in carried:
            carried[rekeyed] = i
        else:
            orphans[i] = parse_key(rekeyed, out[i]["products"])
    return carried, orphans


def _revive(out: dict[str, dict], newcomers: dict[str, PrintFacts], revivable: set[str],
            carried: dict[str, str]) -> None:
    """Rule 1: a newcomer whose key a retired entry had takes that id back; the smallest when several had it."""
    had: dict[str, list[str]] = defaultdict(list)
    for i in sorted(revivable):
        for key in dict.fromkeys([out[i]["key"], *out[i]["formerKeys"]]):
            had[key].append(i)
    for key in list(newcomers):
        candidates = [i for i in had.get(key, []) if i in revivable]
        if not candidates:
            continue
        carried[key] = candidates[0]
        revivable.discard(candidates[0])
        del newcomers[key]


def _by_product(facts: Mapping[str, PrintFacts], newcomers: Mapping[str, PrintFacts],
                orphans: Mapping[str, PrintFacts]) -> list[tuple[str, str]]:
    """Rule 2: (newcomer key, orphan id) where only that orphan held one of the products that, of every current print,
    only that newcomer holds, and the orphan is of the newcomer's card (its facts already rekeyed through a retired
    card's successor). A product shared across cards carries nothing."""
    holders: dict[int, list[str]] = defaultdict(list)
    for key, f in facts.items():
        for product in f.products:
            holders[product].append(key)
    held_by: dict[int, list[str]] = defaultdict(list)
    for i, f in orphans.items():
        for product in f.products:
            held_by[product].append(i)
    pairs = []
    for key, f in newcomers.items():
        held = {i for product in f.products if holders[product] == [key] for i in held_by.get(product, [])}
        if len(held) == 1 and orphans[next(iter(held))].card == f.card:
            pairs.append((key, held.pop()))
    return pairs


def _by_place(newcomers: Mapping[str, PrintFacts], orphans: Mapping[str, PrintFacts],
              place: Callable[[PrintFacts], tuple]) -> list[tuple[str, str]]:
    """Rules 3 and 4: (newcomer key, orphan id) where they are the only newcomer and the only orphan at a place."""
    new_at: dict[tuple, list[str]] = defaultdict(list)
    old_at: dict[tuple, list[str]] = defaultdict(list)
    for key, f in newcomers.items():
        new_at[place(f)].append(key)
    for i, f in orphans.items():
        old_at[place(f)].append(i)
    return [(keys[0], old_at[at][0]) for at, keys in new_at.items() if len(keys) == 1 and len(old_at.get(at, [])) == 1]


def _settle(pairs: list[tuple[str, str]], newcomers: dict[str, PrintFacts], orphans: dict[str, PrintFacts],
            carried: dict[str, str]) -> None:
    """Give each newcomer its orphan's id, unless another newcomer of the same pass points at that orphan too."""
    claims: dict[str, list[str]] = defaultdict(list)
    for key, i in pairs:
        claims[i].append(key)
    for i, keys in sorted(claims.items()):
        if len(keys) == 1:
            carried[keys[0]] = i
            del newcomers[keys[0]], orphans[i]


def _hand(hand: Mapping[str, str], newcomers: dict[str, PrintFacts], revivable: set[str],
          carried: dict[str, str]) -> None:
    """Rule 5: the retired id a person gave the newcomer's key; one that is not a retired id is ignored (check reports
    it)."""
    for key in [k for k in newcomers if k in hand]:
        if hand[key] in revivable:
            carried[key] = hand[key]
            revivable.discard(hand[key])
            del newcomers[key]


def _successor_places(f: PrintFacts) -> tuple[tuple | None, ...]:
    """Where a retired print looks for its successors, in order, the first non-empty place winning: (set, card,
    number, rarity), (set, card, number), (card, number, rarity, variant) and (card, number) when the number is not
    empty, then (set, card, rarity, variant) for a corrected number. None marks a place the print does not have."""
    numbered = f.number != ""
    return ((f.set, f.card, f.number, f.rarity), (f.set, f.card, f.number),
            (f.card, f.number, f.rarity, f.variant) if numbered else None, (f.card, f.number) if numbered else None,
            (f.set, f.card, f.rarity, f.variant))


def _successor_index(current: list[PrintFacts], carried: Mapping[str, str]) -> tuple[dict[tuple, list[str]], ...]:
    """Ids of the current prints at each place of `_successor_places`, in its order."""
    index: tuple[dict[tuple, list[str]], ...] = tuple(defaultdict(list) for _ in range(5))
    for f in current:
        for by_place, at in zip(index, _successor_places(f), strict=True):
            if at is not None:
                by_place[at].append(carried[f.key])
    return index
