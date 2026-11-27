"""The permanent-id ledger: ids/<kind>.json, one append-only file per kind of published id.

Each file is {"<kind>": [entries sorted by id]}. This module mints print ids and loads, saves and validates the
ledger; tools/reconcile.py decides which id each print carries.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Container, Mapping
from pathlib import Path

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
        ledger[kind] = {e["id"]: e for e in entries}
    return ledger


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
