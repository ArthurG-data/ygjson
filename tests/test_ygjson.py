import copy

import pytest

import ygjson


def test_print_id_adds_a_variant_only_when_there_is_one():
    assert ygjson.print_id("lob", "1", "LOB-EN001", "rare") == "lob:1:LOB-EN001:rare"
    assert ygjson.print_id("lob", "1", "LOB-EN001", "rare", "blue") == "lob:1:LOB-EN001:rare:blue"

SET = "legend-of-blue-eyes-white-dragon"
PRINT_A = f"{SET}:46986414:LOB-EN005:ultra_rare"
PRINT_B = f"{SET}:46986414:LOB-EN005:common"

SETS = [{"id": SET, "code": "LOB", "name": "Legend of Blue Eyes White Dragon", "type": "booster",
         "era": "dm", "editions": ["first", "unlimited"], "tcgplayerGroupIds": [1],
         "source": "ygoprodeck",
         "releases": [{"language": "en", "name": "Legend of Blue Eyes White Dragon", "releaseDate": "2002-03-08"}]}]
ERAS = [{"code": "dm", "name": "Duel Monsters", "mechanic": "Fusion", "from": "2002-03-08", "to": "2005-05-31"},
        {"code": "gx", "name": "GX", "mechanic": "Fusion", "from": "2005-06-01"}]
CARD = {"id": "46986414", "passcode": 46986414, "name": "Dark Magician", "names": {"en": "Dark Magician"},
        "kind": "monster", "frame": "normal", "attribute": "dark", "monsterType": "Spellcaster", "level": 7,
        "atk": 2500, "def": 2100, "hasEffect": False, "isTuner": False, "typeline": ["Spellcaster", "Normal"],
        "archetypes": ["dark-magician"], "identifiers": {"ygoprodeckId": 46986414},
        "prints": [{"id": PRINT_A, "set": SET, "number": "LOB-EN005", "region": "EN", "rarity": "ultra_rare",
                    "identifiers": {"tcgplayerProductIds": [10]}},
                   {"id": PRINT_B, "set": SET, "number": "LOB-EN005", "region": "EN", "rarity": "common",
                    "editions": ["unlimited"]}]}
CARDS = {"046": {"cards": [CARD]}}
ARCHETYPES = {"archetypes": [{"slug": "dark-magician", "name": "Dark Magician", "source": "ygoprodeck"}]}
SEALED = {SET: {"products": [{
    "id": "lob-booster-pack", "set": SET, "category": "booster_pack", "name": "LOB Booster Pack",
    "identifiers": {"tcgplayerProductIds": [20]}, "contentsStatus": "partial",
    "contents": {"pool": [{"set": SET}]}, "sources": ["https://example.com/p/20"]}]}}
LEGALITY = {"formats": [{"id": "tcg", "name": "Advanced Format (TCG)", "source": "https://example.com"}],
            "events": [{"card": "46986414", "format": "tcg", "status": "limited", "effective": "2005-03-01",
                        "source": "ygojson"}]}


def errors(sets=SETS, eras=ERAS, cards=CARDS, archetypes=ARCHETYPES, sealed=SEALED, legality=LEGALITY):
    return ygjson.validate(sets, eras, cards, archetypes, sealed, legality)


def edit(**paths):
    """A deep copy of the fixtures as a kwargs dict for errors(), with one change applied by a callable."""
    docs = {"sets": SETS, "eras": ERAS, "cards": CARDS, "archetypes": ARCHETYPES, "sealed": SEALED,
            "legality": LEGALITY}
    docs = copy.deepcopy(docs)
    for name, fn in paths.items():
        fn(docs[name])
    return docs


def test_slugify():
    assert ygjson.slugify("Legend of Blue Eyes White Dragon") == SET
    assert ygjson.slugify("Yu-Gi-Oh! 5D's Tag Force 5 Promotional Cards") == "yu-gi-oh-5d-s-tag-force-5-promotional-cards"
    assert ygjson.slugify("  --D.D.-- ") == "d-d"


def test_slugify_of_a_name_with_nothing_left_is_a_stable_hash():
    slug = ygjson.slugify("ブルーアイズ")
    assert slug.startswith("x-") and len(slug) == 14
    assert slug == ygjson.slugify("ブルーアイズ")
    assert slug != ygjson.slugify("レッドアイズ")


def test_dedupe_keeps_the_first_sorted_name_and_numbers_the_rest():
    a, b = "Yu-Gi-Oh! 5D's Tag Force 5 Promotional Cards", "Yu-Gi-Oh! 5D's Tag Force 5 promotional cards"
    out = ygjson.dedupe_slugs([b, a, "Other"])
    assert out == {a: "yu-gi-oh-5d-s-tag-force-5-promotional-cards",
                   b: "yu-gi-oh-5d-s-tag-force-5-promotional-cards-2", "Other": "other"}


def test_dedupe_punctuation_variants_and_a_literal_suffix():
    out = ygjson.dedupe_slugs(["D/D", "D.D.", "Roid", "roid", "roid 2"])
    assert out["D.D."] == "d-d" and out["D/D"] == "d-d-2"
    assert out["Roid"] == "roid" and out["roid"] == "roid-2"
    assert out["roid 2"] == "roid-2-2"  # -2 is taken by "roid", so a real "roid-2" slug cannot be repeated


def test_dedupe_keeps_held_slugs_when_an_earlier_name_arrives():
    assert ygjson.dedupe_slugs(["Roid", "ROID"], held={"Roid": "roid"}) == {"Roid": "roid", "ROID": "roid-2"}


def test_dedupe_never_reuses_a_reserved_slug():
    assert ygjson.dedupe_slugs(["Foo"], reserved={"foo"}) == {"Foo": "foo-2"}


def test_dedupe_never_hands_a_held_slug_to_another_name():
    # "Bar" is held at "foo"; "Foo" is new and must not take it even though "Bar" is absent this run.
    assert ygjson.dedupe_slugs(["Foo"], held={"Bar": "foo"}) == {"Foo": "foo-2"}
    # Two current names held at one slug: the first in sorted order keeps it, the other gets a free one.
    assert ygjson.dedupe_slugs(["New", "Old"], held={"New": "x", "Old": "x"}) == {"New": "x", "Old": "old"}


def test_dedupe_is_independent_of_input_order():
    names = ["a b", "A-B", "a.b"]
    assert ygjson.dedupe_slugs(names) == ygjson.dedupe_slugs(reversed(names))


@pytest.mark.parametrize("number, region", [("LOB-EN001", "EN"), ("LOB-001", None), ("LAVD-ENS05", "EN"),
                                             ("TKN3-EN005", "EN"),
                                             ("TDIL-ENSE3", "EN"), ("CYHO-ENSP1", "EN"), ("RGBT-ENPP5", "EN"),
                                             ("SS01-ENAS1", "EN"), ("IOC-SE1", "SE"), ("SDK-E001", "E"), ("RA01-PT012", "PT"),
                                             ("", None), (None, None), ("nohyphen", None)])
def test_region_of(number, region):
    assert ygjson.region_of(number) == region


def test_card_bucket():
    assert ygjson.card_bucket("46986414") == "046"
    assert ygjson.card_bucket("4007") == "000"
    assert ygjson.card_bucket("100000001") == "100"
    assert ygjson.card_bucket("149694341") == "149"


def test_print_and_printing_ids():
    assert ygjson.print_id(SET, "46986414", "LOB-EN005", "ultra_rare") == PRINT_A
    assert ygjson.print_id("promo", "1", None, "common") == "promo:1::common"
    assert ygjson.printing_id(PRINT_A, "en", "first") == f"{PRINT_A}:en:first"


def test_save_json_format(tmp_path):
    path = tmp_path / "sub" / "x.json"
    ygjson.save_json(path, {"b": "é", "a": [1]})
    assert path.read_text(encoding="utf-8") == '{\n "a": [\n  1\n ],\n "b": "é"\n}\n'


def test_valid_data_has_no_errors():
    assert errors() == []
    assert ygjson.validate(SETS, ERAS, CARDS, ARCHETYPES) == []


def test_the_committed_eras_and_formats_are_valid():
    eras, legality = ygjson.load_eras(), ygjson.load_legality()
    assert ygjson._check_eras(eras) == []
    assert ygjson._schema_errors("eras.schema.json", "eras.json", eras) == []
    assert {f["id"] for f in legality["formats"]} == {"tcg", "ocg", "speed_duel", "goat"}


def test_duplicate_ids_are_errors():
    sets = SETS + [SETS[0]]
    assert any("is listed 2 times" in e for e in errors(sets=sets))
    docs = edit(cards=lambda c: c["046"]["cards"].append(copy.deepcopy(CARD)))
    assert any("card 46986414 is listed 2 times" in e for e in errors(**docs))
    docs = edit(cards=lambda c: c["046"]["cards"][0]["prints"].append(copy.deepcopy(CARD["prints"][0])))
    assert any(f"print {PRINT_A} is listed twice" in e for e in errors(**docs))


@pytest.mark.parametrize("variant, treatment", [(None, False), ("blue", False), ("b", False), ("version-2", False),
                                                ("judge-stamp", True), ("extended-art", True), ("unlimited-misprint", True)])
def test_is_treatment(variant, treatment):
    assert ygjson.is_treatment({"variant": variant} if variant else {}) is treatment


def test_print_id_must_follow_the_rule():
    def rename(c):
        c["046"]["cards"][0]["prints"][0]["id"] = f"{SET}:46986414:LOB-EN006:ultra_rare"
    assert any("id must be" in e for e in errors(**edit(cards=rename)))


def test_rarity_outside_the_enum_is_a_schema_error():
    def bad(c):
        c["046"]["cards"][0]["prints"][1]["rarity"] = "mythic"
    assert any("'mythic' is not one of" in e for e in errors(**edit(cards=bad)))


def test_unknown_set_on_a_print_is_an_error():
    def bad(c):
        c["046"]["cards"][0]["prints"][0]["set"] = "nope"
        c["046"]["cards"][0]["prints"][0]["id"] = "nope:46986414:LOB-EN005:ultra_rare"
    assert any("set nope is not in sets.json" in e for e in errors(**edit(cards=bad)))


def test_set_parent_must_exist_and_not_loop():
    child = {**copy.deepcopy(SETS[0]), "id": "child", "tcgplayerGroupIds": [2], "parent": SET}
    sets = copy.deepcopy(SETS) + [child]
    assert errors(sets=sets) == []
    sets[0]["parent"] = "child"
    assert any("its own ancestor" in e for e in errors(sets=sets))
    sets[0]["parent"] = "nope"
    assert any("parent nope, which is not a set" in e for e in errors(sets=sets))


def test_set_era_must_exist_and_a_group_belongs_to_one_set():
    docs = edit(sets=lambda s: s[0].update(era="vrains"))
    assert any("era vrains" in e for e in errors(**docs))
    twin = {**copy.deepcopy(SETS[0]), "id": "twin"}
    assert any("TCGplayer group 1 is on" in e for e in errors(sets=SETS + [twin]))


def test_eras_must_not_overlap():
    eras = copy.deepcopy(ERAS)
    eras[0]["to"] = "2005-06-01"
    assert any("overlap" in e for e in errors(eras=eras))


def test_product_id_on_two_prints_or_a_print_and_a_product_is_an_error():
    def twice(c):
        c["046"]["cards"][0]["prints"][1]["identifiers"] = {"tcgplayerProductIds": [10]}
    assert any(f"TCGplayer product 10 is on {PRINT_A} and {PRINT_B}" in e for e in errors(**edit(cards=twice)))

    def clash(s):
        s[SET]["products"][0]["identifiers"]["tcgplayerProductIds"] = [10]
    assert any("TCGplayer product 10 is on" in e for e in errors(**edit(sealed=clash)))


def test_card_archetype_must_exist():
    docs = edit(archetypes=lambda a: a["archetypes"].clear())
    assert any("archetype dark-magician is not in archetypes.json" in e for e in errors(**docs))


def test_card_must_live_in_its_bucket():
    assert any("belongs in cards/046.json" in e for e in errors(cards={"047": CARDS["046"]}))


def test_empty_edition_lists_are_schema_errors():
    assert any("editions" in e for e in errors(**edit(sets=lambda s: s[0].update(editions=[]))))

    def empty(c):
        c["046"]["cards"][0]["prints"][1]["editions"] = []
    assert any("editions" in e for e in errors(**edit(cards=empty)))


def test_sealed_must_be_filed_under_its_set_and_reference_real_things():
    assert any("filed under other but its set is" in e for e in errors(sealed={"other": SEALED[SET]}))

    def bad(s):
        s[SET]["products"][0]["contents"] = {"cards": [{"print": "nope:1::common"}], "pool": [{"set": "nope"}],
                                             "sealed": [{"product": "ghost"}]}
    found = errors(**edit(sealed=bad))
    assert any("print nope:1::common, which does not exist" in e for e in found)
    assert any("pool set nope" in e for e in found)
    assert any("holds ghost" in e for e in found)


def test_complete_contents_need_counts():
    def bad(s):
        s[SET]["products"][0].update(contentsStatus="complete",
                                     contents={"cards": [{"print": PRINT_A}]})
    assert any("need a count" in e for e in errors(**edit(sealed=bad)))


def test_legality_event_for_a_missing_card_or_format_is_an_error():
    def card(lg):
        lg["events"][0]["card"] = "1"
    assert any("card 1, which does not exist" in e for e in errors(**edit(legality=card)))

    def fmt(lg):
        lg["events"][0]["format"] = "goat"
    assert any("format goat, which is not in formats.json" in e for e in errors(**edit(legality=fmt)))


def test_legality_event_needs_a_date():
    def bad(lg):
        del lg["events"][0]["effective"]
    assert errors(**edit(legality=bad))


def test_schema_errors_come_first_and_skip_the_cross_checks():
    def bad(c):
        c["046"]["cards"][0]["colour"] = "dark"
        c["046"]["cards"][0]["prints"][0]["set"] = "nope"
    found = errors(**edit(cards=bad))
    assert found and all(e.startswith("cards/046.json") for e in found)


def test_flatten_makes_a_printing_per_print_and_edition():
    out = ygjson.flatten(SETS, CARDS, ARCHETYPES, SEALED)
    assert set(out) == {"sets", "cards", "printings", "archetypes", "products"}
    assert out["cards"]["46986414"]["prints"] == [PRINT_A, PRINT_B]
    assert sorted(out["printings"]) == sorted([
        f"{PRINT_A}:en:first", f"{PRINT_A}:en:unlimited", f"{PRINT_B}:en:unlimited"])  # B overrides the set's editions
    first = out["printings"][f"{PRINT_A}:en:first"]
    assert first == {"id": f"{PRINT_A}:en:first", "print": PRINT_A, "card": "46986414", "set": SET,
                     "number": "LOB-EN005", "region": "EN", "rarity": "ultra_rare", "rarityTier": 4, "language": "en",
                     "edition": "first", "finish": "foil", "identifiers": {"tcgplayerProductIds": [10]},
                     "tcgplayerPrice": {"productId": 10, "subTypeName": "1st Edition"}}
    assert out["printings"][f"{PRINT_A}:en:unlimited"]["tcgplayerPrice"] == {"productId": 10, "subTypeName": "Unlimited"}
    common = out["printings"][f"{PRINT_B}:en:unlimited"]
    assert common["finish"] == "nonfoil" and common["rarityTier"] == 1 and common["identifiers"] == {}
    assert "tcgplayerPrice" not in common  # no product


def _two_products(edition_products):
    cards = copy.deepcopy(CARDS)
    p = cards["046"]["cards"][0]["prints"][0]
    p["identifiers"] = {"tcgplayerProductIds": [10, 11]}
    p["tcgplayer"] = {"name": "Dark Magician", "match": "number+rarity", "editionProducts": edition_products}
    return cards


def test_a_printing_of_a_print_with_two_products_is_priced_by_the_one_its_edition_names():
    printings = ygjson.flatten(SETS, _two_products({"first": 11}), ARCHETYPES)["printings"]
    first, unlimited = printings[f"{PRINT_A}:en:first"], printings[f"{PRINT_A}:en:unlimited"]
    assert first["tcgplayerPrice"] == {"productId": 11, "subTypeName": "1st Edition"}
    assert "tcgplayerPrice" not in unlimited  # neither product prices it
    assert first["tcgplayer"] == {"name": "Dark Magician", "match": "number+rarity"}  # the map stays in the data


def test_a_printing_links_the_scan_of_its_edition():
    cards = copy.deepcopy(CARDS)
    cards["046"]["cards"][0]["prints"][0]["scans"] = {"first": "https://ms.yugipedia.com/a.png"}
    assert errors(cards=cards) == []
    printings = ygjson.flatten(SETS, cards, ARCHETYPES)["printings"]
    assert printings[f"{PRINT_A}:en:first"]["scan"] == "https://ms.yugipedia.com/a.png"
    assert "scan" not in printings[f"{PRINT_A}:en:unlimited"]


def test_edition_products_must_name_the_prints_own_products_and_editions():
    assert errors(cards=_two_products({"first": 11, "unlimited": 10})) == []
    assert errors(cards=_two_products({"first": 12})) == [
        f"print {PRINT_A}: editionProducts names first 12, which is not one of its products and editions"]
    assert len(errors(cards=_two_products({"limited": 10}))) == 1


def test_flatten_unknown_rarity_has_no_finish_or_tier():
    cards = copy.deepcopy(CARDS)
    cards["046"]["cards"][0]["prints"] = [{"id": f"{SET}:46986414::unknown", "set": SET, "rarity": "unknown",
                                           "rawRarity": "New"}]
    printing = ygjson.flatten(SETS, cards, ARCHETYPES)["printings"][f"{SET}:46986414::unknown:en:first"]
    assert printing["finish"] is None and "rarityTier" not in printing and "number" not in printing


def test_flatten_archetype_members_and_products():
    other = copy.deepcopy(CARD)
    other.update(id="4007", passcode=4007, prints=[], identifiers={"ygoprodeckId": 4007})
    cards = {"000": {"cards": [other]}, "046": CARDS["046"]}
    out = ygjson.flatten(SETS, cards, ARCHETYPES, SEALED)
    assert out["archetypes"]["dark-magician"]["members"] == ["4007", "46986414"]
    assert out["products"]["lob-booster-pack"]["set"] == SET
    assert ygjson.flatten(SETS, CARDS, ARCHETYPES)["products"] == {}


def _ledger_for(sealed=SEALED, cards=CARDS):
    import ids
    return ids.run({k: {} for k in ids.KINDS}, SETS, cards, ARCHETYPES, sealed, ({}, {}), {})[0]


def test_flatten_with_a_ledger_uses_print_uuids():
    before = copy.deepcopy(CARDS)
    ledger = _ledger_for()
    uuids = {e["key"]: e["id"] for e in ledger["prints"].values()}
    out = ygjson.flatten(SETS, CARDS, ARCHETYPES, SEALED, ledger=ledger)
    assert CARDS == before
    assert out["cards"]["46986414"]["prints"] == [uuids[PRINT_A], uuids[PRINT_B]]
    pid = f"{uuids[PRINT_A]}:en:first"
    assert sorted(out["printings"]) == sorted([
        pid, f"{uuids[PRINT_A]}:en:unlimited", f"{uuids[PRINT_B]}:en:unlimited"])
    rec = out["printings"][pid]
    assert rec["id"] == pid and rec["print"] == uuids[PRINT_A]
    assert rec["key"] == f"{PRINT_A}:en:first" and rec["printKey"] == PRINT_A
    old = ygjson.flatten(SETS, CARDS, ARCHETYPES, SEALED)["printings"][f"{PRINT_A}:en:first"]
    assert {k: v for k, v in rec.items() if k not in ("id", "key", "print", "printKey")} == \
        {k: v for k, v in old.items() if k not in ("id", "print")}


def test_flatten_sealed_contents_point_at_print_uuids():
    sealed = copy.deepcopy(SEALED)
    sealed[SET]["products"][0]["contents"]["cards"] = [{"print": PRINT_A, "count": 1}]
    before = copy.deepcopy(sealed)
    ledger = _ledger_for(sealed)
    out = ygjson.flatten(SETS, CARDS, ARCHETYPES, sealed, ledger=ledger)
    assert sealed == before
    got = out["products"]["lob-booster-pack"]["contents"]["cards"]
    assert got == [{"print": ledger["prints"][got[0]["print"]]["id"], "count": 1}]
    assert ledger["prints"][got[0]["print"]]["key"] == PRINT_A


# --- tighter schemas (#17) ----------------------------------------------------------------------------------------

def _print(cards, **fields):
    cards["046"]["cards"][0]["prints"][0].update(fields)


@pytest.mark.parametrize("change, where", [
    (dict(cards=lambda c: _print(c, tcgplayer={"name": "Dark Magician", "match": "number+rarity "})), "cards/046.json"),
    (dict(cards=lambda c: c["046"]["cards"][0]["names"].update({"xx": "?"})), "cards/046.json"),
    (dict(cards=lambda c: c["046"]["cards"][0].update(linkArrows=["Up"])), "cards/046.json"),
    (dict(cards=lambda c: _print(c, rarity="unknown", id=f"{SET}:46986414:LOB-EN005:unknown")), "cards/046.json"),
    (dict(archetypes=lambda a: a["archetypes"][0].update(names={"en": "Dark Magician", "jp": "?"})), "archetypes.json"),
    (dict(sets=lambda s: s[0].update(parent="Not A Slug")), "sets.json"),
    (dict(sets=lambda s: s[0].update(era="Duel Monsters")), "sets.json"),
    (dict(sealed=lambda s: s[SET]["products"][0].update(category="accessory")), f"sealed/{SET}.json"),
    (dict(sealed=lambda s: s[SET]["products"][0]["contents"].update(pool=[{"set": "LOB"}])), f"sealed/{SET}.json"),
    (dict(sealed=lambda s: s[SET]["products"][0]["contents"].update(cards=[{"print": "Dark Magician"}])),
     f"sealed/{SET}.json"),
    (dict(sealed=lambda s: s[SET]["products"][0]["contents"].update(sealed=[{"product": "LOB Box"}])),
     f"sealed/{SET}.json"),
    (dict(legality=lambda g: g["formats"].append({"id": "edison", "name": "Edison", "source": "https://x"})),
     "formats.json"),
])
def test_a_value_outside_the_tighter_schemas_is_a_schema_error(change, where):
    found = errors(**edit(**change))
    assert found and all(e.startswith(f"{where}: ") for e in found), found


def test_an_unknown_rarity_with_its_raw_string_is_valid():
    def unknown(c):
        _print(c, rarity="unknown", rawRarity="New", id=f"{SET}:46986414:LOB-EN005:unknown")
    assert errors(**edit(cards=unknown)) == []


def test_an_archetype_name_must_be_its_english_name():
    docs = edit(archetypes=lambda a: a["archetypes"][0].update(names={"en": "dark magician"}))
    assert errors(**docs) == ["archetypes.json: archetype dark-magician: name 'Dark Magician' is not names.en "
                              "'dark magician'"]


def test_a_set_s_era_must_hold_its_release_date():
    assert errors(**edit(sets=lambda s: s[0].update(era="gx"))) == [
        f"sets.json: set {SET} has era gx, but its release date 2002-03-08 is in dm"]


def test_a_set_without_a_date_takes_its_parent_s_era():
    child = {**copy.deepcopy(SETS[0]), "id": "lob-promo", "name": "LOB Promo", "parent": SET, "era": "gx",
             "releases": [{"language": "en", "name": "LOB Promo"}], "tcgplayerGroupIds": []}
    assert errors(**edit(sets=lambda s: s.append(child))) == [
        "sets.json: set lob-promo has era gx, but its parent's is dm"]
    child["era"] = "dm"
    assert errors(**edit(sets=lambda s: s.append(child))) == []


@pytest.mark.parametrize("change, label", [
    (dict(sets=lambda s: s[0].update(name="Legend of Blue Eyes  White Dragon")), f"sets.json: set {SET}"),
    (dict(cards=lambda c: c["046"]["cards"][0]["names"].update(es="Mago Oscuro ")), "card 46986414 (es)"),
    (dict(archetypes=lambda a: a["archetypes"][0].update(name=" Dark Magician")), "archetypes.json: archetype dark-magician"),
    (dict(sealed=lambda s: s[SET]["products"][0].update(name="LOB\tBooster Pack")), f"sealed/{SET}.json: lob-booster-pack"),
])
def test_a_name_with_a_stray_space_is_an_error(change, label):
    found = errors(**edit(**change))
    assert any(e.startswith(label) and "leading, trailing or doubled space" in e for e in found), found


def test_a_japanese_name_keeps_its_ideographic_spaces():
    name = "ユベル－Ｄａｓ　Ａｂｓｃｈｅｕｌｉｃｈ　Ｒｉｔｔｅｒ"
    assert ygjson.clean_name(name) == name
    assert errors(**edit(cards=lambda c: c["046"]["cards"][0]["names"].update(ja=name))) == []


@pytest.mark.parametrize("raw, clean", [
    ("Crossover Breakers  - Booster Pack", "Crossover Breakers - Booster Pack"),
    (" Mago Oscuro \n", "Mago Oscuro"),
])
def test_clean_name(raw, clean):
    assert ygjson.clean_name(raw) == clean


def test_clean_archetype_name_drops_a_leaked_template_key():
    assert ygjson.clean_archetype_name("| supports_archetypes    Power Patron") == "Power Patron"
    assert ygjson.clean_archetype_name("Power Patron") == "Power Patron"
    assert ygjson.clean_archetype_name('"C"') == '"C"'


@pytest.mark.parametrize("a, b", [
    ("Magician&apos;s Force", "Magician’s Force"),
    ("Magician's  Force", "magician's force"),
    ("Yu-Gi-Oh! 5D's", "yu gi oh 5d s"),
    ("  Dark Crisis ", "Dark Crisis"),
])
def test_normalise_unifies_case_apostrophes_and_punctuation(a, b):
    assert ygjson.normalise(a) == ygjson.normalise(b)


def test_normalise_keeps_different_words_apart():
    assert ygjson.normalise("Dark Crisis") != ygjson.normalise("Dark Crisis 2")


def test_fold_name_folds_case_apostrophes_and_spaces_but_keeps_punctuation():
    assert ygjson.fold_name("  Magician’s   FORCE ") == "magician's force"
    assert ygjson.fold_name("Yu-Gi-Oh! 5D's") != ygjson.fold_name("Yu Gi Oh 5D's")
