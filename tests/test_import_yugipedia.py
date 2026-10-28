import copy

import pytest

import import_yugipedia as imp
import ygjson

ERAS = [
    {"code": "dm", "name": "DM", "mechanic": "none", "from": "2002-03-08", "to": "2005-05-31"},
    {"code": "gx", "name": "GX", "mechanic": "none", "from": "2005-06-01"},
]
MAPPING = imp.load_mapping()


def our_set(set_id, name, code, kind="booster", **over):
    s = {"id": set_id, "code": code, "name": name, "type": kind, "editions": ["unlimited"], "source": "ygoprodeck",
         "releases": [{"language": "en", "name": name}]}
    s.update(over)
    return s


def page(pageid, title, infobox_text):
    return {"pageid": pageid, "title": title,
            "revisions": [{"slots": {"main": {"content": "{{Infobox set\n" + infobox_text + "\n}}"}}}]}


def ib(**kw):
    return {k.replace("__", "/"): v for k, v in kw.items()}


# --- type mapping --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("infobox, name, expected", [
    ({"type": "Booster pack"}, "Dark Crisis", "booster"),
    ({"type": "Collectible Tin"}, "2008 Collectible Tin", "tin"),
    ({"type": "Magazine promotional card"}, "Shonen Jump Vol. 1", "promo"),
    ({"type": "Tournament pack"}, "OTS Tournament Pack 1", "promo"),
    ({"type": "Preconstructed deck"}, "Some Deck", "starter_deck"),
    ({"type": "Advent calendar"}, "Yu-Gi-Oh! Advent Calendar", "box_set"),
    ({"type": "Booster pack", "series": "Core Booster"}, "Dark Crisis", "booster"),
    ({"type": "Collector's set", "series": "Legendary Duelists (series)"}, "Legendary Duelists", "booster"),
    ({"type": "Collector's set", "series": "60 Card Set"}, "Dark Saviors", "box_set"),
    ({"type": "Tournament pack", "series": "Speed Duel Tournament Pack"}, "Speed Pack", "speed_duel"),
    ({"type": "Booster pack", "series": "speed duel gx"}, "Speed Duel GX", "speed_duel"),
    ({"type": "Participation card", "series": "Sneak Peek Participation Cards"}, "X", "sneak_peek"),
    ({"type": "Tournament pack", "series": "Champion Pack"}, "Champion Pack: Game One", "promo"),
])
def test_map_type(infobox, name, expected):
    assert imp.map_type(infobox, name, MAPPING) == expected


def test_sneak_peek_name_rule_needs_a_participation_card():
    assert imp.map_type({"type": "Participation card"}, "Cyberdark Impact Sneak Peek Participation Card", MAPPING) == "sneak_peek"
    assert imp.map_type({"type": "Participation card"}, "Hobby League 3", MAPPING) == "promo"
    assert imp.map_type({"type": "Booster pack"}, "Sneak Peek Booster", MAPPING) == "booster"


def test_special_edition_name_rule_beats_the_infobox_type():
    assert imp.map_type({"type": "Booster pack"}, "Clash of Rebellions: Special Edition", MAPPING) == "special_edition"
    assert imp.map_type({"type": "Booster pack"}, "Special Edition Fans", MAPPING) == "booster"


def test_unmapped_type_is_none():
    assert imp.map_type({"type": ""}, "X", MAPPING) is None
    assert imp.map_type({"type": "Mystery"}, "X", MAPPING) is None
    assert imp.map_type({}, "X", MAPPING) is None


def test_every_mapped_type_is_a_schema_type():
    allowed = set(ygjson._schema("sets.schema.json").schema["items"]["properties"]["type"]["enum"])
    assert set(MAPPING["types"].values()) <= allowed and set(MAPPING["series"].values()) <= allowed


# --- fields --------------------------------------------------------------------------------------------------

def test_database_ids_take_every_key_and_skip_blanks():
    got = imp.database_ids(ib(en_database_id="11101000", database_id="5", ja_database_id="", fr_database_id="31; 32",
                              ko_database_id="n/a", ae_database_id="5000000003000", cover_card="1"))
    assert got == [5, 31, 32, 11101000, 5000000003000]


def test_release_date_prefers_na_then_en_then_plain_then_earliest():
    assert imp.release_date(ib(na_release_date="March 8, 2002", en_release_date="December 1, 2004")) == "2002-03-08"
    assert imp.release_date(ib(na_release_date="", en_release_date="December 1, 2004", eu_release_date="May 1, 2000")) == "2004-12-01"
    assert imp.release_date(ib(release_date="June 2003", jp_release_date="May 1, 2000")) == "2003-06-01"
    assert imp.release_date(ib(jp_release_date="May 1, 2001", eu_release_date="March 2000", fr__de__it__sp_release_date="")) == "2000-03-01"
    assert imp.release_date(ib(na_release_date="2023")) is None
    assert imp.release_date({}) is None


def test_prefix_code_takes_the_part_before_the_hyphen():
    assert imp.prefix_code(ib(prefix="SD1")) == "SD1"
    assert imp.prefix_code(ib(en_prefix="LOB-EN")) == "LOB"
    assert imp.prefix_code(ib(prefix="", en_prefix="LOB-EN; LOB")) == "LOB"
    assert imp.prefix_code({}) is None


def apply(s, infobox, by_title=False, title="Page Title", pageid=9):
    stats, unmapped = imp.collections.Counter(), []
    imp.apply_infobox(s, infobox, {"pageid": pageid, "title": title}, by_title, MAPPING, ERAS, stats, unmapped)
    return stats, unmapped


def test_apply_infobox_fills_what_is_missing_and_keeps_what_exists():
    s = our_set("a", "Dark Crisis", "DCR", identifiers={"konamiDatabaseIds": [7], "ygojsonId": "u"})
    s["releases"][0]["releaseDate"] = "2010-01-01"
    stats, unmapped = apply(s, ib(type="Booster pack", series="Core Booster", image="DCR-Booster EN.png", en_database_id="8",
                                  na_release_date="March 8, 2002"), by_title=True, title="Dark Crisis")
    assert s["series"] == "Core Booster"
    assert s["identifiers"] == {"konamiDatabaseIds": [7, 8], "ygojsonId": "u", "yugipediaId": 9}
    assert s["releases"][0]["releaseDate"] == "2010-01-01"  # YGOPRODeck's date stands
    assert s["releases"][0]["keyArt"] == {"url": "https://yugipedia.com/wiki/Special:FilePath/DCR-Booster_EN.png",
                                          "source": "https://yugipedia.com/wiki/Dark_Crisis"}
    assert stats["keyArt"] == 1 and stats["dates"] == 0 and not unmapped


def test_apply_infobox_fills_date_and_era_when_the_set_has_none():
    s = our_set("a", "Old", "OLD")
    stats, _ = apply(s, ib(type="Booster pack", na_release_date="March 8, 2002"))
    assert s["releases"][0]["releaseDate"] == "2002-03-08" and s["era"] == "dm" and stats["dates"] == 1
    assert "yugipediaId" not in s.get("identifiers", {})


def test_apply_infobox_does_not_overwrite_art_or_create_empty_identifiers():
    s = our_set("a", "X", "X")
    s["releases"][0]["keyArt"] = {"url": "https://example.com/a.jpg", "source": "https://example.com"}
    apply(s, ib(type="Tin", image="Foo.png"))
    assert s["releases"][0]["keyArt"]["url"] == "https://example.com/a.jpg"
    assert "identifiers" not in s and s["type"] == "tin" and "series" not in s


def test_apply_infobox_fills_unknown_code_only():
    s = our_set("a", "X", "UNKNOWN")
    stats, _ = apply(s, ib(type="Tin", en_prefix="ABC-EN"))
    assert s["code"] == "ABC" and stats["codes"] == 1
    t = our_set("b", "Y", "KEEP")
    apply(t, ib(type="Tin", prefix="ABC"))
    assert t["code"] == "KEEP"


def test_apply_infobox_unmapped_type_keeps_current_type_and_reviews():
    s = our_set("a", "Elemental Hero Collection 1", "EHC", kind="box_set")
    _, unmapped = apply(s, ib(type="", series=""))
    assert s["type"] == "box_set"
    assert unmapped == [{"id": "a", "name": "Elemental Hero Collection 1", "type": "", "series": ""}]


# --- parents -------------------------------------------------------------------------------------------------

def parents(sets, boxes=None):
    found, ambiguous = imp.find_parents(sets, boxes or {})
    return {k: v for k, v in found.items()}, ambiguous


def test_parent_by_code():
    sets = [our_set("dcr", "Dark Crisis", "DCR"), our_set("dcr-se", "Crisis Reprint", "DCR", "special_edition"),
            our_set("other", "Other", "OTH")]
    assert parents(sets)[0] == {"dcr-se": ("dcr", "code")}


def test_parent_by_name_prefix_for_each_child_kind():
    sets = [our_set("coR", "Clash of Rebellions", "CORE"),
            our_set("coR-se", "Clash of Rebellions: Special Edition", "CORS", "special_edition"),
            our_set("abyss", "Abyss Rising", "ABYR"),
            our_set("abyss-sp", "Abyss Rising Sneak Peek Participation Card", "ABYS", "sneak_peek"),
            our_set("bv", "Blazing Vortex", "BLVO"),
            our_set("bv-pr", "Blazing Vortex Premiere! promotional card", "BLVP", "promo")]
    assert parents(sets)[0] == {"coR-se": ("coR", "name"), "abyss-sp": ("abyss", "name"), "bv-pr": ("bv", "name")}


def test_parent_name_prefix_stops_at_a_word_boundary():
    sets = [our_set("a", "Dark", "D1"), our_set("b", "Dark Crisis", "D2"),
            our_set("c", "Dark Crisisx Special Edition", "D3", "special_edition")]
    assert parents(sets)[0] == {"c": ("a", "name")}  # "Dark" ends at a space, "Dark Crisis" would end mid-word


def test_parent_name_prefix_prefers_the_longest_booster():
    sets = [our_set("a", "Dark", "D1"), our_set("b", "Dark Crisis", "D2"),
            our_set("d", "Dark Crisis Sneak Peek Participation Card", "D4", "sneak_peek")]
    assert parents(sets)[0] == {"d": ("b", "name")}


def test_parent_by_other_sets_in_the_child_and_in_the_booster():
    sets = [our_set("lob", "Legend of Blue Eyes White Dragon", "LOB"),
            our_set("tcg", "Legend X promotional cards", "ZZ1", "promo"),
            our_set("kid", "Kids' Promo", "KP", "special_edition"),
            our_set("rs", "Rise Set", "RS")]
    boxes = {"tcg": {"other_sets": "''Legend of Blue Eyes White Dragon''"},
             "rs": {"other_sets": "Kids' Promo"}}
    found, _ = parents(sets, boxes)
    assert found == {"tcg": ("lob", "other_sets"), "kid": ("rs", "other_sets")}


def test_parent_evidence_is_joined_when_several_agree():
    sets = [our_set("dcr", "Dark Crisis", "DCR"), our_set("dcr-se", "Dark Crisis: Special Edition", "DCR", "special_edition")]
    assert parents(sets)[0] == {"dcr-se": ("dcr", "code+name")}


def test_two_boosters_are_ambiguous_and_reviewed():
    sets = [our_set("a", "Dark Crisis", "DCR"), our_set("b", "Other Pack", "DCR"),
            our_set("c", "Dark Crisis: Special Edition", "DCR", "special_edition")]
    found, ambiguous = parents(sets)
    assert found == {} and ambiguous == {"c": ["a", "b"]}


def test_promo_without_a_premiere_or_promotional_name_gets_no_parent():
    sets = [our_set("a", "Dark Crisis", "DCR"), our_set("p", "Dark Crisis Prize", "DCR", "promo"),
            our_set("q", "Dark Crisis Promotional Cards", "DCR", "promo")]
    assert parents(sets)[0] == {"q": ("a", "code+name")}


def test_parent_not_itself_and_existing_parent_kept():
    sets = [our_set("a", "Dark Crisis", "DCR", "special_edition"),
            our_set("b", "Dark Crisis Special Edition", "DCR", "special_edition", parent="zzz")]
    assert parents(sets)[0] == {}


def test_era_is_inherited_from_the_parent_chain():
    sets = [our_set("a", "A", "A", era="gx"), our_set("b", "B", "B", "special_edition", parent="a"),
            our_set("c", "C", "C", "promo", parent="b"), our_set("d", "D", "D", era="dm", parent="a")]
    assert imp.inherit_eras(sets) == 2
    assert [s.get("era") for s in sets] == ["gx", "gx", "gx", "dm"]


# --- build ---------------------------------------------------------------------------------------------------

def test_build_end_to_end_is_idempotent_and_reviews():
    sets = [our_set("dcr", "Dark Crisis", "DCR", identifiers={"yugipediaId": 1}),
            our_set("dcr-se", "Dark Crisis: Special Edition", "DCRS", identifiers={"yugipediaId": 2}),
            our_set("alias", "Dark Crisis Alias", "DCA"),
            our_set("gone", "Gone", "GON", identifiers={"yugipediaId": 4}),
            our_set("blank", "Blank", "BLK", kind="tin", identifiers={"yugipediaId": 5}),
            our_set("nobox", "No Box", "NBX", identifiers={"yugipediaId": 6})]
    pages = {
        "dcr": (page(1, "Dark Crisis", "| type = [[Booster pack]]\n| na_release_date = June 6, 2005\n| en_database_id = 9"), False),
        "dcr-se": (page(2, "Dark Crisis: Special Edition", "| type = [[Booster pack]]\n| series = Core Booster"), False),
        "alias": (page(1, "Dark Crisis", "| type = [[Booster pack]]"), True),
        "blank": (page(5, "Blank", "| type =\n"), False),
        "nobox": ({"pageid": 6, "title": "No Box", "revisions": [{"slots": {"main": {"content": "text only"}}}]}, False),
    }
    review, stats, evidence = imp.build(sets, pages, ERAS, MAPPING)
    by_id = {s["id"]: s for s in sets}
    assert by_id["dcr-se"]["type"] == "special_edition" and by_id["dcr-se"]["parent"] == "dcr"
    assert by_id["dcr-se"]["era"] == "gx" and by_id["dcr"]["identifiers"]["konamiDatabaseIds"] == [9]
    assert by_id["blank"]["type"] == "tin"
    assert "yugipediaId" not in by_id["alias"].get("identifiers", {})  # page 1 belongs to dcr
    assert review["noPage"] == [{"id": "gone", "name": "Gone"}]
    assert review["noInfobox"] == [{"id": "nobox", "name": "No Box"}]
    assert review["unmappedType"] == [{"id": "blank", "name": "Blank", "type": "", "series": ""}]
    assert review["sharedPage"] == [{"id": "alias", "name": "Dark Crisis Alias", "page": "Dark Crisis", "pageid": 1,
                                     "ownedBy": "dcr"}]
    assert stats["parents"] == 1 and evidence == {"name": 1}
    again = copy.deepcopy(sets)
    imp.build(again, pages, ERAS, MAPPING)
    assert again == sets


def test_built_sets_validate():
    sets = [our_set("dcr", "Dark Crisis", "DCR"), our_set("dcr-se", "Dark Crisis: Special Edition", "DCRS")]
    pages = {"dcr": (page(1, "Dark Crisis", "| type = Booster pack\n| image = A b.png\n| na_release_date = June 6, 2005"), True),
             "dcr-se": (page(2, "Dark Crisis: Special Edition", "| type = Booster pack\n| series = Core Booster"), True)}
    imp.build(sets, pages, ERAS, MAPPING)
    errors = ygjson.validate(sets, ERAS, {}, {"archetypes": []})
    assert errors == []
