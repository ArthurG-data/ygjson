import changelog


def entry(i, status="live", **over):
    return {"id": i, "status": status, **over}


BEFORE = {
    "prints": {"p1": entry("p1", key="lob:1:LOB-001:rare"), "p2": entry("p2", key="lob:2:LOB-002:rare"),
               "p3": entry("p3", key="lob:3:LOB-003:rare")},
    "cards": {"1": entry("1", name="Alpha"), "2": entry("2", name="Beta")},
    "sets": {"lob": entry("lob", names=["LOB"])},
    "sealed": {"box": entry("box")},
}
AFTER = {
    "prints": {"p1": entry("p1", key="lob:1:LOB-EN001:rare", formerKeys=["lob:1:LOB-001:rare"]),
               "p2": entry("p2", "retired", key="lob:2:LOB-002:rare", successors=["p4"]),
               "p3": entry("p3", key="lob:3:LOB-003:rare"),
               "p4": entry("p4", key="lob:2:LOB-002:super_rare"),
               "p5": entry("p5", "retired", key="x", successors=["p4"])},
    "cards": {"1": entry("1", name="Alpha"), "2": entry("2", name="Beta Prime")},
    "sets": {"lob": entry("lob", names=["LOB", "Legend of Blue Eyes"])},
    "sealed": {"box": entry("box")},
}


def test_added_retired_and_renamed_ids_by_kind():
    data = changelog.changes(BEFORE, AFTER)
    assert data["prints"] == {"added": ["p4", "p5"],  # p5 is new and already retired: added only
                              "retired": [{"id": "p2", "successors": ["p4"]}],
                              "renamed": [{"id": "p1", "from": "lob:1:LOB-001:rare", "to": "lob:1:LOB-EN001:rare"}]}
    assert data["cards"]["renamed"] == [{"id": "2", "from": "Beta", "to": "Beta Prime"}]
    assert data["sets"]["renamed"] == [{"id": "lob", "from": "LOB", "to": "Legend of Blue Eyes"}]
    assert data["sealed"] == {"added": [], "retired": [], "renamed": []}
    assert set(data) == set(changelog.ids.KINDS)


def test_oracles_are_added_and_retired_but_never_renamed():
    before = {"oracles": {"o1": entry("o1", cards=["1"]), "o2": entry("o2", cards=["2"])}}
    after = {"oracles": {"o1": entry("o1", cards=["1", "3"]),  # a card joining is no rename
                         "o2": entry("o2", "retired", cards=["2"], successors=["o1"]),
                         "o4": entry("o4", cards=["4"])}}
    assert changelog.changes(before, after)["oracles"] == {"added": ["o4"],
                                                           "retired": [{"id": "o2", "successors": ["o1"]}],
                                                           "renamed": []}


def test_an_id_retired_before_stays_out_of_the_list():
    before = {"cards": {"1": entry("1", "retired", name="A", successors=["2"])}}
    after = {"cards": {"1": entry("1", "retired", name="A", successors=["3"])}}
    assert changelog.changes(before, after)["cards"] == {"added": [], "retired": [], "renamed": []}


def test_markdown_counts_each_kind_and_caps_the_lists(monkeypatch):
    monkeypatch.setattr(changelog, "SHOWN", 1)
    after = {**AFTER, "cards": {"1": entry("1", name="Alpha 2"), "2": entry("2", name="Beta Prime")}}
    text = changelog.markdown(changelog.changes(BEFORE, after), "v0.2.0", first=False)
    assert "## Ids since v0.2.0" in text and "| prints | 2 | 1 | 1 |" in text and "| cards | 0 | 0 | 2 |" in text
    assert "- retired `p2` → `p4`" in text and "- renamed `1`: `Alpha` → `Alpha 2`" in text
    assert "- and 1 more in `Changes.json`" in text  # Beta's rename is past the cap


def test_the_first_ledger_release_says_every_id_is_new():
    text = changelog.markdown(changelog.changes({}, AFTER), None, first=True)
    assert "all 9 ids are new" in text  # 5 prints, 2 cards, a set, a sealed product
