"""Facts about prints and the rules that carry permanent ids across a rebuild. Pure functions: no file IO.

Used by the build; see tools/ids.py for the ledger itself.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


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
