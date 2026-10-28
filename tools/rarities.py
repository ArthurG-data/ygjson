"""Rarity codes: the one place that maps a source's rarity string onto ygjson's canonical code.

YGOPRODeck's `set_rarity` and TCGplayer's `Rarity` are free text. `canonical` turns either into a code from CODES,
or `unknown` (the importers keep the raw string and count it in review/rarities.json). `is_foil` and `tier` are the
two facts AutoMana derives from a code; its SQL functions `rarity_is_foil` and `rarity_tier` must agree with them.
"""
from __future__ import annotations

ALIASES: dict[str, str] = {
    "Common": "common",
    "Rare": "rare",
    "Super Rare": "super_rare",
    "Ultra Rare": "ultra_rare",
    "Secret Rare": "secret_rare",
    "Ultimate Rare": "ultimate_rare",
    "Quarter Century Secret Rare": "qc_secret_rare",
    "Platinum Secret Rare": "platinum_secret_rare",
    "Prismatic Secret Rare": "prismatic_secret",
    "Collector's Rare": "collectors_rare",
    "Starlight Rare": "starlight_rare",
    "Short Print": "short_print",
    "Super Short Print": "super_short_print",
    "Gold Rare": "gold_rare",
    "Gold Secret Rare": "gold_secret_rare",
    "Premium Gold Rare": "premium_gold_rare",
    "Ghost Rare": "ghost_rare",
    "Ghost/Gold Rare": "ghost_gold_rare",
    "Starfoil Rare": "starfoil_rare",
    "Mosaic Rare": "mosaic_rare",
    "Shatterfoil Rare": "shatterfoil_rare",
    "Platinum Rare": "platinum_rare",
    "Grand Master Rare": "grand_master_rare",
    "Ultra Rare (Pharaoh's Rare)": "pharaohs_rare",
    "Extra Secret Rare": "extra_secret_rare",
    "Ultra Secret Rare": "ultra_secret_rare",
    "10000 Secret Rare": "10000_secret_rare",
    "Normal Parallel Rare": "normal_parallel_rare",
    "Super Parallel Rare": "super_parallel_rare",
    "Ultra Parallel Rare": "ultra_parallel_rare",
    "Secret Parallel Rare": "secret_parallel_rare",
    "Duel Terminal Normal Parallel Rare": "dt_normal_parallel",
    "Duel Terminal Rare Parallel Rare": "dt_rare_parallel",
    "Duel Terminal Super Parallel Rare": "dt_super_parallel",
    "Duel Terminal Ultra Parallel Rare": "dt_ultra_parallel",
    "Duel Terminal Secret Parallel Rare": "dt_secret_parallel",
    "Millennium Rare": "millennium_rare",
    "Millennium Super Rare": "millennium_super",
    "Millennium Ultra Rare": "millennium_ultra",
    "Millennium Secret Rare": "millennium_secret",
    "Millennium Gold Rare": "millennium_gold_rare",
    # Misspellings and abbreviations seen on YGOPRODeck.
    "PLatinum Secret Rare": "platinum_secret_rare",
    "Starfoil": "starfoil_rare",
    "Extra Secret": "extra_secret_rare",
    "Cr": "collectors_rare",
    "Duel Terminal Normal Rare Parallel Rare": "dt_rare_parallel",
    # Spellings only TCGplayer uses. Each pairs with the one print YGOPRODeck leaves uncovered at that number
    # (measured over the TCGCSV cache: 388 numbers pair Prismatic Collector's and Ultimate, 137 and 25 pair the
    # Duel Terminal Technology rarities, 12 pair Parallel Rare).
    "Prismatic Collector's Rare": "collectors_rare",
    "Prismatic Ultimate Rare": "ultimate_rare",
    "Duel Terminal Technology Common": "dt_normal_parallel",
    "Duel Terminal Technology Ultra Rare": "dt_ultra_parallel",
    "Parallel Rare": "normal_parallel_rare",
    "Ultra Pharaoh's Rare": "pharaohs_rare",
    "Ultra Pharaoh\u2019s Rare": "pharaohs_rare",
}

UNKNOWN = "unknown"
CODES: tuple[str, ...] = (*sorted(set(ALIASES.values())), UNKNOWN)

_FOLDED = {raw.casefold(): code for raw, code in ALIASES.items()}
_NONFOIL = {"common", "short_print", "super_short_print", "rare"}
_TIERS = {
    1: ("common", "short_print", "super_short_print"),
    2: ("rare", "normal_parallel_rare", "dt_normal_parallel", "dt_rare_parallel"),
    3: ("super_rare", "super_parallel_rare", "dt_super_parallel"),
    4: ("ultra_rare", "ultimate_rare", "ultra_parallel_rare", "dt_ultra_parallel", "gold_rare", "premium_gold_rare",
        "platinum_rare", "starfoil_rare", "mosaic_rare", "shatterfoil_rare", "millennium_rare", "millennium_super",
        "millennium_ultra"),
}
_TIER_OF = {code: tier for tier, codes in _TIERS.items() for code in codes}


def canonical(raw: str | None) -> str:
    """The code for a source's rarity string: exact alias, else case-insensitive alias, else `unknown`."""
    if raw is None:
        return UNKNOWN
    raw = raw.strip()
    return ALIASES.get(raw) or _FOLDED.get(raw.casefold(), UNKNOWN)


def is_foil(code: str | None) -> bool | None:
    """False for the plain-card rarities, None when the code is unknown (the importer decides), else True."""
    if code is None or code == UNKNOWN:
        return None
    return code not in _NONFOIL


def tier(code: str | None) -> int | None:
    """Value ladder 1..5, a parallel following its base rarity; 5 is every other code (the secret families, ghost,
    starlight, collector's, grand master, Pharaoh's, Millennium secret and gold). None for None and `unknown`."""
    if code is None or code == UNKNOWN:
        return None
    return _TIER_OF.get(code, 5)
