"""The permanent-id ledger: ids/<kind>.json, one append-only file per kind of published id.

Each file is {"<kind>": [entries sorted by id]}. This module mints print ids and loads, saves and validates the
ledger; tools/reconcile.py decides which id each print carries.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Container
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


def schema_errors(ledger: dict[str, dict[str, dict]]) -> list[str]:
    """Schema violations of the ledger, as readable strings."""
    doc = {kind: sorted(entries.values(), key=lambda e: e["id"]) for kind, entries in ledger.items()}
    return ygjson._schema_errors("ids.schema.json", "ids", doc)
