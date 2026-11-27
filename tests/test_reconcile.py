import pytest

import reconcile
import ygjson


def test_parse_key_with_empty_number():
    f = reconcile.parse_key("mattel-action-figure-promotional-cards-series-3:98585345::normal_parallel_rare")
    assert (f.set, f.card, f.number, f.rarity, f.variant) == ("mattel-action-figure-promotional-cards-series-3", "98585345", "", "normal_parallel_rare", None)


def test_parse_key_round_trips_a_joined_variant():
    key = "quarter-century-bonanza:24094653:RA03-EN051:collectors_rare:a-alternate-art"
    f = reconcile.parse_key(key)
    assert f.variant == "a-alternate-art"
    assert ygjson.print_id(f.set, f.card, f.number, f.rarity, f.variant) == key


def test_parse_key_keeps_products_and_rejects_short_keys():
    assert reconcile.parse_key("s:1:N:r", [3, 3, 2]).products == frozenset({2, 3})
    with pytest.raises(ValueError):
        reconcile.parse_key("s:1:N")


def test_rekey_card_swaps_a_placeholder_for_its_passcode():
    assert reconcile.rekey_card("s:101403001:X-EN001:rare", {"101403001": "82951145"}) == "s:82951145:X-EN001:rare"
    assert reconcile.rekey_card("s:5:X-EN001:rare", {}) == "s:5:X-EN001:rare"


def test_current_prints_reads_products_and_sorts():
    files = {"a.json": {"cards": [{"id": "5", "prints": [
        {"id": "s:5:B-1:rare", "set": "s", "number": "B-1", "rarity": "rare", "identifiers": {"tcgplayerProductIds": [9, 8]}},
        {"id": "s:5:A-1:rare:blue", "set": "s", "number": "A-1", "rarity": "rare", "variant": "blue"}]}]}}
    got = reconcile.current_prints(files)
    assert [p.key for p in got] == ["s:5:A-1:rare:blue", "s:5:B-1:rare"]
    assert got[0].products == frozenset() and got[1].products == frozenset({8, 9})
