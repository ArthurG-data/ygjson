import json

import pytest

import tcgcsv


def product(name="Dark Magician", **extended):
    return tcgcsv.Product(product_id=1, group_id=2, name=name, clean_name=name, image_url="", url="", extended=extended)


def test_category_and_user_agent():
    assert tcgcsv.CATEGORY == 2
    assert tcgcsv.USER_AGENT == "ygjson/0.1 (+https://github.com/ArthurG-data/ygjson)"


@pytest.mark.parametrize("extended, single", [
    ({"Number": "LOB-EN005", "Rarity": "Ultra Rare"}, True),
    ({"Number": "LOB-EN005"}, True),
    ({"Rarity": "Promo"}, True),
    ({"Description": "A booster pack"}, False),
    ({}, False),
])
def test_is_single_needs_a_number_or_a_rarity(extended, single):
    assert product(**extended).is_single is single


@pytest.mark.parametrize("name, base, tags", [
    ("Dark Magician", "Dark Magician", []),
    ("Dark Magician (Secret Rare)", "Dark Magician", ["Secret Rare"]),
    ("Blue-Eyes White Dragon (Starlight Rare)", "Blue-Eyes White Dragon", ["Starlight Rare"]),
    ("Tin Promo (Duel Terminal) (Red)", "Tin Promo", ["Duel Terminal", "Red"]),
    ("Dragon Treasure [1st Edition]", "Dragon Treasure", ["1st Edition"]),
    ('Token: Mecha Phantom Beast (B) - "Harrliard"', 'Token: Mecha Phantom Beast (B) - "Harrliard"', []),
    ("(Odd) Name (Alternate Art)", "(Odd) Name", ["Alternate Art"]),
])
def test_base_name_and_tags(name, base, tags):
    assert product(name).base_name_and_tags() == (base, tags)


def test_reads_the_cache_without_the_network(tmp_path):
    (tmp_path / "2_groups.json").write_text(json.dumps({"success": True, "results": [{"groupId": 5, "name": "LOB"}]}))
    (tmp_path / "2_5_products.json").write_text(json.dumps({"results": [{
        "productId": 9, "groupId": 5, "name": "Dark Magician", "cleanName": "Dark Magician", "url": "https://x/9",
        "presaleInfo": {"releasedOn": "2002-03-08T00:00:00"},
        "extendedData": [{"name": "Number", "value": "LOB-EN005"}, {"name": "Rarity", "value": "Ultra Rare"}]}]}))
    (tmp_path / "2_5_prices.json").write_text(json.dumps({"results": [{"productId": 9, "subTypeName": "1st Edition"}]}))
    assert tcgcsv.groups(tmp_path) == [{"groupId": 5, "name": "LOB"}]
    (p,) = tcgcsv.products(5, tmp_path)
    assert (p.product_id, p.number, p.rarity, p.released_on, p.url) == (9, "LOB-EN005", "Ultra Rare", "2002-03-08", "https://x/9")
    assert tcgcsv.prices(5, tmp_path) == [{"productId": 9, "subTypeName": "1st Edition"}]
