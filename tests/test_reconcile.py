import random
import uuid

import pytest

import ids
import reconcile
import ygjson


def test_parse_key_with_empty_number():
    f = reconcile.parse_key("mattel-action-figure-promotional-cards-series-3:98585345::normal_parallel_rare")
    assert (f.set, f.card, f.number, f.rarity, f.variant) == ("mattel-action-figure-promotional-cards-series-3", "98585345", "", "normal_parallel_rare", None)


def test_parse_key_round_trips_a_joined_variant():
    key = "quarter-century-bonanza:24094653:RA03-EN051:collectors_rare:a-alternate-art"
    f = reconcile.parse_key(key)
    assert f.variant == "a-alternate-art"
    assert ygjson.print_id(f.set, f.card, f.number, f.rarity, f.variant) == key


def test_parse_key_keeps_products_and_rejects_short_keys():
    assert reconcile.parse_key("s:1:N:r", [3, 3, 2]).products == frozenset({2, 3})
    with pytest.raises(ValueError):
        reconcile.parse_key("s:1:N")


def test_rekey_card_swaps_a_placeholder_for_its_passcode():
    assert reconcile.rekey_card("s:101403001:X-EN001:rare", {"101403001": "82951145"}) == "s:82951145:X-EN001:rare"
    assert reconcile.rekey_card("s:5:X-EN001:rare", {}) == "s:5:X-EN001:rare"


def test_current_prints_reads_products_and_sorts():
    files = {"a.json": {"cards": [{"id": "5", "prints": [
        {"id": "s:5:B-1:rare", "set": "s", "number": "B-1", "rarity": "rare", "identifiers": {"tcgplayerProductIds": [9, 8]}},
        {"id": "s:5:A-1:rare:blue", "set": "s", "number": "A-1", "rarity": "rare", "variant": "blue"}]}]}}
    got = reconcile.current_prints(files)
    assert [p.key for p in got] == ["s:5:A-1:rare:blue", "s:5:B-1:rare"]
    assert got[0].products == frozenset() and got[1].products == frozenset({8, 9})


# --- reconcile_prints ---------------------------------------------------------------------------------------------


def live(key, id_, products=(), former=()):
    return {"id": id_, "key": key, "formerKeys": list(former), "status": "live", "successors": [], "products": sorted(products)}


def retired(key, id_, products=(), former=(), successors=()):
    return {**live(key, id_, products, former), "status": "retired", "successors": list(successors)}


def ledger(*entries):
    return {e["id"]: e for e in entries}


def cur(*keys, products=None):
    products = products or {}
    return [reconcile.parse_key(k, products.get(k, ())) for k in keys]


def test_first_run_mints_every_print():
    got, by_key, review = reconcile.reconcile_prints({}, cur("s:1:S-EN001:rare", "s:2:S-EN002:common", products={"s:1:S-EN001:rare": [7, 5]}))
    a, b = ids.mint("s:1:S-EN001:rare", set()), ids.mint("s:2:S-EN002:common", set())
    assert by_key == {"s:1:S-EN001:rare": a, "s:2:S-EN002:common": b}
    assert got == ledger(live("s:1:S-EN001:rare", a, [5, 7]), live("s:2:S-EN002:common", b))
    assert review == []


def test_unchanged_print_keeps_its_id_and_entry():
    before = ledger(live("s:1:S-EN001:rare", "id-a", [5]))
    got, by_key, review = reconcile.reconcile_prints(before, cur("s:1:S-EN001:rare", products={"s:1:S-EN001:rare": [5]}))
    assert got == before and got["id-a"] is not before["id-a"]
    assert by_key == {"s:1:S-EN001:rare": "id-a"}
    assert review == []


def test_rarity_correction_keeps_the_id():
    old, new = "l5dd:5:L5DD-ENA12:unknown", "l5dd:5:L5DD-ENA12:common"
    got, by_key, review = reconcile.reconcile_prints(ledger(live(old, "id-a")), cur(new))
    assert by_key == {new: "id-a"}
    assert got == ledger(live(new, "id-a", former=[old]))
    assert review == []


def test_variant_split_follows_the_product():
    old = "qcb:9:RA04-EN109:platinum_secret_rare"
    fourth, seventh = old + ":4th-art", old + ":7th-art"
    got, by_key, review = reconcile.reconcile_prints(ledger(live(old, "id-a", [100])),
                                                     cur(fourth, seventh, products={fourth: [100], seventh: [101]}))
    minted = ids.mint(seventh, {"id-a"})
    assert by_key == {fourth: "id-a", seventh: minted}
    assert got == ledger(live(fourth, "id-a", [100], former=[old]), live(seventh, minted, [101]))
    assert review == []


def test_split_without_evidence_retires_with_both_successors():
    old, secret, starlight = "ch02:3:CH02-EN003:unknown", "ch02:3:CH02-EN003:secret_rare", "ch02:3:CH02-EN003:starlight_rare"
    got, by_key, review = reconcile.reconcile_prints(ledger(live(old, "id-a")), cur(secret, starlight))
    s, t = ids.mint(secret, {"id-a"}), ids.mint(starlight, {"id-a"})
    assert by_key == {secret: s, starlight: t}
    assert got["id-a"] == retired(old, "id-a", successors=sorted([s, t]))
    assert got[s] == live(secret, s) and got[t] == live(starlight, t)
    assert review == [{"id": "id-a", "key": old, "reason": "retired", "successors": sorted([s, t])}]


def test_letter_becoming_the_base_print_keeps_the_id():
    base = "qcb:24094653:RA03-EN051:collectors_rare"
    got, by_key, review = reconcile.reconcile_prints(ledger(live(base + ":a", "id-a"), live(base + ":b", "id-b")), cur(base, base + ":b"))
    assert by_key == {base: "id-a", base + ":b": "id-b"}
    assert got == ledger(live(base, "id-a", former=[base + ":a"]), live(base + ":b", "id-b"))
    assert review == []


def test_same_card_in_another_set_keeps_the_id():
    old = "wcs-2025-limited-pack:33396948:25LP-EN000:secret_rare"
    new = "limited-pack-world-championship-2025:33396948:25LP-EN000:secret_rare"
    got, by_key, review = reconcile.reconcile_prints(ledger(live(old, "id-a")), cur(new))
    assert by_key == {new: "id-a"}
    assert got == ledger(live(new, "id-a", former=[old]))
    assert review == []


def test_number_change_retires_with_the_new_print_as_successor():
    old, new = "s:1:X-EN001:rare", "s:1:X-EN002:rare"
    got, by_key, review = reconcile.reconcile_prints(ledger(live(old, "id-a")), cur(new))
    minted = ids.mint(new, {"id-a"})
    assert by_key == {new: minted}
    assert got == ledger(retired(old, "id-a", successors=[minted]), live(new, minted))
    assert review == [{"id": "id-a", "key": old, "reason": "retired", "successors": [minted]}]


def test_flip_back_revives_the_retired_id():
    k1, k2 = "s:1:X-EN001:rare", "s:1:X-EN001:super_rare"
    before = ledger(retired(k1, "id-old", [3], successors=["id-x"]), retired("s:2:Y-EN001:rare", "id-y", former=[k2]),
                    live("s:9:Z-EN001:rare", "id-x"))
    got, by_key, review = reconcile.reconcile_prints(before, cur(k1, k2, "s:9:Z-EN001:rare", products={k1: [4]}))
    assert by_key == {k1: "id-old", k2: "id-y", "s:9:Z-EN001:rare": "id-x"}
    assert got["id-old"] == live(k1, "id-old", [4])
    assert got["id-y"] == live(k2, "id-y", former=[k2, "s:2:Y-EN001:rare"])
    assert review == []


def test_former_key_of_a_live_print_does_not_revive():
    k1, k2 = "s:1:X-EN001:unknown", "s:1:X-EN001:rare"
    live_id = ids.mint(k1, set())
    got, by_key, review = reconcile.reconcile_prints(ledger(live(k2, live_id, former=[k1])), cur(k1, k2))
    second = str(uuid.uuid5(ids.YGJSON_NAMESPACE, k1 + "#2"))
    assert by_key == {k1: second, k2: live_id}
    assert got == ledger(live(k2, live_id, former=[k1]), live(k1, second))
    assert review == []


def test_hand_decision_revives_a_retired_id():
    old, new = "s:1:X-EN001:rare", "t:1:Y-EN009:ultra_rare"
    got, by_key, review = reconcile.reconcile_prints(ledger(retired(old, "id-a", successors=["id-z"])), cur(new), hand={new: "id-a"})
    assert by_key == {new: "id-a"}
    assert got == ledger(live(new, "id-a", former=[old]))
    assert review == []


def test_hand_decision_naming_a_live_or_unknown_id_is_ignored_and_reviewed():
    a, b = "s:1:X-EN001:rare", "t:1:Y-EN009:ultra_rare"
    before = ledger(live("s:1:X-EN001:rare", "id-live"))
    got, by_key, review = reconcile.reconcile_prints(before, cur(a, b), hand={b: "id-live", "t:2:Q:rare": "id-nope"})
    minted = ids.mint(b, {"id-live"})
    assert by_key == {a: "id-live", b: minted}
    assert got == ledger(live(a, "id-live"), live(b, minted))
    assert review == [{"id": "id-live", "key": b, "reason": "bad-hand-decision", "successors": []}]


def test_placeholder_card_prints_follow_the_passcode():
    old, new = "s:101403001:X:rare", "s:82951145:X:rare"
    got, by_key, review = reconcile.reconcile_prints(ledger(live(old, "id-a", [8])), cur(new, products={new: [8]}),
                                                     card_successor={"101403001": "82951145"})
    assert by_key == {new: "id-a"}
    assert got == ledger(live(new, "id-a", [8], former=[old]))
    assert review == []


def test_two_retired_entries_with_the_key_revive_the_smallest_id():
    k = "s:1:X-EN001:rare"
    before = ledger(retired("s:1:X-EN001:common", "id-b", former=[k]), retired(k, "id-c"), retired("s:1:X-EN001:super_rare", "id-a", former=[k]))
    got, by_key, review = reconcile.reconcile_prints(before, cur(k))
    assert by_key == {k: "id-a"}
    assert got["id-a"] == live(k, "id-a", former=[k, "s:1:X-EN001:super_rare"])
    assert got["id-b"] == before["id-b"] and got["id-c"] == before["id-c"]
    assert review == [{"id": "id-a", "key": k, "reason": "ambiguous-revival", "successors": []}]


def test_product_split_across_two_newcomers_retires():
    old, a, b = "s:1:X:rare", "s:1:X:rare:4th-art", "s:1:X:rare:7th-art"
    got, by_key, review = reconcile.reconcile_prints(ledger(live(old, "id-a", [100, 101])), cur(a, b, products={a: [100], b: [101]}))
    assert "id-a" not in by_key.values()
    assert got["id-a"]["status"] == "retired" and got["id-a"]["successors"] == sorted(by_key.values())
    assert [r["reason"] for r in review] == ["retired"]


def test_retired_successors_fall_back_to_card_and_number_then_corrected_number():
    gone, moved = "s:1:X-EN001:rare", "t:1:X-EN001:super_rare"
    got, by_key, _ = reconcile.reconcile_prints(ledger(live(gone, "id-a"), live("u:2:Q:rare", "id-q")), cur(moved, "u:2:R:rare"))
    assert got["id-a"]["successors"] == [by_key[moved]]
    assert got["id-q"]["successors"] == [by_key["u:2:R:rare"]]


def test_reconcile_does_not_mutate_its_input():
    before = ledger(live("s:1:X-EN001:unknown", "id-a"), live("s:2:Y:rare", "id-b"))
    snapshot = {k: {**v, "formerKeys": list(v["formerKeys"])} for k, v in before.items()}
    reconcile.reconcile_prints(before, cur("s:1:X-EN001:rare", "s:3:Z:rare"))
    assert before == snapshot


def test_reconcile_is_deterministic():
    keys = ["s:1:X-EN001:unknown", "s:1:X-EN001:rare", "s:1:X-EN001:super_rare", "s:2:Y:rare", "t:3:Z:rare", "s:4:W:rare:4th-art"]
    entries = [live("s:1:X-EN001:unknown", "id-a"), live("s:2:Y:old", "id-b"), live("s:4:W:rare", "id-c", [9]),
               retired("t:3:Z:rare", "id-d"), live("s:5:V:rare", "id-e")]
    products = {"s:4:W:rare:4th-art": [9]}
    want = reconcile.reconcile_prints(ledger(*entries), cur(*keys, products=products))
    rng = random.Random(4)
    for _ in range(5):
        rng.shuffle(keys)
        rng.shuffle(entries)
        got = reconcile.reconcile_prints(ledger(*entries), cur(*keys, products=products))
        assert got == want
        assert list(got[0]) == list(want[0]) and list(got[1]) == list(want[1])


def test_rule2_refuses_a_product_another_current_print_holds():
    gone, back, new = "s:1:A:rare", "t:2:B:rare", "u:3:C:rare"
    before = ledger(live(gone, "id-a", [100]), retired(back, "id-b", [7]))
    got, by_key, review = reconcile.reconcile_prints(before, cur(back, new, products={back: [100], new: [100]}))
    minted = ids.mint(new, {"id-a", "id-b"})
    assert by_key == {back: "id-b", new: minted}
    assert got["id-a"] == retired(gone, "id-a", [100])
    assert review == [{"id": "id-a", "key": gone, "reason": "retired", "successors": []}]

    kept = "t:2:B:rare"
    got, by_key, review = reconcile.reconcile_prints(ledger(live(gone, "id-a", [100]), live(kept, "id-k", [100])),
                                                     cur(kept, new, products={kept: [100], new: [100]}))
    assert by_key == {kept: "id-k", new: ids.mint(new, {"id-a", "id-k"})}
    assert got["id-a"]["status"] == "retired"
    assert [r["id"] for r in review] == ["id-a"]


def test_unnumbered_print_in_another_set_does_not_keep_the_id():
    old, new = "promo-a:5::ultra_rare", "promo-b:5::ultra_rare"
    got, by_key, review = reconcile.reconcile_prints(ledger(live(old, "id-a")), cur(new))
    minted = ids.mint(new, {"id-a"})
    assert by_key == {new: minted}
    assert got == ledger(retired(old, "id-a"), live(new, minted))
    assert review == [{"id": "id-a", "key": old, "reason": "retired", "successors": []}]


def _card(cid, name, konami=None):
    return {"id": cid, "name": name, "identifiers": {"konamiId": konami} if konami else {}}


def test_placeholder_card_retires_to_its_passcode():
    entries = {"101403001": {"id": "101403001", "name": "Helpoemer, Chanter of the Sun God", "status": "live", "successors": []}}
    new, succ, review = reconcile.reconcile_cards(entries, [_card("82951145", "Helpoemer, Chanter of the Sun God")])
    assert new["101403001"]["status"] == "retired" and new["101403001"]["successors"] == ["82951145"]
    assert succ == {"101403001": "82951145"} and review == []
    assert new["82951145"] == {"id": "82951145", "name": "Helpoemer, Chanter of the Sun God", "status": "live",
                               "successors": []}
    assert entries["101403001"]["status"] == "live"


def test_retired_card_with_two_namesakes_has_no_successor_and_goes_to_review():
    entries = {"1": {"id": "1", "name": "Twin", "status": "live", "successors": []}}
    new, succ, review = reconcile.reconcile_cards(entries, [_card("3", "Twin"), _card("2", "Twin")])
    assert new["1"]["status"] == "retired" and new["1"]["successors"] == [] and succ == {}
    assert review == [{"id": "1", "name": "Twin", "reason": "retired", "successors": ["2", "3"]}]


def test_retired_card_falls_back_to_konami_id_then_to_review_with_none():
    entries = {"1": {"id": "1", "name": "Old", "konamiId": 9, "status": "live", "successors": []},
               "5": {"id": "5", "name": "Lost", "status": "live", "successors": []}}
    new, succ, review = reconcile.reconcile_cards(entries, [_card("2", "New", 9)])
    assert new["1"]["successors"] == ["2"] and succ == {"1": "2"}
    assert review == [{"id": "5", "name": "Lost", "reason": "retired", "successors": []}]


def test_card_entry_records_name_and_konami_id():
    entries = {"2": {"id": "2", "name": "Old name", "konamiId": 7, "status": "live", "successors": []}}
    new, _, _ = reconcile.reconcile_cards(entries, [_card("2", "New name", 8), _card("3", "X")])
    assert new["2"] == {"id": "2", "name": "New name", "konamiId": 8, "status": "live", "successors": []}
    assert "konamiId" not in new["3"]
    kept, _, _ = reconcile.reconcile_cards(entries, [_card("2", "New name")])
    assert kept["2"]["konamiId"] == 7


def test_retired_entry_stays_quiet_and_comes_back_live():
    entries = {"1": {"id": "1", "name": "A", "status": "retired", "successors": ["2"]},
               "4": {"id": "4", "name": "B", "status": "retired", "successors": []}}
    new, succ, review = reconcile.reconcile_cards(entries, [_card("4", "B")])
    assert new["1"] == entries["1"] and succ == {} and review == []
    assert new["4"]["status"] == "live" and new["4"]["successors"] == []
