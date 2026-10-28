import copy

import pytest

import import_ygojson as imp
import ygjson


def our_set(set_id, name, code, **over):
    s = {"id": set_id, "code": code, "name": name, "type": "booster", "editions": ["unlimited"], "source": "ygoprodeck",
         "releases": [{"language": "en", "name": name}]}
    s.update(over)
    return s


def their_set(uuid, name, prefix=None, locale="en", yugipedia=None, **locale_over):
    body = {"language": locale, **({"prefix": prefix} if prefix else {}), **locale_over}
    g = {"id": uuid, "name": {"en": name}, "locales": {locale: body}}
    if yugipedia:
        g["externalIDs"] = {"yugipedia": {"name": yugipedia, "id": 7}}
    return g


def matched(ours, theirs):
    return {sid: (g["id"], rule) for sid, (g, rule) in imp.match_sets(ours, theirs).items()}


@pytest.mark.parametrize("a, b", [
    ("Magician&apos;s Force", "Magician’s Force"),
    ("Magician's  Force", "magician's force"),
    ("Yu-Gi-Oh! 5D's", "yu gi oh 5d s"),
    ("  Dark Crisis ", "Dark Crisis"),
])
def test_normalise_unifies_case_apostrophes_and_punctuation(a, b):
    assert imp.normalise(a) == imp.normalise(b)


def test_normalise_keeps_different_words_apart():
    assert imp.normalise("Dark Crisis") != imp.normalise("Dark Crisis 2")


def test_exact_name_wins_before_any_looser_rule():
    ours = [our_set("a", "Pack", "AAA")]
    theirs = [their_set("exact", "Pack", "ZZZ-EN"), their_set("loose", "pack!", "AAA-EN")]
    assert matched(ours, theirs) == {"a": ("exact", "exact_name")}


def test_name_and_prefix_beats_name_alone():
    ours = [our_set("a", "Magician's Force", "MFC")]
    theirs = [their_set("u1", "Magician&apos;s Force", "MFC-EN")]
    assert matched(ours, theirs) == {"a": ("u1", "name_and_prefix")}


def test_name_alone_needs_uniqueness_on_both_sides():
    theirs = [their_set("u1", "Duelist Pack: Kaiba", "ONE-EN")]
    assert matched([our_set("a", "Duelist Pack Kaiba", "DPK")], theirs) == {"a": ("u1", "name")}
    twice = [our_set("a", "Duelist Pack Kaiba", "DPK"), our_set("b", "duelist pack kaiba", "DPK")]
    assert matched(twice, theirs) == {}
    assert matched([our_set("a", "Duelist Pack Kaiba", "DPK")],
                   theirs + [their_set("u2", "Duelist-Pack Kaiba", "TWO-EN")]) == {}


def test_prefix_rule_needs_exactly_one_set_on_each_side():
    theirs = [their_set("u1", "Totally Different", "SDY-EN")]
    assert matched([our_set("a", "Starter Deck Yugi", "SDY")], theirs) == {"a": ("u1", "prefix")}
    assert matched([our_set("a", "Starter Deck Yugi", "SDY"), our_set("b", "Other", "SDY")], theirs) == {}
    assert matched([our_set("a", "Starter Deck Yugi", "SDY")], theirs + [their_set("u2", "Else", "SDY-EN")]) == {}


def test_a_claimed_set_is_not_offered_to_a_later_rule():
    ours = [our_set("a", "Pack", "AAA"), our_set("b", "Pack Reprint", "AAA")]
    theirs = [their_set("u1", "Pack", "AAA-EN")]
    assert matched(ours, theirs) == {"a": ("u1", "exact_name")}


def test_same_english_name_twice_is_told_apart_by_the_yugipedia_title():
    ours = [our_set("base", "Dark Crisis", "DCR"),
            our_set("anniv", "Dark Crisis (25th Anniversary Edition)", "DCR")]
    theirs = [their_set("u-anniv", "Dark Crisis", "DCR-EN", yugipedia="Dark Crisis (25th Anniversary Edition)"),
              their_set("u-base", "Dark Crisis", "DCR-EN", yugipedia="Dark Crisis")]
    assert matched(ours, theirs) == {"base": ("u-base", "yugipedia_name"), "anniv": ("u-anniv", "yugipedia_name")}


def test_regional_english_locale_counts_and_en_wins():
    ancient = their_set("u-na", "Ancient Sanctuary", "AST-", locale="na")
    assert imp.en_sets([ancient, their_set("u-jp", "Magic Ruler", locale="jp")]) == [ancient]
    assert matched([our_set("a", "Ancient Sanctuary", "AST")], [ancient]) == {"a": ("u-na", "exact_name")}
    both = {"id": "u", "name": {"en": "X"}, "locales": {"na": {"prefix": "NA-"}, "en": {"prefix": "EN-EN"}}}
    assert imp.en_prefix(both) == "EN"


def test_tcgplayer_sets_are_never_matched():
    ours = [our_set("a", "Pack", "AAA", source="tcgplayer")]
    assert matched(ours, [their_set("u1", "Pack", "AAA-EN")]) == {}


def test_apply_set_writes_identifiers_editions_date_and_art():
    s = our_set("lob", "Legend of Blue Eyes", "LOB")
    g = their_set("u-lob", "Legend of Blue Eyes", "LOB-EN", yugipedia="Legend of Blue Eyes: Test/x",
                  date="2002-03-08", image="https://ms.yugipedia.com/a.png", editions=["unlimited", "1st"],
                  externalIDs={"dbIDs": [11101000, "11101001"]})
    imp.apply_set(s, g)
    assert s["identifiers"] == {"ygojsonId": "u-lob", "yugipediaId": 7, "konamiDatabaseIds": [11101000, 11101001]}
    assert s["editions"] == ["first", "unlimited"]
    assert s["releases"][0]["releaseDate"] == "2002-03-08"
    assert s["releases"][0]["keyArt"] == {"url": "https://ms.yugipedia.com/a.png",
                                          "source": "https://yugipedia.com/wiki/Legend_of_Blue_Eyes:_Test/x"}


def test_apply_set_keeps_what_the_set_has():
    s = our_set("a", "A", "AAA", editions=["limited"], identifiers={"konamiDatabaseIds": [5]})
    s["releases"][0].update(releaseDate="2000-01-01", keyArt={"url": "https://y/x.jpg", "source": "https://y/"})
    g = their_set("u", "A", "AAA-EN", yugipedia="A", date="2010-01-01", image="https://ms/a.png",
                  externalIDs={"dbIDs": [6]})
    imp.apply_set(s, g)  # no editions on the YGOJSON side
    assert s["editions"] == ["limited"]
    assert s["releases"][0]["releaseDate"] == "2000-01-01"
    assert s["releases"][0]["keyArt"]["url"] == "https://y/x.jpg"
    assert s["identifiers"]["konamiDatabaseIds"] == [5, 6]


def test_apply_set_without_a_yugipedia_page_writes_no_art():
    s = our_set("a", "A", "AAA")
    imp.apply_set(s, their_set("u", "A", "AAA-EN", image="https://ms/a.png"))
    assert "keyArt" not in s["releases"][0]
    assert s["identifiers"] == {"ygojsonId": "u"}


def test_yugipedia_page_quotes_the_title():
    assert imp.yugipedia_page("Yu-Gi-Oh! 5D's Volume 1") == "https://yugipedia.com/wiki/Yu-Gi-Oh!_5D%27s_Volume_1"
    assert imp.yugipedia_page("Tournament Pack: 1st Season") == "https://yugipedia.com/wiki/Tournament_Pack:_1st_Season"


def our_card(card_id, name="Dark Magician", **ids):
    return {"id": card_id, "name": name, "names": {"en": name}, "identifiers": {"ygoprodeckId": int(card_id), **ids}}


def their_card(uuid, ygoprodeck=None, passwords=(), **over):
    g = {"id": uuid, "passwords": list(passwords), "text": {"en": {"name": "Dark Magician"}}, "externalIDs": {}}
    if ygoprodeck is not None:
        g["externalIDs"]["ygoprodeck"] = {"id": ygoprodeck, "name": "x"}
    g.update(over)
    return g


def test_cards_match_by_ygoprodeck_id_then_by_password():
    ours = [our_card("46986414"), our_card("46986415"), our_card("1"), our_card("2")]
    theirs = [their_card("g1", ygoprodeck=46986414), their_card("g2", passwords=["46986415"]),
              their_card("g3", ygoprodeck=999, passwords=["1"])]
    assert {k: v["id"] for k, v in imp.match_cards(ours, theirs).items()} == {
        "46986414": "g1", "46986415": "g2", "1": "g3"}


def test_a_password_does_not_steal_a_card_another_id_matched():
    ours = [our_card("100"), our_card("101")]
    theirs = [their_card("g1", ygoprodeck=100, passwords=["100", "101"])]
    assert {k: v["id"] for k, v in imp.match_cards(ours, theirs).items()} == {"100": "g1"}


def test_an_ambiguous_password_matches_nothing():
    ours = [our_card("7")]
    theirs = [their_card("g1", passwords=["7"]), their_card("g2", passwords=["7"])]
    assert imp.match_cards(ours, theirs) == {}


def test_apply_card_writes_ids_and_other_language_names():
    card = our_card("46986414")
    g = their_card("g1", ygoprodeck=46986414, text={
        "en": {"name": "Dark Magician (YGOJSON spelling)"}, "fr": {"name": "Magicien Sombre"},
        "zh-CN": {"name": "黑魔导"}, "ja_romaji": {"name": "Burakku"}, "de": {"name": ""}},
        externalIDs={"ygoprodeck": {"id": 46986414}, "dbID": 4041,
                     "yugipedia": [{"id": 20, "name": "a"}, {"id": 10, "name": "b"}]})
    imp.apply_card(card, g)
    assert card["names"] == {"en": "Dark Magician", "fr": "Magicien Sombre", "zh-CN": "黑魔导"}
    assert card["identifiers"] == {"ygoprodeckId": 46986414, "ygojsonId": "g1", "konamiId": 4041,
                                   "yugipediaIds": [10, 20]}


def test_apply_card_keeps_an_existing_konami_id_and_tolerates_missing_external_ids():
    card = our_card("5", konamiId=111)
    imp.apply_card(card, their_card("g", externalIDs={"dbID": 222, "yugipedia": None}))
    assert card["identifiers"]["konamiId"] == 111
    assert "yugipediaIds" not in card["identifiers"]
    bare = our_card("6")
    imp.apply_card(bare, {"id": "g", "text": {"en": {"name": "x"}}})
    assert bare["identifiers"] == {"ygoprodeckId": 6, "ygojsonId": "g"}


def arch(slug, name, source="ygoprodeck", **over):
    return {"slug": slug, "name": name, "source": source, **over}


def series(uuid, name, archetype=True, members=(), yugipedia=None):
    names = {"en": name, "ja": "魔導獣", "ja_romaji": "Majikku", "ko_rr": "x", "zh-TW": "繁"}
    g = {"id": uuid, "name": names, "archetype": archetype, "members": list(members), "externalIDs": {}}
    if yugipedia:
        g["externalIDs"]["yugipedia"] = {"name": name, "id": yugipedia}
    return g


def test_series_match_exact_name_then_unique_case_insensitive_name():
    ours = [arch("mythical-beast", "Mythical Beast"), arch("roid", "Roid"), arch("roid-2", "roid"),
            arch("hero", "HERO")]
    sers = [series("s1", "Mythical Beast"), series("s2", "roid"), series("s3", "Roid"), series("s4", "Hero"),
            series("s5", "Elsewhere")]
    found = imp.match_series(ours, sers)
    assert {slug: g["id"] for slug, g in found.items()} == {
        "mythical-beast": "s1", "roid-2": "s2", "roid": "s3", "hero": "s4"}


def test_case_insensitive_name_is_skipped_when_it_is_not_unique():
    ours = [arch("a", "Hero"), arch("b", "HERO")]
    assert imp.match_series(ours, [series("s", "hero")]) == {}


def test_two_series_with_one_name_keep_their_archetype_across_runs():
    ours = [arch("sprout", "sprout", identifiers={"ygojsonId": "b"})]
    twin = [series("a", "sprout", archetype=False), series("b", "sprout")]
    assert imp.match_series(ours, twin)["sprout"]["id"] == "b"
    assert imp.match_series([arch("sprout", "sprout")], twin)["sprout"]["id"] == "b"  # the flagged one first


def test_sync_matches_adds_and_defaults():
    archetypes = [arch("mythical-beast", "Mythical Beast"), arch("unlisted", "Unlisted")]
    sers = [series("s1", "Mythical Beast", archetype=False, yugipedia=520411),
            series("s2", "Blue-Eyes", members=["g1"], yugipedia=9),
            series("s3", "Not An Archetype", archetype=False)]
    matched_, added, skipped = imp.sync_archetypes(archetypes, sers)
    by_slug = {a["slug"]: a for a in archetypes}
    mb = by_slug["mythical-beast"]
    assert mb["isArchetype"] is False
    assert mb["names"] == {"en": "Mythical Beast", "ja": "魔導獣", "zh-TW": "繁"}  # no romanisations
    assert mb["identifiers"] == {"ygojsonId": "s1", "yugipediaId": 520411}
    assert by_slug["unlisted"]["isArchetype"] is True
    assert [a["slug"] for a in added] == ["blue-eyes"] and skipped == []
    assert by_slug["blue-eyes"] == {"slug": "blue-eyes", "name": "Blue-Eyes", "source": "ygojson", "isArchetype": True,
                                    "names": {"en": "Blue-Eyes", "ja": "魔導獣", "zh-TW": "繁"},
                                    "identifiers": {"ygojsonId": "s2", "yugipediaId": 9}}
    assert "not-an-archetype" not in by_slug
    assert [a["slug"] for a in archetypes] == sorted(by_slug)
    assert set(matched_) == {"mythical-beast", "blue-eyes"}


def test_a_series_whose_slug_is_taken_is_skipped_and_listed():
    archetypes = [arch("magnet-warrior", "Magnet Warrior")]
    _, added, skipped = imp.sync_archetypes(archetypes, [series("s1", "Magnet Warrior Σ")])
    assert added == [] and [g["id"] for g in skipped] == ["s1"]
    assert len(archetypes) == 1


def test_memberships_only_for_ygojson_archetypes():
    archetypes = [arch("listed", "Listed"), arch("blue-eyes", "Blue-Eyes", source="ygojson")]
    sers = {"listed": series("s1", "Listed", members=["g1", "g2"]),
            "blue-eyes": series("s2", "Blue-Eyes", members=["g1", "g3"])}
    cards = [our_card("1", ygojsonId="g1"), our_card("2", ygojsonId="g2"), our_card("3", ygojsonId="g3"),
             our_card("4")]
    cards[0]["archetypes"] = ["listed"]
    assert imp.add_memberships(cards, archetypes, sers) == 2
    assert cards[0]["archetypes"] == ["blue-eyes", "listed"]
    assert "archetypes" not in cards[1]
    assert cards[2]["archetypes"] == ["blue-eyes"]
    assert "archetypes" not in cards[3]
    assert imp.add_memberships(cards, archetypes, sers) == 0  # idempotent


def test_review_body_is_sorted_and_complete():
    sets = [our_set("b", "B", "BBB"), our_set("a", "A", "AAA"), our_set("c", "C", "CCC")]
    theirs = [their_set("u-c", "C", "CCC-EN"), their_set("u-z", "Zed", "ZZZ-EN"), their_set("u-y", "Why", "YYY-EN")]
    found = imp.match_sets(sets, theirs)
    cards = [our_card("20", "Twenty"), our_card("3", "Three")]
    body = imp.review_body(sets, found, theirs, cards, {"3": {}}, [series("sk", "Skipped")])
    assert body["setsUnmatched"] == [{"id": "a", "name": "A", "code": "AAA"}, {"id": "b", "name": "B", "code": "BBB"}]
    assert [g["name"] for g in body["ygojsonSetsUnclaimed"]] == ["Why", "Zed"]
    assert body["cardsUnmatched"] == [{"id": "20", "name": "Twenty"}]
    assert body["archetypesSkipped"] == [{"id": "sk", "name": "Skipped", "slug": "skipped"}]
    assert body["setsMatchedByFallback"] == []


def test_applying_everything_twice_changes_nothing():
    s = our_set("lob", "Legend of Blue Eyes", "LOB")
    g = their_set("u", "Legend of Blue Eyes", "LOB-EN", yugipedia="Legend of Blue Eyes", date="2002-03-08",
                  image="https://ms/a.png", editions=["1st"], externalIDs={"dbIDs": [1]})
    imp.apply_set(s, g)
    once = copy.deepcopy(s)
    imp.apply_set(s, g)
    assert s == once
    card = our_card("1")
    c = their_card("c", ygoprodeck=1, text={"en": {"name": "x"}, "fr": {"name": "y"}})
    imp.apply_card(card, c)
    once = copy.deepcopy(card)
    imp.apply_card(card, c)
    assert card == once


def test_results_validate_against_the_schemas():
    s = our_set("lob", "Legend of Blue Eyes", "LOB")
    imp.apply_set(s, their_set("u", "Legend of Blue Eyes", "LOB-EN", yugipedia="Legend of Blue Eyes",
                               date="2002-03-08", image="https://ms.yugipedia.com/a.png", editions=["1st", "limited"],
                               externalIDs={"dbIDs": [1]}))
    card = {**our_card("46986414"), "kind": "monster", "frame": "normal", "hasEffect": False, "isTuner": False,
            "prints": []}
    imp.apply_card(card, their_card("c", ygoprodeck=46986414, text={"en": {"name": "x"}, "zh-CN": {"name": "黑"}}))
    archetypes = {"archetypes": [arch("hero", "HERO")]}
    imp.sync_archetypes(archetypes["archetypes"], [series("s", "Hero")])
    eras = [{"code": "dm", "name": "Duel Monsters", "mechanic": "Fusion", "from": "2002-03-08"}]
    assert ygjson.validate([s], eras, {"046": {"cards": [card]}}, archetypes) == []
