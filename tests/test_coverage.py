import tcgcsv

import coverage


def prod(product_id, group_id, name, **extended):
    return tcgcsv.Product(product_id, group_id, name, name, "", "", extended)


def single(product_id, group_id):
    return prod(product_id, group_id, "Card", Number="X-1", Rarity="Rare")


def test_every_product_is_counted_once_in_the_first_place_that_holds_it():
    groups = [{"groupId": 1, "publishedOn": "2020-01-01T00:00:00"}, {"groupId": 2, "publishedOn": "2099-01-01T00:00:00"},
              {"groupId": 3, "publishedOn": "2020-01-01T00:00:00"}]
    products = {
        1: [single(1, 1), single(2, 1), single(3, 1), single(4, 1), prod(5, 1, "Legend Booster Pack"),
            prod(6, 1, "Legend Playmat"), single(7, 1)],
        2: [prod(8, 2, "Future Box"), single(9, 2)],
        3: [prod(10, 3, "Lost Tin"), single(11, 3)],
    }
    sets = [{"id": "lob", "tcgplayerGroupIds": [1]}]
    files = {"000": {"cards": [{"prints": [
        {"identifiers": {"tcgplayerProductIds": [1, 2]}, "tcgplayer": {"match": "number+rarity"}},
        {"identifiers": {"tcgplayerProductIds": [3]}, "tcgplayer": {"match": "number"}},
        {"identifiers": {"tcgplayerProductIds": [9]}, "tcgplayer": {"match": "number-other-set"}}, {}]}]}}
    sealed = {"lob": {"products": [{"identifiers": {"tcgplayerProductIds": [5]}}]}}
    review = {"unmatched": [{"productId": 4}, {"productId": 11}], "conflicts": [{"productId": 7}]}
    sealed_review = {"noSet": [{"productId": 10}]}
    tally, missing = coverage.classify(groups, products, sets, files, sealed, review, sealed_review, "2026-10-28")
    assert dict(tally) == {("single", "print:number+rarity"): 2, ("single", "print:number"): 1,
                           ("single", "print:number-other-set"): 1, ("single", "review"): 3, ("sealed", "sealed"): 1,
                           ("sealed", "accessory"): 1, ("sealed", "pending"): 1, ("sealed", "review"): 1}
    assert missing == []


def test_pending_needs_a_group_with_no_set_published_after_today():
    groups = [{"groupId": 1, "publishedOn": "2099-01-01T00:00:00"}, {"groupId": 2, "publishedOn": "2099-01-01T00:00:00"},
              {"groupId": 3, "publishedOn": "2026-10-28T20:00:06.4640695Z"}]
    products = {1: [single(1, 1)], 2: [single(2, 2)], 3: [single(3, 3)]}
    sets = [{"id": "future", "tcgplayerGroupIds": [1]}]
    tally, missing = coverage.classify(groups, products, sets, {}, {}, {}, {}, "2026-10-28")
    # Group 1 has a set, so it is not pending; group 2 is pending; group 3 was published today, so it is not.
    assert dict(tally) == {("single", "pending"): 1, ("single", "UNACCOUNTED"): 2}
    assert [m[0] for m in missing] == [1, 3]


def test_strict_exits_1_when_something_is_unaccounted_for(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(coverage.tcgcsv, "groups", lambda cache: [{"groupId": 1, "publishedOn": "2020-01-01T00:00:00"}])
    monkeypatch.setattr(coverage.tcgcsv, "products", lambda gid, cache: [single(1, 1)])
    monkeypatch.setattr(coverage.ygjson, "load_sets", lambda: [])
    monkeypatch.setattr(coverage.ygjson, "load_cards", lambda: {})
    monkeypatch.setattr(coverage.ygjson, "load_sealed", lambda: {})
    monkeypatch.setattr(coverage.import_tcgcsv, "REVIEW", tmp_path / "none.json")
    monkeypatch.setattr(coverage.import_sealed, "REVIEW", tmp_path / "none2.json")
    import sys
    import pytest
    monkeypatch.setattr(sys, "argv", ["coverage.py"])
    coverage.main()
    assert "1 unaccounted for" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["coverage.py", "--strict"])
    with pytest.raises(SystemExit) as e:
        coverage.main()
    assert e.value.code == 1
