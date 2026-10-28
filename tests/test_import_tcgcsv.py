import copy

import pytest

import import_tcgcsv as imp
import rarities
import tcgcsv
import ygjson

ERAS = [{"code": "dm", "name": "Duel Monsters", "mechanic": "Fusion", "from": "2002-03-08"}]


def mkset(set_id, name, code, kind="booster", editions=("unlimited",), source="ygoprodeck", **over):
    s = {"id": set_id, "code": code, "name": name, "type": kind, "editions": list(editions), "source": source,
         "releases": [{"language": "en", "name": name}]}
    s.update(over)
    return s


def mkprint(set_id, card_id, number, rarity, **over):
    p = {"id": ygjson.print_id(set_id, card_id, number, rarity), "set": set_id, "number": number, "rarity": rarity}
    p.update(over)
    return p


def mkcard(card_id, name, prints):
    return {"id": card_id, "name": name, "names": {"en": name}, "kind": "monster", "frame": "normal", "hasEffect": False,
            "isTuner": False, "identifiers": {"ygoprodeckId": int(card_id)}, "prints": prints}


def mkgroup(group_id, name, abbreviation="", published="2002-03-08T00:00:00"):
    return {"groupId": group_id, "name": name, "abbreviation": abbreviation, "publishedOn": published}


_next_id = iter(range(1000, 10_000))


def single(group_id, name, number, rarity, product_id=None):
    return tcgcsv.Product(product_id=product_id or next(_next_id), group_id=group_id, name=name, clean_name=name,
                          image_url="", url="", extended={"Number": number, "Rarity": rarity})


def sealed(group_id, name, product_id=None):
    return tcgcsv.Product(product_id=product_id or next(_next_id), group_id=group_id, name=name, clean_name=name,
                          image_url="", url="https://tcg/x", extended={"Description": "x"})


def go(groups=(), products=None, prices=None, sets=(), cards=(), mapping=None):
    files = {"000": {"cards": copy.deepcopy(list(cards))}}
    out = imp.run(list(groups), products or {}, prices or {}, copy.deepcopy(list(sets)), files, mapping or {})
    out["cards"] = {c["id"]: c for c in out["files"]["000"]["cards"]}
    out["sets_by_id"] = {s["id"]: s for s in out["sets"]}
    return out


def prints_of(out, card_id):
    return {p["id"]: p for p in out["cards"][card_id]["prints"]}


# --- groups -----------------------------------------------------------------------------------------------------

def test_groups_match_by_five_rules_in_order():
    sets = [mkset("a", "Alpha Pack", "ALP"), mkset("b", "Beta Pack!", "BET"), mkset("c", "Gamma Pack", "GAM"),
            mkset("d", "Delta Pack", "DEL"), mkset("e", "Epsilon Pack", "EPS")]
    groups = [mkgroup(1, "Alpha Pack", "ALP"), mkgroup(2, "beta pack", "BET"), mkgroup(3, "Gamma Pack (Worldwide English)"),
              mkgroup(4, "The Delta Set", "XXX"), mkgroup(5, "Epsilon Booster", "EPS-EN")]
    found = imp.match_groups(groups, sets, {"4": {"set": "d", "why": "x"}})
    assert found["matches"] == {1: ("a", "exact_name"), 2: ("b", "normalised_name"), 3: ("c", "worldwide_english"),
                                4: ("d", "mapping"), 5: ("e", "abbreviation")}
    assert found["unmatched"] == [] and found["reprints"] == {}


def test_a_worldwide_english_group_joins_a_set_that_another_group_took():
    sets = [mkset("mr", "Metal Raiders", "MRD")]
    groups = [mkgroup(1, "Metal Raiders"), mkgroup(2, "Metal Raiders (Worldwide English)", "MRD-EN")]
    found = imp.match_groups(groups, sets, {})
    assert found["matches"] == {1: ("mr", "exact_name"), 2: ("mr", "worldwide_english")}
    out = go(groups, {}, {}, sets)
    assert out["sets_by_id"]["mr"]["tcgplayerGroupIds"] == [1, 2]


def test_rules_only_use_sets_and_groups_still_free():
    sets = [mkset("a", "Alpha", "ALP"), mkset("a2", "Alpha Two", "ALP")]
    groups = [mkgroup(1, "Alpha", "ALP"), mkgroup(2, "Other", "ALP")]
    found = imp.match_groups(groups, sets, {})
    # Group 1 takes "Alpha" by name; group 2's code ALP is now held by one free set, so it matches that.
    assert found["matches"] == {1: ("a", "exact_name"), 2: ("a2", "abbreviation")}


def test_abbreviation_needs_exactly_one_group_and_one_set_and_the_same_special_edition_kind():
    sets = [mkset("lob", "Legend", "LOB"), mkset("cb", "Cosmo Blazer", "CBLZ"),
            mkset("cbse", "Cosmo Blazer Special", "CBLZ", kind="special_edition"),
            mkset("x1", "X One", "XXX"), mkset("x2", "X Two", "XXX"), mkset("y", "Y", "YYY")]
    groups = [mkgroup(1, "Legend EN", "LOB-EN"), mkgroup(2, "Cosmo", "CBLZ-EN"), mkgroup(3, "Cosmo SE", "CBLZ-ENSE"),
              mkgroup(4, "Shared code", "XXX"), mkgroup(5, "Twin A", "YYY"), mkgroup(6, "Twin B", "YYY"),
              mkgroup(7, "No code", "")]
    found = imp.match_groups(groups, sets, {})
    assert found["matches"] == {1: ("lob", "abbreviation"), 2: ("cb", "abbreviation"), 3: ("cbse", "abbreviation")}
    assert [g["groupId"] for g in found["unmatched"]] == [4, 5, 6, 7]


def test_unmatched_groups_are_reviewed_with_the_sets_that_share_their_code():
    sets = [mkset("x1", "X One", "XXX"), mkset("x2", "X Two", "XXX")]
    out = go([mkgroup(4, "Shared code", "XXX-EN"), mkgroup(5, "Lonely", "")], sets=sets)
    assert out["review"]["groups"] == [
        {"groupId": 4, "name": "Shared code", "abbreviation": "XXX-EN", "candidates": ["x1", "x2"]},
        {"groupId": 5, "name": "Lonely", "abbreviation": "", "candidates": []}]


def test_a_reprint_group_mints_a_set_and_copies_the_prints_its_singles_name():
    parent = mkset("ret", "Retro Pack", "RP01", editions=("first", "unlimited"), era="dm", **{"tcgplayerGroupIds": [1]})
    cards = [mkcard("100", "Alpha", [mkprint("ret", "100", "RP01-EN001", "ultra_rare"),
                                      mkprint("ret", "100", "RP01-EN001", "common")]),
             mkcard("200", "Beta", [mkprint("ret", "200", "RP01-EN002", "rare")])]
    groups = [mkgroup(1, "Retro Pack", "RP01"), mkgroup(2, "Retro Pack (2020 Date Reprint)", "RP01", "2024-08-23T00:00:00")]
    products = {1: [], 2: [single(2, "Alpha", "RP01-EN001", "Ultra Rare"), single(2, "Beta", "RP01-EN002", "Rare")]}
    out = go(groups, products, {}, [parent], cards)
    new = out["sets_by_id"]["ret-2020-reprint"]
    assert new == {"id": "ret-2020-reprint", "code": "RP01", "name": "Retro Pack (2020 Date Reprint)", "type": "booster",
                   "editions": ["first", "unlimited"], "parent": "ret", "source": "tcgplayer", "era": "dm",
                   "tcgplayerGroupIds": [2], "releases": [{"language": "en", "name": "Retro Pack (2020 Date Reprint)",
                                                           "releaseDate": "2024-08-23"}]}
    alpha = prints_of(out, "100")
    # The common print is not named by a single, so it is not copied; the parent keeps all its prints.
    assert set(alpha) == {"ret:100:RP01-EN001:ultra_rare", "ret:100:RP01-EN001:common",
                          "ret-2020-reprint:100:RP01-EN001:ultra_rare"}
    copy_ = alpha["ret-2020-reprint:100:RP01-EN001:ultra_rare"]
    assert copy_["set"] == "ret-2020-reprint" and copy_["identifiers"]["tcgplayerProductIds"] == [products[2][0].product_id]
    assert "identifiers" not in alpha["ret:100:RP01-EN001:ultra_rare"]
    assert out["stats"]["groupRules"]["reprint"] == 1 and out["stats"]["minted"] == 2
    assert out["sets_by_id"]["ret"]["tcgplayerGroupIds"] == [1]


def test_a_reprint_hangs_off_the_candidate_that_holds_its_numbers():
    small = mkset("plain", "Collection", "LCK", kind="box_set")
    mega = mkset("mega", "Collection Mega Pack", "LCK")
    cards = [mkcard("100", "Alpha", [mkprint("mega", "100", "LCK-EN001", "rare")])]
    groups = [mkgroup(1, "Collection", "LCK"), mkgroup(2, "Collection (2020 Date Reprint)", "LCK")]
    out = go(groups, {2: [single(2, "Alpha", "LCK-EN001", "Rare")]}, {}, [small, mega], cards)
    assert out["sets_by_id"]["mega-2020-reprint"]["parent"] == "mega"
    assert "plain-2020-reprint" not in out["sets_by_id"]


def test_reprint_ids_do_not_collide_and_an_existing_reprint_set_keeps_its_identifiers_not_its_editions():
    parent = mkset("ret", "Retro Pack", "RP01", editions=("first", "unlimited"))
    old = mkset("ret-2020-reprint", "Retro Pack (2020 Date Reprint)", "RP01", source="tcgplayer", parent="ret",
                editions=["limited"], tcgplayerGroupIds=[2], identifiers={"yugipediaId": 7})
    groups = [mkgroup(2, "Retro Pack (2020 Date Reprint)", "RP01")]
    out = go(groups, {}, {}, [parent, old])
    assert [s["id"] for s in out["sets"]] == ["ret", "ret-2020-reprint"]
    assert out["sets_by_id"]["ret-2020-reprint"]["editions"] == ["first", "unlimited"]
    assert out["sets_by_id"]["ret-2020-reprint"]["identifiers"] == {"yugipediaId": 7}


def anniversary_world(with_set):
    parent = mkset("doc", "Dark of Chaos", "DOC", editions=("unlimited",), era="dm", tcgplayerGroupIds=[1])
    sets = [parent]
    if with_set:
        sets.append(mkset("doc-25", "Dark of Chaos (25th Anniversary Edition)", "DOC", editions=("unlimited",)))
    cards = [mkcard("100", "Alpha", [mkprint("doc", "100", "DOC-EN001", "ultra_rare")]),
             mkcard("200", "Beta", [mkprint("doc", "200", "DOC-EN002", "common"), mkprint("doc", "200", "DOC-EN002", "rare")])]
    groups = [mkgroup(1, "Dark of Chaos", "DOC"),
              mkgroup(2, "Dark of Chaos (25th Anniversary Edition)", "DOC", "2023-04-21T00:00:00")]
    products = {1: [single(1, "Alpha", "DOC-EN001", "Ultra Rare", 11)],
                2: [single(2, "Alpha (QCSR)", "DOC-EN001", "Quarter Century Secret Rare", 21),
                    single(2, "Beta", "DOC-EN002", "Rare", 22), single(2, "Beta", "DOC-EN002", "Super Rare", 23),
                    single(2, "Gamma", "DOC-EN009", "Rare", 24)]}
    prices = {1: [price(11, "Unlimited")], 2: [price(21, "1st Edition"), price(22, "Unlimited"), price(23, "Unlimited")]}
    return go(groups, products, prices, sets, cards)


def price(product_id, sub):
    return {"productId": product_id, "subTypeName": sub}


def test_an_anniversary_group_with_no_set_of_its_name_mints_a_child_set():
    out = anniversary_world(with_set=False)
    child = out["sets_by_id"]["doc-25th-anniversary-edition"]
    assert child == {"id": "doc-25th-anniversary-edition", "code": "DOC", "name": "Dark of Chaos (25th Anniversary Edition)",
                     "type": "booster", "editions": ["first", "unlimited"], "parent": "doc", "source": "tcgplayer", "era": "dm",
                     "tcgplayerGroupIds": [2], "releases": [{"language": "en", "name": "Dark of Chaos (25th Anniversary Edition)",
                                                             "releaseDate": "2023-04-21"}]}
    assert out["stats"]["groupRules"]["reprint"] == 1 and out["review"]["groupAliases"] == []


def test_the_anniversary_children_hold_the_products_and_the_originals_do_not():
    for with_set in (False, True):
        out = anniversary_world(with_set)
        child = "doc-25" if with_set else "doc-25th-anniversary-edition"
        alpha, beta = prints_of(out, "100"), prints_of(out, "200")
        # A rarity the parent lacks is minted at TCGplayer's rarity, from the one card that holds the number.
        assert alpha[f"{child}:100:DOC-EN001:qc_secret_rare"]["identifiers"] == {"tcgplayerProductIds": [21]}
        assert beta[f"{child}:200:DOC-EN002:rare"]["identifiers"] == {"tcgplayerProductIds": [22]}
        assert beta[f"{child}:200:DOC-EN002:super_rare"]["identifiers"] == {"tcgplayerProductIds": [23]}
        assert alpha["doc:100:DOC-EN001:ultra_rare"]["identifiers"] == {"tcgplayerProductIds": [11]}
        for p in beta.values():
            if p["set"] == "doc":
                assert "identifiers" not in p
        assert out["review"]["groupAliases"] == []
        assert [r["productId"] for r in out["review"]["unmatched"]] == [24]


def test_a_childs_editions_come_from_its_own_group_and_not_the_parents():
    out = anniversary_world(with_set=False)
    # The 1st Edition is priced on the anniversary group only: the new set gets it, the parent does not.
    assert out["sets_by_id"]["doc"]["editions"] == ["unlimited"]
    assert out["sets_by_id"]["doc-25th-anniversary-edition"]["editions"] == ["first", "unlimited"]
    out = anniversary_world(with_set=True)
    assert out["sets_by_id"]["doc"]["editions"] == ["unlimited"]
    assert out["sets_by_id"]["doc-25"]["editions"] == ["first", "unlimited"]
    assert out["sets_by_id"]["doc-25"]["tcgplayerGroupIds"] == [2] and out["sets_by_id"]["doc"]["tcgplayerGroupIds"] == [1]


# --- singles ----------------------------------------------------------------------------------------------------

LOB = mkset("lob", "Legend of Blue Eyes", "LOB", **{"tcgplayerGroupIds": []})


def world(prints, extra_sets=(), card_name="Alpha"):
    """Set 'lob' matched to group 1, one card (id 100) holding the given prints."""
    return dict(groups=[mkgroup(1, "Legend of Blue Eyes", "LOB")], sets=[LOB, *extra_sets],
                cards=[mkcard("100", card_name, prints)])


def test_rule_1_number_and_rarity():
    w = world([mkprint("lob", "100", "LOB-EN001", "ultra_rare"), mkprint("lob", "100", "LOB-EN001", "common")])
    p = single(1, "Alpha (Ultra Rare)", "LOB-EN001", "Ultra Rare", 7)
    out = go(products={1: [p]}, **w)
    hit = prints_of(out, "100")["lob:100:LOB-EN001:ultra_rare"]
    assert hit["identifiers"] == {"tcgplayerProductIds": [7]}
    assert hit["tcgplayer"] == {"name": "Alpha (Ultra Rare)", "match": "number+rarity"}
    assert "identifiers" not in prints_of(out, "100")["lob:100:LOB-EN001:common"]
    assert out["stats"]["matches"] == {"number+rarity": 1}


def test_rule_2_number_alone_when_the_set_has_one_print_of_it():
    w = world([mkprint("lob", "100", "LOB-EN001", "rare")])
    out = go(products={1: [single(1, "Alpha", "LOB-EN001", "Ultra Rare", 7)]}, **w)
    assert prints_of(out, "100")["lob:100:LOB-EN001:rare"]["tcgplayer"]["match"] == "number"


def test_two_prints_of_the_number_and_none_at_the_rarity_is_ambiguous():
    w = world([mkprint("lob", "100", "LOB-EN001", "rare"), mkprint("lob", "100", "LOB-EN001", "common")])
    out = go(products={1: [single(1, "Alpha", "LOB-EN001", "Ultra Rare", 7)]}, **w)
    (r,) = out["review"]["unmatched"]
    assert r["productId"] == 7 and r["reason"].startswith("ambiguous: 2 prints of LOB-EN001")
    assert all("identifiers" not in p for p in out["cards"]["100"]["prints"])


def test_rule_3_an_unknown_rarity_print_takes_tcgplayers_rarity():
    w = world([mkprint("lob", "100", "LOB-EN001", "unknown", rawRarity="New", region="EN")])
    out = go(products={1: [single(1, "Alpha", "LOB-EN001", "Secret Rare", 7)]}, **w)
    (key, p), = prints_of(out, "100").items()
    assert key == "lob:100:LOB-EN001:secret_rare" == p["id"]
    assert p["rarity"] == "secret_rare" and "rawRarity" not in p and p["region"] == "EN"
    assert p["tcgplayer"]["match"] == "number+rarity-from-tcgplayer" and p["identifiers"]["tcgplayerProductIds"] == [7]
    assert out["stats"]["rekeyed"] == 1


def test_an_exact_match_is_made_before_a_fuzzy_one_can_take_the_print():
    w = world([mkprint("lob", "100", "LOB-EN001", "unknown", rawRarity="2"),
               mkprint("lob", "100", "LOB-EN001", "secret_rare")])
    fuzzy = single(1, "Alpha (Ultra Rare)", "LOB-EN001", "Ultra Rare", 5)  # lower id, goes first within a pass
    exact = single(1, "Alpha (Secret Rare)", "LOB-EN001", "Secret Rare", 9)
    out = go(products={1: [fuzzy, exact]}, **w)
    prints = prints_of(out, "100")
    assert prints["lob:100:LOB-EN001:secret_rare"]["identifiers"]["tcgplayerProductIds"] == [9]
    assert prints["lob:100:LOB-EN001:ultra_rare"]["identifiers"]["tcgplayerProductIds"] == [5]


def test_rule_4_a_number_in_exactly_one_other_set_is_an_alias():
    tins = mkset("tins", "Collectible Tins 2012 Wave 1", "CT09")
    cards = [mkcard("100", "Alpha", [mkprint("tins", "100", "CT09-EN001", "ultra_rare")])]
    groups = [mkgroup(1, "2012 Collectors Tin"), mkgroup(2, "Other", "ZZ")]
    products = {1: [single(1, "Alpha", "CT09-EN001", "Ultra Rare", 7), single(1, "Alpha (Alternate Art)", "CT09-EN001", "Ultra Rare", 8)]}
    out = go(groups, products, {}, [LOB, tins], cards)
    p = prints_of(out, "100")["tins:100:CT09-EN001:ultra_rare"]
    assert p["tcgplayer"]["match"] == "number-other-set" and p["identifiers"]["tcgplayerProductIds"] == [7, 8]
    assert out["review"]["groupAliases"] == [{"groupId": 1, "name": "2012 Collectors Tin", "setsHit": {"tins": 2}}]
    assert out["review"]["groups"][0]["groupId"] == 1  # the group itself stays unmatched


def test_rule_4_also_applies_when_the_groups_set_lacks_the_number():
    other = mkset("other", "Other Set", "OTH")
    cards = [mkcard("100", "Alpha", [mkprint("other", "100", "OTH-EN001", "rare")])]
    out = go([mkgroup(1, "Legend of Blue Eyes", "LOB")], {1: [single(1, "Alpha", "OTH-EN001", "Rare", 7)]}, {},
             [LOB, other], cards)
    assert prints_of(out, "100")["other:100:OTH-EN001:rare"]["tcgplayer"]["match"] == "number-other-set"
    assert out["review"]["groupAliases"][0]["setsHit"] == {"other": 1}


def test_rule_5_review_reasons():
    two = [mkset("s1", "S1", "S1"), mkset("s2", "S2", "S2")]
    cards = [mkcard("100", "Alpha", [mkprint("s1", "100", "AAA-EN001", "rare"), mkprint("s2", "100", "AAA-EN001", "rare")])]
    products = {1: [single(1, "A", "AAA-EN001", "Rare", 1), single(1, "B", "ZZZ-EN001", "Rare", 2),
                    tcgcsv.Product(3, 1, "C", "C", "", "", {"Rarity": "Promo"})]}
    out = go([mkgroup(1, "Legend of Blue Eyes", "LOB")], products, {}, [LOB, *two], cards)
    reasons = {r["productId"]: r["reason"] for r in out["review"]["unmatched"]}
    assert reasons[1].startswith("the number is in 2 other sets: s1, s2")
    assert reasons[2] == "no print has this number"
    assert reasons[3] == "TCGplayer gives it no card number"
    assert {"productId": 1, "name": "A", "groupId": 1, "number": "AAA-EN001", "rarity": "Rare",
            "reason": reasons[1]} in out["review"]["unmatched"]


def test_a_product_in_a_group_with_no_set_and_no_matching_number_says_so():
    out = go([mkgroup(1, "Mystery Promos", "")], {1: [single(1, "A", "ZZZ-EN001", "Rare", 2)]}, {}, [LOB], [])
    assert out["review"]["unmatched"][0]["reason"] == "no print has this number; the group matched no set"


def test_two_cards_sharing_a_number_and_rarity_are_told_apart_by_name():
    w = world([mkprint("lob", "100", "LOB-EN001", "rare")])
    w["cards"].append(mkcard("200", "Beta", [mkprint("lob", "200", "LOB-EN001", "rare")]))
    out = go(products={1: [single(1, "Beta (Rare)", "LOB-EN001", "Rare", 7), single(1, "Gamma", "LOB-EN001", "Rare", 8)]}, **w)
    assert "identifiers" in prints_of(out, "200")["lob:200:LOB-EN001:rare"]
    assert "identifiers" not in prints_of(out, "100")["lob:100:LOB-EN001:rare"]
    assert out["review"]["unmatched"][0]["reason"].startswith("ambiguous: 2 prints of LOB-EN001 at rare")


def test_name_variants_of_one_card_at_one_rarity_share_a_print_and_anything_else_is_a_conflict():
    w = world([mkprint("lob", "100", "LOB-EN001", "common")])
    red = single(1, "Alpha (Red)", "LOB-EN001", "Common", 7)
    blue = single(1, "Alpha (Blue)", "LOB-EN001", "Common", 8)
    other = single(1, "Beta", "LOB-EN001", "Common", 9)
    rare = single(1, "Alpha (Rare)", "LOB-EN001", "Rare", 10)
    out = go(products={1: [red, blue, other, rare]}, **w)
    p = prints_of(out, "100")["lob:100:LOB-EN001:common"]
    assert p["identifiers"]["tcgplayerProductIds"] == [7, 8] and p["tcgplayer"]["name"] == "Alpha (Red)"
    conflicts = {c["productId"]: c for c in out["review"]["conflicts"]}
    assert set(conflicts) == {9, 10} and conflicts[9]["heldBy"] == [7, 8]
    assert conflicts[9]["print"] == p["id"]


def test_tcgplayers_own_rarity_spellings_are_understood():
    w = world([mkprint("lob", "100", "LOB-EN001", "collectors_rare"), mkprint("lob", "100", "LOB-EN001", "ultimate_rare")])
    products = {1: [single(1, "Alpha (PCR)", "LOB-EN001", "Prismatic Collector's Rare", 7),
                    single(1, "Alpha (PUR)", "LOB-EN001", "Prismatic Ultimate Rare", 8)]}
    out = go(products=products, **w)
    prints = prints_of(out, "100")
    assert prints["lob:100:LOB-EN001:collectors_rare"]["identifiers"]["tcgplayerProductIds"] == [7]
    assert prints["lob:100:LOB-EN001:ultimate_rare"]["tcgplayer"]["match"] == "number+rarity"
    assert rarities.canonical("Duel Terminal Technology Common") == "dt_normal_parallel"
    assert rarities.canonical("Secret Rare") == "secret_rare" and rarities.canonical("Mystery") == "unknown"


# --- editions ---------------------------------------------------------------------------------------------------

def test_a_sets_editions_are_unioned_with_the_priced_subtypes_in_order_and_never_shrink():
    lob = mkset("lob", "Legend of Blue Eyes", "LOB", editions=("limited", "unlimited"))
    cards = [mkcard("100", "Alpha", [mkprint("lob", "100", "LOB-EN001", "rare")])]
    out = go([mkgroup(1, "Legend of Blue Eyes", "LOB")], {1: [single(1, "Alpha", "LOB-EN001", "Rare", 7)]},
             {1: [price(7, "1st Edition"), price(7, "Normal")]}, [lob], cards)
    assert out["sets_by_id"]["lob"]["editions"] == ["first", "unlimited", "limited"]
    assert out["stats"]["setsEditionsChanged"] == 1


def test_a_print_priced_in_fewer_editions_than_its_set_gets_its_own():
    cards = [mkcard("100", "Alpha", [mkprint("lob", "100", "LOB-EN001", "rare"), mkprint("lob", "100", "LOB-EN002", "rare"),
                                     mkprint("lob", "100", "LOB-EN003", "rare")])]
    products = {1: [single(1, "Alpha 1", "LOB-EN001", "Rare", 7), single(1, "Alpha 2", "LOB-EN002", "Rare", 8)]}
    prices = {1: [price(7, "1st Edition"), price(7, "Unlimited"), price(8, "Unlimited")]}
    out = go([mkgroup(1, "Legend of Blue Eyes", "LOB")], products, prices, [LOB], cards)
    assert out["sets_by_id"]["lob"]["editions"] == ["first", "unlimited"]
    prints = prints_of(out, "100")
    assert "editions" not in prints["lob:100:LOB-EN001:rare"]  # same as the set
    assert prints["lob:100:LOB-EN002:rare"]["editions"] == ["unlimited"]
    assert "editions" not in prints["lob:100:LOB-EN003:rare"]  # no product, inherits


def test_a_sealed_product_prices_do_not_touch_editions():
    cards = [mkcard("100", "Alpha", [mkprint("lob", "100", "LOB-EN001", "rare")])]
    products = {1: [sealed(1, "Box", 5), single(1, "Alpha", "LOB-EN001", "Rare", 7)]}
    out = go([mkgroup(1, "Legend of Blue Eyes", "LOB")], products, {1: [price(5, "1st Edition"), price(7, "Unlimited")]},
             [LOB], cards)
    assert out["sets_by_id"]["lob"]["editions"] == ["unlimited"]


# --- the whole run ----------------------------------------------------------------------------------------------

def full_world():
    sets = [mkset("lob", "Legend of Blue Eyes", "LOB", era="dm"), mkset("tins", "Collectible Tins 2012 Wave 1", "CT09"),
            mkset("ret", "Retro Pack", "RP01", era="dm")]
    cards = [mkcard("100", "Alpha", [mkprint("lob", "100", "LOB-EN001", "unknown", rawRarity="New"),
                                      mkprint("lob", "100", "LOB-EN002", "rare")]),
             mkcard("200", "Beta", [mkprint("tins", "200", "CT09-EN001", "rare"), mkprint("ret", "200", "RP01-EN001", "rare")])]
    groups = [mkgroup(1, "Legend of Blue Eyes", "LOB"), mkgroup(2, "2012 Collectors Tin"),
              mkgroup(3, "Retro Pack", "RP01"), mkgroup(4, "Retro Pack (2020 Date Reprint)", "RP01")]
    products = {1: [single(1, "Alpha", "LOB-EN001", "Secret Rare", 11), single(1, "Alpha", "LOB-EN002", "Rare", 12)],
                2: [single(2, "Beta", "CT09-EN001", "Rare", 21)], 3: [single(3, "Beta", "RP01-EN001", "Rare", 31)],
                4: [single(4, "Beta", "RP01-EN001", "Rare", 41), single(4, "Nobody", "NOPE-001", "Rare", 42)]}
    prices = {1: [price(11, "1st Edition"), price(12, "Unlimited")], 4: [price(41, "Unlimited")]}
    return groups, products, prices, sets, cards


def test_a_run_is_valid_and_idempotent():
    groups, products, prices, sets, cards = full_world()
    out = go(groups, products, prices, sets, cards)
    errors = ygjson.validate(out["sets"], ERAS, out["files"], {"archetypes": []})
    assert errors == []
    again = imp.run(groups, products, prices, copy.deepcopy(out["sets"]), copy.deepcopy(out["files"]), {})
    assert again["sets"] == out["sets"] and again["files"] == out["files"]
    # The re-keyed print keeps its label on the second run (it now matches exactly).
    p = prints_of(out, "100")["lob:100:LOB-EN001:secret_rare"]
    assert p["tcgplayer"]["match"] == "number+rarity-from-tcgplayer"
    assert out["stats"]["matches"] == {"number+rarity": 3, "number+rarity-from-tcgplayer": 1, "number-other-set": 1}


def test_the_reprint_set_and_aliases_in_a_run():
    groups, products, prices, sets, cards = full_world()
    out = go(groups, products, prices, sets, cards)
    assert out["sets_by_id"]["ret-2020-reprint"]["parent"] == "ret"
    beta = prints_of(out, "200")
    assert beta["tins:200:CT09-EN001:rare"]["tcgplayer"]["match"] == "number-other-set"
    assert beta["ret-2020-reprint:200:RP01-EN001:rare"]["identifiers"] == {"tcgplayerProductIds": [41]}
    assert beta["ret:200:RP01-EN001:rare"]["identifiers"] == {"tcgplayerProductIds": [31]}
    assert [r["productId"] for r in out["review"]["unmatched"]] == [42]
    assert out["stats"]["groupsUnmatched"] == 1 and out["review"]["groups"][0]["groupId"] == 2


def test_load_mapping_is_empty_without_a_file(tmp_path):
    assert imp.load_mapping(tmp_path / "nope.json") == {}
