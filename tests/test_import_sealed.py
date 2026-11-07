import pytest

import import_sealed as imp
import tcgcsv
import ygjson

ERAS = [{"code": "dm", "name": "Duel Monsters", "mechanic": "Fusion", "from": "2002-03-08"}]
_ids = iter(range(100, 10_000))


def mkset(set_id, name, kind="booster", groups=(), **over):
    s = {"id": set_id, "code": set_id[:4].upper(), "name": name, "type": kind, "editions": ["unlimited"],
         "source": "ygoprodeck", "releases": [{"language": "en", "name": name}], "tcgplayerGroupIds": list(groups)}
    s.update(over)
    return s


def mkcard(card_id, name, prints, **identifiers):
    return {"id": card_id, "name": name, "names": {"en": name}, "kind": "monster", "frame": "normal", "hasEffect": False,
            "isTuner": False, "identifiers": {"ygoprodeckId": int(card_id), **identifiers}, "prints": prints}


def mkprint(set_id, card_id, number, rarity="rare", variant=None):
    p = {"id": ygjson.print_id(set_id, card_id, number, rarity, variant), "set": set_id, "number": number, "rarity": rarity}
    return {**p, "variant": variant, "source": "tcgplayer"} if variant else p


def prod(group_id, name, product_id=None, released=None):
    return tcgcsv.Product(product_id=product_id or next(_ids), group_id=group_id, name=name, clean_name=name, image_url="",
                          url="https://tcgplayer.com/product/" + "".join(c if c.isalnum() else "-" for c in name), extended={"Description": "d"},
                          released_on=released)


def card_single(group_id, name):
    return tcgcsv.Product(product_id=next(_ids), group_id=group_id, name=name, clean_name=name, image_url="", url="",
                          extended={"Number": "X-1", "Rarity": "Rare"})


def build(products, sets, cards=(), ygo=()):
    groups = [{"groupId": gid, "name": f"group {gid}"} for gid in products]
    files = {"000": {"cards": list(cards)}}
    out = imp.build(groups, products, sets, files, list(ygo))
    out["by_name"] = {p["name"]: p for body in out["files"].values() for p in body["products"]}
    return out


@pytest.mark.parametrize("name, expected", [
    ("Raging Tempest Booster Box [1st Edition]", "booster_box"),
    ("Mini Booster Box", "booster_box"),
    ("Dark Neostorm Tuck Box (Retail Exclusive)", "booster_box"),
    ("Raging Tempest Booster Box Case [1st Edition]", "case"),
    ("Dragon Treasure Display", "display"),
    ("Cyber Strike Structure Deck Display [1st Edition]", "display"),
    ("Mega Tin [Set of 2]", "display"),
    ("Raging Tempest Booster Pack", "booster_pack"),
    ("Doom of Dimensions Sleeved Booster Pack", "booster_pack"),
    ("Forbidden Legacy - Blister Pack", "booster_pack"),
    ("Wave of Light Structure Deck", "structure_deck"),
    ("Starter Deck: Yugi [1st Edition]", "starter_deck"),
    ("Yugi's Starter", "starter_deck"),
    ("Ultimate Predators Speed Duel Deck", "deck"),
    ("2016 Mega-Tin [Kaiba & Obelisk]", "mega_tin"),
    ("2007 Collectors Tin: Rainbow Dragon", "tin"),
    ("Ghosts From the Past: The 2nd Haunting Pack", "other"),  # "tin" inside a word is not a tin
    ("Dark Neostorm: Special Edition Box", "special_edition"),
    ("Cosmo Blazer SE", "special_edition"),
    ("Legendary Dragon Decks Collector's Set", "deck"),
    ("Premium Gold Mini-Box Set", "collectors_set"),
    ("Duel Power Promo Pack", "promo_pack"),
    ("Speed Duel: Tournament Pack 6", "promo_pack"),
    ("Silver Dragon Value Box", "bundle"),
    ("Sealed Play Battle Kit 2 (Ra)", "bundle"),
    ("Maze of Muertos Field Center Card Box (Retail Exclusive)", "accessory"),
    ("Master Collection Volume 1 Binder", "accessory"),
    ("Yugi Deck Box", "accessory"),
    ("Duel Monsters Playmat", "accessory"),
    ("25th Anniversary Ultimate Kaiba Set Briefcase", "other"),
    ("Magnificent Mavens Box", "other"),
    ("Lots of Fun Set", "collectors_set"),
])
def test_category_rules(name, expected):
    assert imp.category(name) == expected


@pytest.mark.parametrize("name, tag, stripped", [
    ("Absolute Powerforce - Booster Box [1st Edition]", "first", "Absolute Powerforce - Booster Box"),
    ("Metal Raiders Booster Pack [Unlimited Edition]", "unlimited", "Metal Raiders Booster Pack"),
    ("Power of the Elements Booster Box [Unlimited]", "unlimited", "Power of the Elements Booster Box"),
    ("Legacy of Darkness Booster Box [1st Edition North American English]", "first", "Legacy of Darkness Booster Box"),
    ("Dragunity Legion Structure Deck - 1st Edition", "first", "Dragunity Legion Structure Deck"),
    ("Invincible Fortress Structure Deck - Unlimited Edition", "unlimited", "Invincible Fortress Structure Deck"),
    ("Yugi's Collector Box [Limited Edition]", "limited", "Yugi's Collector Box"),
    ("Raging Tempest Booster Box", None, "Raging Tempest Booster Box"),
    ("2016 Mega-Tin [Set of 2]", None, "2016 Mega-Tin [Set of 2]"),
])
def test_edition_tag_and_the_name_without_it(name, tag, stripped):
    assert imp.edition_tag(name) == tag and imp.strip_edition(name) == stripped


def test_pack_count_comes_from_the_name_else_24():
    assert imp.box_packs("Dark Crisis - Booster Box (36 packs)") == 36
    assert imp.box_packs("Dragons of Legend Booster Box (24 count)") == 24
    assert imp.box_packs("Raging Tempest Booster Box") == 24


def test_ids_are_unique_and_the_first_edition_keeps_the_plain_slug_whatever_the_input_order():
    def records(order):
        names = {1: "Foo Booster Box [Unlimited Edition]", 2: "Foo Booster Box [1st Edition]", 3: "Foo Booster Box",
                 4: "Foo Booster Box (Retail Exclusive)", 5: "Bar"}
        rs = [{"productId": i, "name": names[i], "tag": imp.edition_tag(names[i])} for i in order]
        imp.assign_ids(rs)
        return {r["productId"]: r["id"] for r in rs}

    a = records([1, 2, 3, 4, 5])
    assert a == {2: "foo-booster-box", 3: "foo-booster-box-2", 1: "foo-booster-box-3", 4: "foo-booster-box-retail-exclusive",
                 5: "bar"}
    assert records([5, 4, 3, 2, 1]) == a


# --- a set with products ----------------------------------------------------------------------------------------

def tcg_world():
    lob = mkset("lob", "Legend", groups=[1])
    deck = mkset("sd", "Some Structure Deck", kind="structure_deck", groups=[2])
    tin = mkset("tin", "2020 Tin", kind="tin", groups=[3])
    cards = [mkcard("100", "Alpha", [mkprint("lob", "100", "LOB-EN001"), mkprint("sd", "100", "SD-EN001"),
                                      mkprint("tin", "100", "TIN-EN001")]),
             mkcard("200", "Beta", [mkprint("sd", "200", "SD-EN002", "common")])]
    products = {
        1: [prod(1, "Legend Booster Pack [1st Edition]", 11), prod(1, "Legend Booster Pack [Unlimited Edition]", 12),
            prod(1, "Legend Booster Box [1st Edition]", 13), prod(1, "Legend Booster Box [Unlimited Edition]", 14),
            prod(1, "Legend Booster Box Case [1st Edition]", 15), prod(1, "Legend Display [1st Edition]", 16),
            prod(1, "Legend Mini Booster Box [1st Edition]", 17), prod(1, "Legend Booster Box (36 packs)", 18),
            prod(1, "Legend Playmat", 19), prod(1, "Legend Mystery Thing", 20, released="2002-03-08T00:00:00"[:10]),
            card_single(1, "A card")],
        2: [prod(2, "Some Structure Deck", 21), prod(2, "Some Structure Deck Display", 22)],
        3: [prod(3, "2020 Tin of Lost Memories", 31), prod(3, "2020 Special Edition Box", 32)],
        4: [prod(4, "Lost Binder", 41), prod(4, "Lost Tin", 42)],
    }
    return products, [lob, deck, tin], cards


def test_products_by_set_accessories_skipped_and_the_rest_reviewed():
    products, sets, cards = tcg_world()
    out = build(products, sets, cards)
    assert set(out["files"]) == {"lob", "sd", "tin"}
    assert [p["id"] for p in out["files"]["sd"]["products"]] == ["some-structure-deck", "some-structure-deck-display"]
    assert out["stats"]["accessories"] == 2  # the playmat and the binder
    assert out["review"]["noSet"] == [{"productId": 42, "name": "Lost Tin", "groupId": 4, "group": "group 4"}]
    assert out["review"]["other"] == [{"productId": 20, "name": "Legend Mystery Thing", "set": "lob"}]
    assert out["by_name"]["Legend Mystery Thing"]["releaseDate"] == "2002-03-08"
    assert "releaseDate" not in out["by_name"]["Legend Booster Pack [1st Edition]"]
    assert out["by_name"]["Legend Booster Pack [1st Edition]"]["sources"] == ["https://tcgplayer.com/product/Legend-Booster-Pack--1st-Edition-"]


def test_a_booster_box_holds_24_of_the_pack_with_its_edition():
    out = build(*tcg_world())
    first, unlimited = out["by_name"]["Legend Booster Box [1st Edition]"], out["by_name"]["Legend Booster Box [Unlimited Edition]"]
    assert first["contents"] == {"sealed": [{"product": "legend-booster-pack", "count": 24}]}
    assert unlimited["contents"] == {"sealed": [{"product": "legend-booster-pack-2", "count": 24}]}
    assert first["contentsStatus"] == unlimited["contentsStatus"] == "complete"
    assert first["identifiers"] == {"tcgplayerProductIds": [13]}


def test_a_box_whose_pack_is_not_unique_or_missing_is_unknown_and_a_mini_box_has_no_count():
    out = build(*tcg_world())
    untagged = out["by_name"]["Legend Booster Box (36 packs)"]  # no untagged pack in the group
    assert (untagged["contents"], untagged["contentsStatus"]) == ({}, "unknown")
    mini = out["by_name"]["Legend Mini Booster Box [1st Edition]"]
    assert mini["contents"] == {"sealed": [{"product": "legend-booster-pack"}]} and mini["contentsStatus"] == "partial"


def test_the_pack_count_in_a_name_is_used():
    products = {1: [prod(1, "Legend Booster Pack"), prod(1, "Legend Booster Box (36 packs)")]}
    out = build(products, [mkset("lob", "Legend", groups=[1])])
    assert out["by_name"]["Legend Booster Box (36 packs)"]["contents"]["sealed"][0]["count"] == 36


def test_two_packs_with_one_tag_make_the_box_unknown():
    products = {1: [prod(1, "Legend Booster Pack"), prod(1, "Legend Sleeved Booster Pack"), prod(1, "Legend Booster Box")]}
    out = build(products, [mkset("lob", "Legend", groups=[1])])
    assert out["by_name"]["Legend Booster Box"]["contentsStatus"] == "unknown"


def test_a_case_holds_12_boxes_and_a_display_holds_its_unit_without_a_count():
    out = build(*tcg_world())
    case = out["by_name"]["Legend Booster Box Case [1st Edition]"]
    assert case["contents"] == {"sealed": [{"product": "legend-booster-box", "count": 12}]} and case["contentsStatus"] == "complete"
    display = out["by_name"]["Legend Display [1st Edition]"]
    assert display["contents"] == {"sealed": [{"product": "legend-booster-pack"}]} and display["contentsStatus"] == "partial"
    deck_display = out["by_name"]["Some Structure Deck Display"]
    assert deck_display["contents"] == {"sealed": [{"product": "some-structure-deck"}]}


def test_a_booster_pack_draws_from_its_set_in_its_edition():
    out = build(*tcg_world())
    assert out["by_name"]["Legend Booster Pack [1st Edition]"]["contents"] == {"pool": [{"set": "lob", "editions": ["first"]}]}
    assert out["by_name"]["Legend Booster Pack [1st Edition]"]["contentsStatus"] == "partial"
    assert out["by_name"]["Legend Booster Pack [Unlimited Edition]"]["contents"]["pool"][0]["editions"] == ["unlimited"]


def test_decks_tins_and_special_editions_list_their_sets_prints_only_in_a_set_that_fits():
    out = build(*tcg_world())
    deck = out["by_name"]["Some Structure Deck"]
    assert deck["contents"] == {"cards": [{"print": "sd:100:SD-EN001:rare"}, {"print": "sd:200:SD-EN002:common"}]}
    assert deck["contentsStatus"] == "partial"
    assert out["by_name"]["2020 Tin of Lost Memories"]["contents"] == {"cards": [{"print": "tin:100:TIN-EN001:rare"}]}
    # A special edition filed under a tin set does not list the tin's prints.
    se = out["by_name"]["2020 Special Edition Box"]
    assert (se["contents"], se["contentsStatus"]) == ({}, "unknown")


def test_a_deck_lists_a_cards_art_letters_but_not_its_treatments():
    base, art = mkprint("sd", "100", "SD-EN001"), mkprint("sd", "100", "SD-EN001", variant="b")
    misprint = mkprint("sd", "100", "SD-EN001", variant="unlimited-misprint")
    products = {1: [prod(1, "Some Structure Deck")]}
    out = build(products, [mkset("sd", "Some Structure Deck", "structure_deck", groups=[1])],
                [mkcard("100", "A", [base, art, misprint])])
    assert out["by_name"]["Some Structure Deck"]["contents"] == {"cards": [{"print": base["id"]}, {"print": art["id"]}]}


def test_a_treatment_does_not_make_a_cards_print_in_a_set_ambiguous():
    base, stamp = mkprint("sd", "100", "SD-EN001"), mkprint("sd", "100", "SD-EN001", variant="judge-stamp")
    ctx = imp.Context([], [mkset("sd", "Some Structure Deck", "structure_deck")], {"000": {"cards": [mkcard("100", "A", [base, stamp])]}})
    assert ctx.card_prints[("100", "sd")] == [base["id"]]


def test_a_deck_in_a_booster_set_is_unknown():
    products = {1: [prod(1, "Legend Structure Deck")]}
    out = build(products, [mkset("lob", "Legend", groups=[1])], [mkcard("100", "A", [mkprint("lob", "100", "LOB-EN001")])])
    assert out["by_name"]["Legend Structure Deck"]["contentsStatus"] == "unknown"


def test_the_output_is_valid_data():
    products, sets, cards = tcg_world()
    out = build(products, sets, cards)
    errors = ygjson.validate(sets, ERAS, {"000": {"cards": cards}}, {"archetypes": []}, out["files"])
    assert errors == []


# --- YGOJSON ----------------------------------------------------------------------------------------------------

def ygo(uuid, name, packs, locales=("en",), **over):
    g = {"id": uuid, "name": {"en": name}, "locales": {code: {} for code in locales},
         "contents": [{"locales": list(locales), "packs": packs}]}
    g.update(over)
    return g


def test_ygojson_adds_its_id_and_a_boxs_packs_with_quantity():
    products = {1: [prod(1, "Legend Booster Pack", 11), prod(1, "Legend Booster Box", 12)]}
    sets = [mkset("lob", "Legend", groups=[1], identifiers={"ygojsonId": "set-lob"})]
    out = build(products, sets, ygo=[ygo("p1", "Legend (Box)", [{"set": "set-lob", "qty": 30}])])
    box = out["by_name"]["Legend Booster Box"]
    assert box["identifiers"] == {"tcgplayerProductIds": [12], "ygojsonId": "p1"}
    assert box["contents"] == {"sealed": [{"product": "legend-booster-pack", "count": 30}]}  # YGOJSON's 30, not the rule's 24
    assert box["contentsStatus"] == "complete" and box["sources"][-1] == "ygojson:p1"
    assert "ygojsonId" not in out["by_name"]["Legend Booster Pack"]["identifiers"]


def test_ygojson_cards_replace_the_rule_listing_and_a_pack_without_quantity_leaves_it_partial():
    products = {1: [prod(1, "Legend Booster Pack", 11)], 2: [prod(2, "2020 Tin Special Edition", 21)]}
    sets = [mkset("lob", "Legend", groups=[1], identifiers={"ygojsonId": "set-lob"}),
            mkset("se", "2020 Tin Special Edition", kind="special_edition", groups=[2], identifiers={"ygojsonId": "set-se"})]
    cards = [mkcard("100", "Alpha", [mkprint("se", "100", "SE-EN001"), mkprint("se", "100", "SE-EN002")], ygojsonId="card-a"),
             mkcard("200", "Beta", [mkprint("se", "200", "SE-EN003")], ygojsonId="card-b")]
    packs = [{"set": "set-lob", "qty": 3}, {"set": "set-se", "card": "card-b"}]
    out = build(products, sets, cards, [ygo("p2", "2020 Tin: Special Edition", packs)])
    se = out["by_name"]["2020 Tin Special Edition"]
    assert se["contents"] == {"sealed": [{"product": "legend-booster-pack", "count": 3}],
                              "cards": [{"print": "se:200:SE-EN003:rare", "count": 1}]}
    assert se["contentsStatus"] == "complete"
    # Alpha has two prints in the set, so a pack naming it cannot be resolved: partial.
    out = build(products, sets, cards, [ygo("p2", "2020 Tin: Special Edition", [packs[0], {"set": "set-se", "card": "card-a"}])])
    assert out["by_name"]["2020 Tin Special Edition"]["contentsStatus"] == "partial"
    assert out["by_name"]["2020 Tin Special Edition"]["contents"]["sealed"] == [{"product": "legend-booster-pack", "count": 3}]
    errors = ygjson.validate(sets, ERAS, {"000": {"cards": cards}}, {"archetypes": []}, out["files"])
    assert errors == []


def test_a_pack_missing_a_quantity_or_a_product_keeps_the_product_partial():
    products = {1: [prod(1, "Legend Booster Pack", 11), prod(1, "Legend Booster Box", 12)]}
    sets = [mkset("lob", "Legend", groups=[1], identifiers={"ygojsonId": "set-lob"})]
    out = build(products, sets, ygo=[ygo("p1", "Legend (Box)", [{"set": "set-lob"}])])
    box = out["by_name"]["Legend Booster Box"]
    assert box["contents"] == {"sealed": [{"product": "legend-booster-pack", "count": 24}]}  # untouched: nothing resolved
    unknown_set = build(products, sets, ygo=[ygo("p1", "Legend (Box)", [{"set": "elsewhere", "qty": 3}])])
    assert unknown_set["by_name"]["Legend Booster Box"]["identifiers"]["ygojsonId"] == "p1"


def test_ygojson_products_with_an_english_release_that_match_nothing_are_reviewed():
    products = {1: [prod(1, "Legend Booster Pack", 11)]}
    sets = [mkset("lob", "Legend", groups=[1])]
    ygo_products = [ygo("p9", "Nothing Like It (Box)", []), ygo("p8", "Japan Only", [], locales=("ja",)),
                    {"id": "p7", "name": {"ja": "x"}}]
    out = build(products, sets, ygo=ygo_products)
    assert out["review"]["ygojsonUnmatched"] == [{"id": "p9", "name": "Nothing Like It (Box)"}]


def test_both_editions_of_a_box_take_the_one_ygojson_product():
    products = {1: [prod(1, "Legend Booster Box [1st Edition]", 1), prod(1, "Legend Booster Box [Unlimited Edition]", 2)]}
    out = build(products, [mkset("lob", "Legend", groups=[1])], ygo=[ygo("p1", "Legend (Box)", [])])
    assert {p["identifiers"].get("ygojsonId") for p in out["by_name"].values()} == {"p1"}
