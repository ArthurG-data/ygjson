import collections

import pytest

import import_ygoprodeck as imp
import ygjson

ERAS = [{"code": "dm", "name": "Duel Monsters", "mechanic": "Fusion", "from": "2002-03-08", "to": "2005-05-31"},
        {"code": "gx", "name": "GX", "mechanic": "Fusion", "from": "2005-06-01"}]
LOB = "Legend of Blue Eyes White Dragon"
LOB_ID = "legend-of-blue-eyes-white-dragon"


def raw_card(**over):
    card = {"id": 46986414, "name": "Dark Magician", "type": "Normal Monster", "frameType": "normal",
            "race": "Spellcaster", "attribute": "DARK", "level": 7, "atk": 2500, "def": 2100,
            "typeline": ["Spellcaster", "Normal"], "misc_info": [{"konami_id": 4041, "has_effect": 0,
                                                                 "tcg_date": "2002-03-08"}],
            "card_images": [{"id": 46986414, "image_url": "https://x/c.jpg", "image_url_small": "https://x/s.jpg",
                             "image_url_cropped": "https://x/a.jpg"}],
            "card_sets": [{"set_name": LOB, "set_code": "LOB-EN005", "set_rarity": "Ultra Rare"}]}
    card.update(over)
    return card


@pytest.mark.parametrize("name, kind", [
    ("Structure Deck: Dragunity Legion", "structure_deck"),
    ("Starter Deck: Kaiba", "starter_deck"),
    ("Yugi's Starter", "starter_deck"),
    ("2014 Mega-Tins", "tin"),
    ("2013 Collectible Tins Wave 1", "tin"),
    ("Absolute Powerforce: Special Edition", "special_edition"),
    ("Crossed Souls: Advance Edition", "special_edition"),
    ("Premiere Sneak Peek Participation Card", "sneak_peek"),
    ("Duel Terminal 7a", "duel_terminal"),
    ("Speed Duel: Battle City Box", "speed_duel"),
    ("Yu-Gi-Oh! 5D's Tag Force 5 Promotional Cards", "promo"),
    ("Shonen Jump Championship Prize Card", "promo"),
    ("Legendary Collection", "box_set"),
    ("Duelist Pack Mega Pack", "box_set"),
    ("Destiny Soldier", "booster"),  # "tin" inside a word is not a tin
    (LOB, "booster"),
])
def test_set_type_rules(name, kind):
    assert imp.set_type(name) == kind


def test_editions_placeholder():
    assert imp.set_editions("Limited Edition 1") == ["limited"]
    assert imp.set_editions(LOB) == ["unlimited"]


def test_era_of():
    assert imp.era_of("2002-03-08", ERAS) == "dm"
    assert imp.era_of("2024-01-01", ERAS) == "gx"
    assert imp.era_of("2001-01-01", ERAS) is None
    assert imp.era_of(None, ERAS) is None


def test_card_kind_level_and_rank():
    card = imp.card_entry(raw_card())
    assert (card["kind"], card["level"], card["attribute"], card["passcode"], card["isTuner"]) == ("monster", 7, "dark", 46986414, False)
    assert card["identifiers"] == {"ygoprodeckId": 46986414, "konamiId": 4041}
    assert card["tcgDate"] == "2002-03-08" and card["hasEffect"] is False
    assert card["images"] == [{"id": 46986414, "card": "https://x/c.jpg", "small": "https://x/s.jpg", "art": "https://x/a.jpg"}]

    xyz = imp.card_entry(raw_card(type="XYZ Monster", frameType="xyz", level=4))
    assert xyz["rank"] == 4 and "level" not in xyz
    xyz_p = imp.card_entry(raw_card(type="XYZ Pendulum Effect Monster", frameType="xyz_pendulum", level=3, scale=2))
    assert xyz_p["rank"] == 3 and xyz_p["scale"] == 2

    link = imp.card_entry(raw_card(type="Link Monster", frameType="link", level=None, linkval=2, linkmarkers=["Top"], **{"def": None}))
    assert link["linkRating"] == 2 and link["linkArrows"] == ["Top"] and "level" not in link and "def" not in link

    assert imp.card_entry(raw_card(type="Spell Card", frameType="spell"))["kind"] == "spell"
    assert imp.card_entry(raw_card(type="Trap Card", frameType="trap"))["kind"] == "trap"
    assert imp.card_entry(raw_card(type="Token", frameType="token"))["kind"] == "token"
    assert imp.card_entry(raw_card(type="Skill Card", frameType="skill"))["kind"] == "skill"
    assert imp.card_entry(raw_card(type="Tuner Monster"))["isTuner"] is True


def test_no_passcode_above_100_million_and_unknown_atk_is_absent():
    card = imp.card_entry(raw_card(id=149694341, atk=-1, **{"def": -1}))
    assert "passcode" not in card and "atk" not in card and "def" not in card
    assert imp.card_entry(raw_card(atk=0))["atk"] == 0


def test_empty_typeline_token_is_dropped():
    assert "typeline" not in imp.card_entry(raw_card(typeline=[""]))


def test_duplicate_print_rows_are_skipped_and_counted():
    rows = [{"set_name": LOB, "set_code": "LOB-EN005", "set_rarity": "Ultra Rare"},
            {"set_name": LOB, "set_code": "LOB-EN005", "set_rarity": "Ultra Rare"},
            {"set_name": LOB, "set_code": "LOB-EN005", "set_rarity": "Starfoil"},
            {"set_name": LOB, "set_code": "LOB-EN005", "set_rarity": "Starfoil Rare"}]
    prints, duplicates, unknown = imp.build_prints(raw_card(card_sets=rows), {LOB: LOB_ID})
    assert duplicates == 2 and unknown == []
    assert [p["rarity"] for p in prints] == ["starfoil_rare", "ultra_rare"]
    assert prints[1] == {"id": f"{LOB_ID}:46986414:LOB-EN005:ultra_rare", "set": LOB_ID, "number": "LOB-EN005",
                         "region": "EN", "rarity": "ultra_rare"}


def test_unknown_rarity_keeps_the_raw_string():
    rows = [{"set_name": LOB, "set_code": "LOB-001", "set_rarity": "New"}]
    (p,), duplicates, unknown = imp.build_prints(raw_card(card_sets=rows), {LOB: LOB_ID})
    assert p["rarity"] == "unknown" and p["rawRarity"] == "New" and "region" not in p
    assert p["id"] == f"{LOB_ID}:46986414:LOB-001:unknown" and unknown == ["New"]
    assert imp.review_body(collections.Counter(["New", "New", "2"]), 3) == {
        "unknown": [{"rarity": "New", "prints": 2}, {"rarity": "2", "prints": 1}], "duplicateRows": 3}


def test_a_placeholder_set_number_is_no_number():
    rows = [{"set_name": LOB, "set_code": "MF03-EN0??", "set_rarity": "Common"}]
    (p,), _, _ = imp.build_prints(raw_card(card_sets=rows), {LOB: LOB_ID})
    assert "number" not in p and p["id"] == f"{LOB_ID}:46986414::common"


def test_sets_code_dates_art_and_slug_collisions():
    cards = [raw_card(card_sets=[
        {"set_name": LOB, "set_code": "LOB-EN005", "set_rarity": "Common"},
        {"set_name": "Unlisted Set", "set_code": "UNL-EN001", "set_rarity": "Common"},
        {"set_name": "Unlisted Set", "set_code": "UNL-EN002", "set_rarity": "Common"},
        {"set_name": "Tag Force 5 Promotional Cards", "set_code": "TF05-EN001", "set_rarity": "Common"},
        {"set_name": "Tag Force 5 promotional cards", "set_code": "TF05-EN002", "set_rarity": "Common"}])]
    listed = [{"set_name": LOB, "set_code": "LOB", "tcg_date": "2002-03-08", "set_image": "https://x/LOB.jpg"},
              {"set_name": "Listed Only", "set_code": "LO"}]
    sets, ids = imp.build_sets(cards, listed, ERAS, [])
    by_id = {s["id"]: s for s in sets}
    assert [s["id"] for s in sets] == sorted(by_id) and len(sets) == 5
    lob = by_id[LOB_ID]
    assert (lob["code"], lob["era"], lob["type"], lob["editions"], lob["source"]) == ("LOB", "dm", "booster", ["unlimited"], "ygoprodeck")
    assert lob["releases"] == [{"language": "en", "name": LOB, "releaseDate": "2002-03-08",
                                "keyArt": {"url": "https://x/LOB.jpg", "source": "https://ygoprodeck.com/sets/LOB"}}]
    assert by_id["unlisted-set"]["code"] == "UNL" and "era" not in by_id["unlisted-set"]
    assert "keyArt" not in by_id["listed-only"]["releases"][0]
    assert ids["Tag Force 5 Promotional Cards"] == "tag-force-5-promotional-cards"
    assert ids["Tag Force 5 promotional cards"] == "tag-force-5-promotional-cards-2"
    assert imp.collisions(ids) == {"tag-force-5-promotional-cards": ["Tag Force 5 Promotional Cards", "Tag Force 5 promotional cards"]}


def test_rerun_keeps_what_later_tools_added_to_a_set():
    listed = [{"set_name": LOB, "set_code": "LOB", "tcg_date": "2002-03-08"}]
    first, _ = imp.build_sets([raw_card()], listed, ERAS, [])
    first[0].update({"identifiers": {"ygojsonId": "abc"}, "type": "special_edition", "editions": ["first", "unlimited"],
                     "parent": "p", "series": "Core Booster", "tcgplayerGroupIds": [7], "code": "STALE"})
    first[0]["releases"][0]["keyArt"] = {"url": "https://y/a.jpg", "source": "https://y"}
    second, _ = imp.build_sets([raw_card()], listed, ERAS, first)
    s = second[0]
    assert s["identifiers"] == {"ygojsonId": "abc"} and s["type"] == "special_edition"
    assert s["editions"] == ["first", "unlimited"] and s["parent"] == "p" and s["series"] == "Core Booster"
    assert s["tcgplayerGroupIds"] == [7] and s["code"] == "LOB"  # code is this tool's
    assert s["releases"][0]["keyArt"]["url"] == "https://y/a.jpg"  # no set_image here, so the other tool's art stays


def test_rerun_keeps_what_later_tools_added_to_a_card_and_its_prints():
    set_ids = {LOB: LOB_ID}
    files, counts = imp.build_cards([raw_card()], set_ids, {}, {})
    assert list(files) == ["046"] and counts["duplicates"] == 0
    card = files["046"]["cards"][0]
    card["names"]["fr"] = "Magicien Sombre"
    card["identifiers"].update({"ygojsonId": "u1", "yugipediaIds": [5]})
    card["prints"][0].update({"identifiers": {"tcgplayerProductIds": [10]}, "tcgplayer": {"name": "x", "match": "number"},
                              "editions": ["first"]})
    again, _ = imp.build_cards([raw_card()], set_ids, {}, files)
    c = again["046"]["cards"][0]
    assert c["names"] == {"en": "Dark Magician", "fr": "Magicien Sombre"}
    assert c["identifiers"] == {"ygoprodeckId": 46986414, "konamiId": 4041, "ygojsonId": "u1", "yugipediaIds": [5]}
    assert c["prints"][0]["identifiers"] == {"tcgplayerProductIds": [10]}
    assert c["prints"][0]["tcgplayer"] == {"name": "x", "match": "number"} and c["prints"][0]["editions"] == ["first"]


def test_cards_are_bucketed_and_sorted_by_numeric_id():
    cards = [raw_card(id=100), raw_card(id=46986414), raw_card(id=9), raw_card(id=1_000_000)]
    files, _ = imp.build_cards(cards, {LOB: LOB_ID}, {}, {})
    assert list(files) == ["000", "001", "046"]
    assert [c["id"] for c in files["000"]["cards"]] == ["9", "100"]


def test_archetype_slugs_collide_deterministically_and_reruns_keep_names():
    cards = [raw_card(archetype="D/D"), raw_card(id=2, archetype="D.D."), raw_card(id=3)]
    arch, slugs = imp.build_archetypes(cards, ["Roid", "roid"], {})
    assert slugs == {"D.D.": "d-d", "D/D": "d-d-2", "Roid": "roid", "roid": "roid-2"}
    assert [a["slug"] for a in arch["archetypes"]] == ["d-d", "d-d-2", "roid", "roid-2"]
    assert imp.collisions(slugs) == {"d-d": ["D.D.", "D/D"], "roid": ["Roid", "roid"]}
    files, _ = imp.build_cards(cards, {LOB: LOB_ID}, slugs, {})
    by_id = {c["id"]: c for body in files.values() for c in body["cards"]}
    assert by_id["46986414"]["archetypes"] == ["d-d-2"] and by_id["2"]["archetypes"] == ["d-d"]
    assert "archetypes" not in by_id["3"]

    arch["archetypes"][0].update({"names": {"fr": "x"}, "isArchetype": False, "identifiers": {"ygojsonId": "s"}})
    again, _ = imp.build_archetypes(cards, ["Roid", "roid"], arch)
    assert again["archetypes"][0]["names"] == {"fr": "x"} and again["archetypes"][0]["isArchetype"] is False


def test_output_validates():
    listed = [{"set_name": LOB, "set_code": "LOB", "tcg_date": "2002-03-08"}]
    sets, ids = imp.build_sets([raw_card(archetype="Blue-Eyes")], listed, ERAS, [])
    arch, slugs = imp.build_archetypes([raw_card(archetype="Blue-Eyes")], [], {})
    files, _ = imp.build_cards([raw_card(archetype="Blue-Eyes")], ids, slugs, {})
    assert ygjson.validate(sets, ERAS, files, arch) == []
