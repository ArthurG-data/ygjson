import json

import pytest

import rarities
from ygjson import SCHEMAS


def test_misspellings_and_abbreviations_map_to_their_code():
    assert rarities.canonical("PLatinum Secret Rare") == "platinum_secret_rare"
    assert rarities.canonical("Starfoil") == "starfoil_rare"
    assert rarities.canonical("Extra Secret") == "extra_secret_rare"
    assert rarities.canonical("Cr") == "collectors_rare"
    assert rarities.canonical("Duel Terminal Normal Rare Parallel Rare") == "dt_rare_parallel"
    assert rarities.canonical("Ultra Rare (Pharaoh's Rare)") == "pharaohs_rare"


@pytest.mark.parametrize("raw, code", [
    ("Prismatic Collector's Rare", "collectors_rare"),
    ("Prismatic Ultimate Rare", "ultimate_rare"),
    ("Duel Terminal Technology Common", "dt_normal_parallel"),
    ("Duel Terminal Technology Ultra Rare", "dt_ultra_parallel"),
    ("Parallel Rare", "normal_parallel_rare"),
    ("Ultra Pharaoh's Rare", "pharaohs_rare"),
    ("Ultra Pharaoh\u2019s Rare", "pharaohs_rare"),
    # Emblazoned is a treatment: the rarity under it is the print's.
    ("Emblazoned Ultra Rare", "ultra_rare"),
    ("Emblazoned Secret Rare", "secret_rare"),
])
def test_tcgplayer_only_spellings_map_to_their_code(raw, code):
    assert rarities.canonical(raw) == code


@pytest.mark.parametrize("raw", ["Promo", "Secret Pharaoh's Rare", "Secret Pharaoh\u2019s Rare"])
def test_tcgplayer_rarities_with_no_print_stay_unknown(raw):
    assert rarities.canonical(raw) == "unknown"


def test_canonical_is_forgiving_about_case_and_space_and_falls_back_to_unknown():
    assert rarities.canonical("  super rare ") == "super_rare"
    assert rarities.canonical("ULTRA RARE") == "ultra_rare"
    for raw in ("New", "2", "force-SMW", "", None):
        assert rarities.canonical(raw) == "unknown"


def test_every_alias_lands_on_a_listed_code():
    assert set(rarities.ALIASES.values()) <= set(rarities.CODES)
    assert rarities.CODES[-1] == "unknown"
    assert list(rarities.CODES[:-1]) == sorted(rarities.CODES[:-1])


def test_schema_enum_is_the_code_list():
    schema = json.loads((SCHEMAS / "cards.schema.json").read_text(encoding="utf-8"))
    assert schema["$defs"]["print"]["properties"]["rarity"]["enum"] == list(rarities.CODES)


@pytest.mark.parametrize("code, foil", [("common", False), ("rare", False), ("short_print", False),
                                         ("super_short_print", False), ("ultra_rare", True), ("secret_rare", True),
                                         ("normal_parallel_rare", True), ("unknown", None), (None, None)])
def test_is_foil(code, foil):
    assert rarities.is_foil(code) is foil


@pytest.mark.parametrize("code, tier", [("common", 1), ("super_short_print", 1), ("rare", 2), ("dt_rare_parallel", 2),
                                         ("super_rare", 3), ("dt_super_parallel", 3), ("ultra_rare", 4),
                                         ("millennium_ultra", 4), ("gold_rare", 4), ("secret_rare", 5),
                                         ("starlight_rare", 5), ("millennium_gold_rare", 5), ("unknown", None),
                                         (None, None)])
def test_tier_ladder(code, tier):
    assert rarities.tier(code) == tier


def test_every_known_code_has_a_tier():
    assert [c for c in rarities.CODES if c != "unknown" and rarities.tier(c) is None] == []
