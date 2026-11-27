"""The permanent-id ledger: ids/<kind>.json, one append-only file per kind of published id.

    uv run python tools/ids.py [--check-against REV]

Run after the whole import pipeline, before validate.py and build.py. Each file is {"<kind>": [entries sorted by
id]}. This module mints print ids and loads, saves and checks the ledger; tools/reconcile.py decides which id each
record carries.

The default reconciles data/cards, sets/, data/archetypes.json and data/sealed with the ledger and the hand decisions
of mappings/ids.json, writes ids/ and review/ids.json (what was retired or renamed, for a person to look at), and
exits 3 when a set or archetype was renamed: the ledger now holds the new name under the old slug, and the pipeline
must run again so the data carries it. --check-against REV compares the ledger on disk with the one at git REV and
exits 1 when an entry was removed, an id or a print's birth key changed, or a formerKeys/formerIds/names list lost
what it had.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from collections import defaultdict
from collections.abc import Container, Mapping
from pathlib import Path

import reconcile
import ygjson

IDS = ygjson.ROOT / "ids"
KINDS = ("prints", "printings", "cards", "sets", "archetypes", "sealed")
YGJSON_NAMESPACE = uuid.UUID("7d674373-b170-5fd8-ab33-29bacad29ffa")  # uuid5(NAMESPACE_URL, "https://github.com/ArthurG-data/ygjson")


def mint(birth_key: str, taken: Container[str]) -> str:
    """The uuid5 of the key the print was born with; on a collision with a taken id, of "<key>#2", "#3", ..."""
    new_id = str(uuid.uuid5(YGJSON_NAMESPACE, birth_key))
    n = 1
    while new_id in taken:
        n += 1
        new_id = str(uuid.uuid5(YGJSON_NAMESPACE, f"{birth_key}#{n}"))
    return new_id


def load_ledger(path: Path = IDS) -> dict[str, dict[str, dict]]:
    """{kind: {id: entry}}; a missing file loads empty."""
    ledger: dict[str, dict[str, dict]] = {}
    for kind in KINDS:
        file = path / f"{kind}.json"
        entries = json.loads(file.read_text(encoding="utf-8"))[kind] if file.exists() else []
        ledger[kind] = _by_id(kind, entries)
    return ledger


def _by_id(kind: str, entries: list[dict]) -> dict[str, dict]:
    """{id: entry}; an id held by two entries is refused rather than one silently replacing the other."""
    out: dict[str, dict] = {}
    for e in entries:
        if e["id"] in out:
            raise ValueError(f"{kind}: id {e['id']} appears twice")
        out[e["id"]] = e
    return out


def save_ledger(ledger: dict[str, dict[str, dict]], path: Path = IDS) -> None:
    """One file per kind, entries sorted by id."""
    for kind in KINDS:
        ygjson.save_json(path / f"{kind}.json", {kind: [e for _, e in sorted(ledger.get(kind, {}).items())]})


def held_names(ledger: dict[str, dict[str, dict]], kind: str) -> dict[str, str]:
    """{name: slug} over every name of every entry of a slug kind, live or retired; a name under two slugs goes to
    the smallest."""
    held: dict[str, str] = {}
    for slug, entry in sorted(ledger.get(kind, {}).items()):
        for name in entry["names"]:
            held.setdefault(name, slug)
    return held


def reserved(ledger: dict[str, dict[str, dict]], kind: str) -> set[str]:
    """Every id the ledger holds for a kind, live or retired: none may be given to another record."""
    return set(ledger.get(kind, {}))


def schema_errors(ledger: dict[str, dict[str, dict]]) -> list[str]:
    """Schema violations of the ledger, as readable strings."""
    doc = {kind: sorted(entries.values(), key=lambda e: e["id"]) for kind, entries in ledger.items()}
    return ygjson._schema_errors("ids.schema.json", "ids", doc)


HAND = ygjson.ROOT / "mappings" / "ids.json"


def load_hand(path: Path = HAND) -> tuple[dict[str, str], dict[str, list[str]]]:
    """The hand decisions of mappings/ids.json: ({newcomer key: retired print id}, {retired id: successor ids}).
    An entry without a non-empty "why" is refused; a missing file is empty."""
    if not path.exists():
        return {}, {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    for section in ("prints", "successors"):
        for name, entry in doc.get(section, {}).items():
            if not str(entry.get("why", "")).strip():
                raise ValueError(f"{path.name}: {section} entry {name!r} has no why")
    return ({key: e["id"] for key, e in doc.get("prints", {}).items()},
            {pid: list(e["successors"]) for pid, e in doc.get("successors", {}).items()})


def hand_errors(ledger: dict[str, dict[str, dict]], hand: tuple[dict[str, str], dict[str, list[str]]]) -> list[str]:
    """Hand decisions the ledger contradicts: a print given a live id or one the ledger lacks; successors set on
    an id that is not a retired print, or naming ids that are not prints."""
    keys, successors = hand
    prints = ledger.get("prints", {})
    errors = []
    for key, pid in sorted(keys.items()):
        if pid not in prints:
            errors.append(f"hand print {key!r}: id {pid} is not in the ledger")
        elif prints[pid]["status"] == "live":
            errors.append(f"hand print {key!r}: id {pid} is live")
    by_id: dict[str, list[str]] = {}
    for key, pid in sorted(keys.items()):
        by_id.setdefault(pid, []).append(key)
    for pid, named in sorted(by_id.items()):
        if len(named) > 1:
            errors.append(f"hand prints {', '.join(repr(k) for k in named)}: all claim id {pid}")
    for pid, targets in sorted(successors.items()):
        if pid not in prints or prints[pid]["status"] != "retired":
            errors.append(f"hand successors {pid!r}: not a retired print")
        for target in targets:
            if target not in prints:
                errors.append(f"hand successors {pid!r}: successor {target} is not in the ledger")
    return errors


def apply_successors(entries: dict[str, dict], overrides: Mapping[str, list[str]]) -> dict[str, dict]:
    """A copy of the print entries with the hand-given successors set on the retired ones."""
    out = {pid: dict(entry) for pid, entry in entries.items()}
    for pid, targets in overrides.items():
        if pid in out and out[pid]["status"] == "retired":
            out[pid]["successors"] = list(targets)
    return out


def review_body(prints: list[dict], cards: list[dict], renames: list[dict]) -> dict:
    """The body of review/ids.json: what reconcile retired or renamed, for a person to look at."""
    return {"prints": sorted(prints, key=lambda r: r["id"]), "cards": sorted(cards, key=lambda r: r["id"]),
            "renames": sorted(renames, key=lambda r: r["from"])}


REVIEW = ygjson.ROOT / "review" / "ids.json"
SET_ALIASES = ygjson.ROOT / "mappings" / "ygoprodeck_set_aliases.json"


def run(ledger: dict[str, dict[str, dict]], sets: list[dict], files: dict[str, dict], archetypes: dict,
        sealed: dict[str, dict], hand: tuple[dict[str, str], dict[str, list[str]]],
        merges: Mapping[str, str]) -> tuple[dict[str, dict[str, dict]], dict, list[dict]]:
    """Reconcile every kind with the data: (new ledger, review body, rename rows). Cards go first so prints can follow
    a retired card to its successor; printings follow the prints. `merges` is {alias set slug: target slug}. `ledger`
    is not modified."""
    keys, successors = hand
    cards = [c for body in files.values() for c in body.get("cards", [])]
    card_entries, card_successor, card_rows = reconcile.reconcile_cards(ledger.get("cards", {}), cards)
    print_entries, print_ids, print_rows = reconcile.reconcile_prints(
        ledger.get("prints", {}), reconcile.current_prints(files), card_successor, keys)
    print_entries = apply_successors(print_entries, successors)
    printing_entries = reconcile.reconcile_printings(ledger.get("printings", {}), reconcile.printings_of(sets, files),
                                                     print_ids, print_entries)
    set_entries, set_renames = reconcile.reconcile_slugs(ledger.get("sets", {}), sets, "name", reconcile.set_identity,
                                                         merges, evidence=reconcile.set_evidence)
    archetype_entries, archetype_renames = reconcile.reconcile_slugs(
        ledger.get("archetypes", {}), archetypes["archetypes"], "name", reconcile.archetype_identity, id_field="slug")
    products = [p for body in sealed.values() for p in body.get("products", [])]
    sealed_entries = reconcile.reconcile_sealed(ledger.get("sealed", {}), products)
    renames = set_renames + archetype_renames
    new = {"prints": print_entries, "printings": printing_entries, "cards": card_entries, "sets": set_entries,
           "archetypes": archetype_entries, "sealed": sealed_entries}
    return new, review_body(print_rows, card_rows, renames), renames


def _both_ways(kind: str, entries: Mapping[str, dict], current: Container[str], field: str = "id") -> list[str]:
    """Each current value is the `field` of exactly one live entry; each live entry's is current; a retired one's is
    not, unless its successors include the live entry that holds it now."""
    live: dict[str, list[str]] = defaultdict(list)
    for i, e in sorted(entries.items()):
        if e["status"] == "live":
            live[e[field]].append(i)
    errors = []
    for i, e in sorted(entries.items()):
        if e["status"] == "live":
            if e[field] not in current:
                errors.append(f"{kind} {i}: live but {e[field]!r} is not in the data")
        elif e[field] in current and not set(live.get(e[field], [])) & set(e["successors"]):
            errors.append(f"{kind} {i}: retired but {e[field]!r} is in the data")
    for value in sorted(current):
        if not live.get(value):
            errors.append(f"{kind} {value!r}: no live ledger entry")
        elif len(live[value]) > 1:
            errors.append(f"{kind} {value!r}: {len(live[value])} live ledger entries ({', '.join(live[value])})")
    return errors


def check(ledger: dict[str, dict[str, dict]], sets: list[dict], files: dict[str, dict], archetypes: dict,
          sealed: dict[str, dict], hand: tuple[dict[str, str], dict[str, list[str]]] = ({}, {})) -> list[str]:
    """Where the ledger and the data disagree, as readable strings: schema errors; an entry filed under another id;
    a print key, printing, card, set, archetype or sealed product with no live entry, a live entry not in the data
    or a retired one that is; a successor the kind does not hold; and the hand decisions the ledger contradicts."""
    errors = schema_errors(ledger)
    if errors:
        return errors  # the checks below read fields the schema guarantees
    for kind in KINDS:
        for i, e in sorted(ledger.get(kind, {}).items()):
            if e.get("id") != i:
                errors.append(f"{kind} {i}: filed under {i!r} but its id is {e.get('id')!r}")
            for s in e.get("successors", []):
                if s not in ledger.get(kind, {}):
                    errors.append(f"{kind} {i}: successor {s} is not in the ledger")

    prints = ledger.get("prints", {})
    keys = {p["id"] for body in files.values() for card in body.get("cards", []) for p in card.get("prints", [])}
    errors += _both_ways("print", prints, keys, "key")
    print_ids = {e["key"]: i for i, e in sorted(prints.items()) if e["status"] == "live"}
    printings = {f"{print_ids[key]}:{language}:{edition}": ygjson.printing_id(key, language, edition)
                 for key, language, edition in reconcile.printings_of(sets, files) if key in print_ids}
    errors += _both_ways("printing", ledger.get("printings", {}), printings)
    for i, readable in sorted(printings.items()):
        entry = ledger.get("printings", {}).get(i)
        if entry and entry["key"] != readable:
            errors.append(f"printing {i}: key is {entry['key']!r}, the data gives {readable!r}")
    errors += _both_ways("card", ledger.get("cards", {}),
                         {c["id"] for body in files.values() for c in body.get("cards", [])})
    errors += _both_ways("set", ledger.get("sets", {}), {s["id"] for s in sets})
    errors += _both_ways("archetype", ledger.get("archetypes", {}), {a["slug"] for a in archetypes["archetypes"]})
    errors += _both_ways("sealed product", ledger.get("sealed", {}),
                         {p["id"] for body in sealed.values() for p in body.get("products", [])})
    return errors + hand_errors(ledger, hand)


def diff_errors(before: dict[str, dict[str, dict]], after: dict[str, dict[str, dict]]) -> list[str]:
    """What `after` dropped of `before`: an entry removed, an id or a print's birth key changed, or a formerKeys,
    formerIds or names list that no longer starts with what it held."""
    errors = []
    for kind in KINDS:
        later = after.get(kind, {})
        for i, old in sorted(before.get(kind, {}).items()):
            new = later.get(i)
            if new is None:
                errors.append(f"{kind} {i}: removed")
                continue
            if new.get("id") != old.get("id"):
                errors.append(f"{kind} {i}: id changed from {old.get('id')!r} to {new.get('id')!r}")
            for field in ("formerKeys", "formerIds", "names"):
                held = old.get(field, [])
                if new.get(field, [])[:len(held)] != held:
                    errors.append(f"{kind} {i}: {field} {held} is not kept at the start of {new.get(field, [])}")
            if kind == "prints" and _birth(new) != _birth(old):
                errors.append(f"{kind} {i}: born as {_birth(old)!r}, now says {_birth(new)!r}")
    return errors


def _birth(entry: dict) -> str | None:
    """The key a print was born with: its first former key, else its key."""
    return (entry.get("formerKeys") or [entry.get("key")])[0]


def ledger_at(rev: str, root: Path = ygjson.ROOT) -> dict[str, dict[str, dict]]:
    """The ledger committed at git `rev`; a kind whose file is not there loads empty. Exits on a rev git lacks."""
    known = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"], cwd=root,
                           capture_output=True)
    if known.returncode != 0:
        sys.exit(f"{rev}: no such git revision")
    ledger: dict[str, dict[str, dict]] = {}
    for kind in KINDS:
        shown = subprocess.run(["git", "show", f"{rev}:ids/{kind}.json"], cwd=root, capture_output=True)
        entries = json.loads(shown.stdout.decode("utf-8"))[kind] if shown.returncode == 0 else []
        ledger[kind] = _by_id(kind, entries)
    return ledger


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check-against", metavar="REV", help="compare the ledger on disk with the one at git REV")
    args = ap.parse_args(argv)
    if args.check_against:
        errors = diff_errors(ledger_at(args.check_against), load_ledger(IDS))
        for e in errors:
            print(e)
        print(f"{len(errors)} ledger problems against {args.check_against}")
        sys.exit(1 if errors else 0)

    aliases = json.loads(SET_ALIASES.read_text(encoding="utf-8")) if SET_ALIASES.exists() else {}
    merges = {alias: entry["set"] for alias, entry in aliases.items()}
    ledger, review, renames = run(load_ledger(IDS), ygjson.load_sets(), ygjson.load_cards(),
                                  ygjson.load_archetypes(), ygjson.load_sealed(), load_hand(HAND), merges)
    save_ledger(ledger, IDS)
    ygjson.save_json(REVIEW, review)
    counts = [f"{kind} {sum(e['status'] == 'live' for e in ledger[kind].values())} live "
              f"{sum(e['status'] == 'retired' for e in ledger[kind].values())} retired" for kind in KINDS]
    print("ids/ written: " + ", ".join(counts) + f"; {len(review['prints']) + len(review['cards'])} to review")
    if renames:
        for r in renames:
            print(f"renamed: {r['from']} now carries {r['name']!r} (would have been {r['to']})")
        print(f"{len(renames)} renames: rerun the pipeline so the data carries the old slugs")
        sys.exit(3)


if __name__ == "__main__":
    main()
