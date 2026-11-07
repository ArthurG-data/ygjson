import json

import pytest

import yugipedia as y

LOB = """{{About|the international set|other uses|''LOB'' (disambiguation)}}
{{Infobox set
| image           = LOB-BoosterEN.png

| en_name         = Legend of Blue Eyes White Dragon
| ja_name         = ストラクチャーデッキ －ドラゴンの{{Ruby|力|ちから}}－
| type            = [[Booster pack]]
| series          = Core Booster
| size            =
* 126
* 103 (E, F, G, I)
| cover_card      = [[Blue-Eyes White Dragon|Blue-Eyes]]
| en_database_id  = 11101000
| other_sets      = ''Legend of Blue Eyes White Dragon'' promotional cards
| na_release_date = March 8, 2002
| eu_release_date = December 2002
| fr/de/it/sp_release_date = March 2003
| next            = Metal Raiders
}}

'''''Legend of Blue Eyes White Dragon''''' is the first set.
"""


def test_infobox_strips_links_italics_ruby_and_lists():
    ib = y.infobox(LOB)
    assert ib["type"] == "Booster pack"
    assert ib["series"] == "Core Booster"
    assert ib["cover_card"] == "Blue-Eyes"  # [[A|B]] -> B
    assert ib["ja_name"] == "ストラクチャーデッキ －ドラゴンの力－"
    assert ib["size"] == "126; 103 (E, F, G, I)"
    assert ib["other_sets"] == "Legend of Blue Eyes White Dragon promotional cards"


def test_infobox_keeps_slash_keys_and_empty_values():
    ib = y.infobox(LOB + "")
    assert ib["fr/de/it/sp_release_date"] == "March 2003"
    assert y.infobox("{{Infobox set\n| type = Tin\n| eu_release_date = \n}}")["eu_release_date"] == ""


def test_infobox_ends_at_the_matching_braces_even_with_nested_templates():
    text = "{{Infobox set\n| a = {{Ruby|x|y}}\n| b = [[C|D]]\n}}\n| not_a_field = 1\n"
    assert y.infobox(text) == {"a": "x", "b": "D"}


def test_infobox_on_one_line_and_case_insensitive_name():
    assert y.infobox("{{infobox set|type=[[Tin]]|prefix=ABC}}") == {"type": "Tin", "prefix": "ABC"}


def test_infobox_none_without_template():
    assert y.infobox("just text {{Other|x=1}}") is None


def test_infobox_ignores_html_comments_and_refs():
    ib = y.infobox("{{Infobox set\n| type = Tin <!-- check --> \n| na_release_date = May 1, 2003<ref>x</ref>\n}}")
    assert ib == {"type": "Tin", "na_release_date": "May 1, 2003"}


def test_named_in_gives_italics_and_link_targets():
    assert y.named_in("''Dark Crisis'' promotional cards") == ["Dark Crisis"]
    assert y.named_in("[[Spell Ruler|Magic Ruler]]; ''Pharaoh's Servant''") == ["Pharaoh's Servant", "Spell Ruler", "Magic Ruler"]
    assert y.named_in("Dark Crisis promotional cards") == []


@pytest.mark.parametrize("text, iso", [
    ("December 9, 2004", "2004-12-09"),
    ("March 8th, 2002", "2002-03-08"),
    ("December 2002", "2002-12-01"),  # month precision: the 1st, never a guessed day
    ("[[June 3]], 2005", "2005-06-03"),  # links are stripped first
    ("2023", None),
    ("", None),
    (None, None),
    ("Smarch 3, 2004", None),
    ("February 30, 2004", None),
])
def test_parse_date(text, iso):
    assert y.parse_date(text) == iso


def test_page_urls():
    assert y.page_url("Duelist Pack: Yusei 2") == "https://yugipedia.com/wiki/Duelist_Pack:_Yusei_2"
    assert y.file_url("File:LOB-Booster EN.png") == "https://yugipedia.com/wiki/Special:FilePath/LOB-Booster_EN.png"


# --- cache ---------------------------------------------------------------------------------------------------

@pytest.fixture
def api(monkeypatch):
    calls = []

    def fake(params):
        calls.append(params)
        if "pageids" in params:
            ids = [int(i) for i in params["pageids"].split("|")]
            return {"query": {"pages": [{"pageid": i, "title": f"T{i}", "revisions": []} if i < 1000 else
                                        {"pageid": i, "missing": True} for i in ids]}}
        title = params["titles"]
        if title == "Nope":
            return {"query": {"pages": [{"title": "Nope", "missing": True}]}}
        return {"query": {"pages": [{"pageid": 5, "title": title, "revisions": []}]}}

    monkeypatch.setattr(y, "_query", fake)
    return calls


def test_pages_by_id_batches_fifty_and_caches(api, tmp_path):
    got = y.pages_by_id(range(1, 121), tmp_path)
    assert [len(c["pageids"].split("|")) for c in api] == [50, 50, 20]
    assert got[7]["title"] == "T7"
    assert (tmp_path / "page_7.json").exists()
    y.pages_by_id(range(1, 121), tmp_path)
    assert len(api) == 3  # all cached


def test_missing_page_is_cached_and_returns_none(api, tmp_path):
    assert y.page_by_id(2000, tmp_path) is None
    assert y.page_by_id(2000, tmp_path) is None
    assert len(api) == 1
    assert json.loads((tmp_path / "page_2000.json").read_text())["missing"] is True


def test_refresh_fetches_again(api, tmp_path):
    y.page_by_id(3, tmp_path)
    y.page_by_id(3, tmp_path, refresh=True)
    assert len(api) == 2


def test_page_by_title_caches_hits_and_misses(api, tmp_path):
    assert y.page_by_title("Dark Crisis", tmp_path)["pageid"] == 5
    assert y.page_by_title("Nope", tmp_path) is None
    assert y.page_by_title("Nope", tmp_path) is None
    assert y.page_by_title("Dark Crisis", tmp_path)["pageid"] == 5
    assert [c["titles"] for c in api] == ["Dark Crisis", "Nope"]
    assert (tmp_path / "title_dark-crisis.json").exists()
    assert json.loads((tmp_path / "title_nope.json").read_text()) == {"missing": True, "title": "Nope"}


def test_page_by_title_refresh_replaces_a_cached_page(api, tmp_path):
    y.page_by_title("Dark Crisis", tmp_path)
    y.page_by_title("Dark Crisis", tmp_path, refresh=True)
    assert [c["titles"] for c in api] == ["Dark Crisis", "Dark Crisis"]


# --- limitation lists -------------------------------------------------------------------------------------------

def list_page(start="October 19, 2026", following="", forbidden="Abyss Dweller", limited="Monster Reborn", semi="",
              medium="TCG", fmt="Advanced Format"):
    return (f"These are the lists.<ref>{{{{cite web | title = x}}}}</ref>\n\n{{{{Limitation list\n"
            f"| start_date        = {start}\n| end_date          = \n| medium            = {medium}\n"
            f"| format            = {fmt}\n| prev              = Earlier Lists (TCG)\n"
            f"| next              = {following}\n| forbidden         = \n{forbidden}\n"
            f"| limited           = \n{limited}\n| semi_limited      = \n{semi}\n}}}}\n\n== References ==\n")


def test_limitation_list_reads_the_date_the_next_page_and_each_status():
    parsed = y.limitation_list(list_page(
        following="November 2026 Lists (TCG)",
        forbidden="Abyss Dweller\nAerial Eater // prev::Unlimited\nMaliss P Dormouse // force-smw",
        limited="Droll &amp; Lock Bird // prev::Semi-Limited\nToon Bookmark // unreleased::TCG",
        semi="Ice Ryzeal"))
    assert parsed == {"date": "2026-10-19", "next": "November 2026 Lists (TCG)", "medium": "TCG",
                      "format": "Advanced Format", "statuses": {
        "Abyss Dweller": "banned", "Aerial Eater": "banned", "Maliss P Dormouse": "banned",
        "Droll & Lock Bird": "limited", "Toon Bookmark": "limited", "Ice Ryzeal": "semi_limited"}}


def test_limitation_list_without_a_next_page_says_none():
    assert y.limitation_list(list_page())["next"] is None


@pytest.mark.parametrize("start", ["October 2026", "2026", "", "TBA"])
def test_limitation_list_refuses_a_date_that_is_not_a_full_date(start):
    assert y.limitation_list(list_page(start=start)) is None


def test_limitation_list_refuses_an_empty_list():
    # An empty section would read as every card moving to legal on this date.
    assert y.limitation_list(list_page(forbidden="")) is None
    assert y.limitation_list(list_page(limited="")) is None


def test_limitation_list_allows_an_empty_semi_limited_section():
    assert y.limitation_list(list_page(semi=""))["statuses"] == {"Abyss Dweller": "banned", "Monster Reborn": "limited"}


def test_limitation_list_none_without_the_template():
    assert y.limitation_list("{{Infobox set | name = x}}") is None


@pytest.fixture
def wiki(monkeypatch):
    pages, calls = {}, []

    def fake(params):
        title = params["titles"]
        calls.append(title)
        if title not in pages:
            return {"query": {"pages": [{"title": title, "missing": True}]}}
        return {"query": {"pages": [{"pageid": 9, "title": title,
                                     "revisions": [{"slots": {"main": {"content": pages[title]}}}]}]}}

    monkeypatch.setattr(y, "_query", fake)
    return pages, calls


def test_limitation_lists_follow_next_in_order(wiki, tmp_path):
    pages, _ = wiki
    pages["A"] = list_page(start="May 18, 2026", following="B")
    pages["B"] = list_page(start="September 21, 2026")
    assert [l["date"] for l in y.limitation_lists("A", "TCG", tmp_path)] == ["2026-05-18", "2026-09-21"]


def test_limitation_lists_ask_again_for_the_last_page_only(wiki, tmp_path):
    pages, calls = wiki
    pages["A"] = list_page(start="May 18, 2026", following="B")
    pages["B"] = list_page(start="September 21, 2026")
    y.limitation_lists("A", "TCG", tmp_path)
    calls.clear()
    pages["B"] = list_page(start="September 21, 2026", following="C")
    pages["C"] = list_page(start="October 19, 2026")
    got = y.limitation_lists("A", "TCG", tmp_path)
    assert [l["date"] for l in got] == ["2026-05-18", "2026-09-21", "2026-10-19"]
    assert "A" not in calls


def test_limitation_lists_stop_at_a_next_page_that_does_not_exist_yet(wiki, tmp_path):
    pages, _ = wiki
    pages["A"] = list_page(start="May 18, 2026", following="Not Written")
    assert [l["date"] for l in y.limitation_lists("A", "TCG", tmp_path)] == ["2026-05-18"]


def test_limitation_lists_stop_at_a_loop(wiki, tmp_path):
    pages, _ = wiki
    pages["A"] = list_page(start="May 18, 2026", following="A")
    assert len(y.limitation_lists("A", "TCG", tmp_path)) == 1


def test_limitation_lists_fail_when_the_first_page_has_no_list(wiki, tmp_path):
    with pytest.raises(ValueError):
        y.limitation_lists("Moved Away", "TCG", tmp_path)


def test_limitation_lists_stop_at_a_page_of_another_medium(wiki, tmp_path):
    pages, _ = wiki
    pages["A"] = list_page(start="May 18, 2026", following="B")
    pages["B"] = list_page(start="September 21, 2026", medium="OCG")
    assert [l["date"] for l in y.limitation_lists("A", "TCG", tmp_path)] == ["2026-05-18"]


def test_limitation_lists_stop_at_a_page_of_another_format(wiki, tmp_path):
    pages, _ = wiki
    pages["A"] = list_page(start="May 18, 2026", following="B")
    pages["B"] = list_page(start="September 21, 2026", fmt="Traditional Format")
    assert [l["date"] for l in y.limitation_lists("A", "TCG", tmp_path)] == ["2026-05-18"]


def test_limitation_lists_stop_at_a_date_that_does_not_move_forward(wiki, tmp_path):
    pages, _ = wiki
    pages["A"] = list_page(start="May 18, 2026", following="B")
    pages["B"] = list_page(start="February 2, 2026")
    assert [l["date"] for l in y.limitation_lists("A", "TCG", tmp_path)] == ["2026-05-18"]


def test_limitation_lists_stop_at_a_page_that_drops_most_of_the_last_list(wiki, tmp_path):
    pages, _ = wiki
    cards = [f"Card {i}" for i in range(10)]
    pages["A"] = list_page(start="May 18, 2026", following="B", forbidden="\n".join(cards[:5]), limited="\n".join(cards[5:]))
    pages["B"] = list_page(start="September 21, 2026", forbidden=cards[0], limited=cards[1])
    assert [l["date"] for l in y.limitation_lists("A", "TCG", tmp_path)] == ["2026-05-18"]


def test_limitation_lists_stop_at_a_page_missing_a_whole_section_of_the_last_list(wiki, tmp_path):
    # Limited is about a third of a real list. The most any 2026 list dropped is 4.4%.
    pages, _ = wiki
    cards = [f"Card {i}" for i in range(10)]
    pages["A"] = list_page(start="May 18, 2026", following="B", forbidden="\n".join(cards[:7]), limited="\n".join(cards[7:]))
    pages["B"] = list_page(start="September 21, 2026", forbidden="\n".join(cards[:6]), limited=cards[6])
    assert [l["date"] for l in y.limitation_lists("A", "TCG", tmp_path)] == ["2026-05-18"]


def test_limitation_lists_accept_a_page_that_drops_a_few_of_the_last_list(wiki, tmp_path):
    pages, _ = wiki
    cards = [f"Card {i}" for i in range(10)]
    pages["A"] = list_page(start="May 18, 2026", following="B", forbidden="\n".join(cards[:5]), limited="\n".join(cards[5:]))
    pages["B"] = list_page(start="September 21, 2026", forbidden="\n".join(cards[:5]), limited="\n".join(cards[5:8]))
    assert len(y.limitation_lists("A", "TCG", tmp_path)) == 2


def test_limitation_lists_fail_when_the_first_page_is_another_medium(wiki, tmp_path):
    pages, _ = wiki
    pages["A"] = list_page(medium="OCG")
    with pytest.raises(ValueError):
        y.limitation_lists("A", "TCG", tmp_path)


def test_limitation_lists_accept_a_page_that_names_no_format(wiki, tmp_path):
    # Every OCG list page leaves the field out.
    pages, _ = wiki
    pages["A"] = list_page(start="October 1, 2026", medium="OCG").replace("| format            = Advanced Format\n", "")
    assert [l["date"] for l in y.limitation_lists("A", "OCG", tmp_path)] == ["2026-10-01"]
