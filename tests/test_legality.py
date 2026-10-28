import pytest

import legality

CARD, OTHER = "46986414", "89631139"


def event(card=CARD, fmt="tcg", status="limited", **kw):
    return {"card": card, "format": fmt, "status": status, "source": "ygojson", **({"effective": "2005-03-01"} | kw)}


def ygojson_card(uuid, **formats):
    return {"id": uuid, "legality": {f: {"current": cur, "history": [{"legality": s, "date": d} for s, d in hist]}
                                     for f, (cur, hist) in formats.items()}}


IDS = {"uuid-1": CARD, "uuid-2": OTHER}


def test_each_dated_history_entry_becomes_an_event():
    cards = [ygojson_card("uuid-1", tcg=("unlimited", [("forbidden", "2005-03-01"), ("limited", "2010-03-01"),
                                                       ("unlimited", "2012-03-01")]),
                          ocg=("semilimited", [("semilimited", "2008-09-01")]),
                          speed=("limit2", [("limit1", "2020-01-01"), ("limit2", "2021-01-01")])),
             ygojson_card("uuid-9", tcg=("forbidden", [("forbidden", "2005-03-01")]))]  # not one of ours
    events = legality.history_events(cards, IDS)
    assert [(e["format"], e["status"], e["effective"]) for e in sorted(events, key=lambda e: (e["format"], e["effective"]))] == [
        ("ocg", "semi_limited", "2008-09-01"), ("speed_duel", "limited", "2020-01-01"),
        ("speed_duel", "semi_limited", "2021-01-01"), ("tcg", "banned", "2005-03-01"), ("tcg", "limited", "2010-03-01"),
        ("tcg", "legal", "2012-03-01")]
    assert {e["card"] for e in events} == {CARD} and {e["source"] for e in events} == {"ygojson"}


def test_statuses_that_are_not_copies_allowed_make_no_event():
    cards = [ygojson_card("uuid-1", tcg=("unreleased", [("unreleased", "2005-03-01")]), speed=("limit3", [("limit3", "2020-01-01")]))]
    assert [(e["format"], e["status"]) for e in legality.history_events(cards, IDS)] == [("speed_duel", "legal")]


def test_lead_status_reads_banlist_info_and_defaults_to_legal():
    prodeck = [{"id": int(CARD), "banlist_info": {"ban_tcg": "Forbidden", "ban_goat": "Semi-Limited"}},
               {"id": int(OTHER)}, {"id": 1, "banlist_info": {"ban_tcg": "Limited"}}]
    lead = legality.lead_status(prodeck, [ygojson_card("uuid-1", speed=("limit1", []), tcg=("limited", []))], IDS, {CARD, OTHER})
    assert lead == {(CARD, "tcg"): "banned", (CARD, "ocg"): "legal", (CARD, "goat"): "semi_limited",
                    (OTHER, "tcg"): "legal", (OTHER, "ocg"): "legal", (OTHER, "goat"): "legal",
                    (CARD, "speed_duel"): "limited"}


def test_current_status_that_differs_from_the_last_event_gets_an_in_force_by_event():
    history = [event(status="banned"), event(status="limited", effective="2010-03-01")]
    lead = {(CARD, "tcg"): "semi_limited", (OTHER, "tcg"): "legal", (CARD, "speed_duel"): "limited"}
    events, new = legality.merge([], history, lead, "2026-10-28")
    added = [e for e in events if "inForceBy" in e]
    assert added == [{"card": CARD, "format": "speed_duel", "status": "limited", "inForceBy": "2026-10-28", "source": "ygojson"},
                     {"card": CARD, "format": "tcg", "status": "semi_limited", "inForceBy": "2026-10-28", "source": "ygoprodeck"}]
    assert (OTHER, "tcg") not in {(e["card"], e["format"]) for e in events}  # legal with no events needs none


def test_a_current_status_equal_to_the_last_event_adds_nothing():
    events, new = legality.merge([], [event(status="banned")], {(CARD, "tcg"): "banned"}, "2026-10-28")
    assert len(events) == 1 and len(new) == 1 and "effective" in events[0]


def test_a_card_whose_events_end_legal_is_not_given_a_legal_event_again():
    history = [event(status="banned"), event(status="legal", effective="2012-03-01")]
    events, new = legality.merge([], history, {(CARD, "tcg"): "legal"}, "2026-10-28")
    assert len(new) == 2


def test_existing_events_are_never_rewritten_or_removed():
    kept = event(status="banned", effective="2005-03-01")
    seen = event(fmt="goat", status="limited", effective=None)
    del seen["effective"]
    seen["inForceBy"] = "2026-01-01"
    history = [event(status="limited", effective="2005-03-01"), event(status="legal", effective="2012-03-01")]
    events, new = legality.merge([kept, seen], history, {(CARD, "goat"): "limited"}, "2026-10-28")
    assert kept in events and seen in events
    assert [e["status"] for e in events if e["format"] == "tcg"] == ["banned", "legal"]  # the 2005 history entry was not added
    assert new == [event(status="legal", effective="2012-03-01")]
    assert not [e for e in events if e.get("inForceBy") == "2026-10-28"]  # goat's status was already recorded on 2026-01-01


def test_a_second_run_changes_nothing():
    history = [event(status="banned"), event(status="limited", effective="2010-03-01")]
    lead = {(CARD, "tcg"): "legal"}
    first, _ = legality.merge([], history, lead, "2026-10-28")
    second, new = legality.merge(first, history, lead, "2026-11-30")
    assert second == first and new == []


def test_events_sort_by_numeric_card_id_then_format_then_date():
    events = [event("100", "tcg", effective="2010-01-01"), event("20", "tcg", effective="2012-01-01"),
              event("20", "ocg", effective="2015-01-01"), event("20", "tcg", effective="2011-01-01")]
    assert [(e["card"], e["format"], e["effective"]) for e in legality.sort_events(events)] == [
        ("20", "ocg", "2015-01-01"), ("20", "tcg", "2011-01-01"), ("20", "tcg", "2012-01-01"), ("100", "tcg", "2010-01-01")]


def test_current_replays_events_up_to_a_date():
    events = [event(status="banned", effective="2005-03-01"), event(status="limited", effective="2010-03-01"),
              event(fmt="goat", status="banned", inForceBy="2026-10-28", effective=None)]
    del events[2]["effective"]
    assert legality.current(events, "2004-01-01") == {}
    assert legality.current(events, "2005-03-01") == {(CARD, "tcg"): "banned"}
    assert legality.current(events, "2026-10-27") == {(CARD, "tcg"): "limited"}
    assert legality.current(events, "2026-10-28") == {(CARD, "tcg"): "limited", (CARD, "goat"): "banned"}


def test_check_reports_each_difference_and_nothing_when_they_agree():
    events = [event(status="banned"), event(status="legal", effective="2012-03-01")]
    lead = {(CARD, "tcg"): "legal", (CARD, "ocg"): "legal", (OTHER, "tcg"): "limited"}
    assert legality.check(events, lead, "2026-10-28") == [f"card {OTHER} tcg: events say legal, ygoprodeck says limited"]
    assert legality.check(events, {(CARD, "tcg"): "banned"}, "2011-01-01") == []
    assert legality.check(events, {(CARD, "speed_duel"): "limited"}, "2026-10-28") == [
        f"card {CARD} speed_duel: events say legal, ygojson says limited"]


def run_check(monkeypatch, capsys, events, prodeck):
    cards = {"046": {"cards": [{"id": CARD, "identifiers": {"ygojsonId": "uuid-1"}}]}}
    monkeypatch.setattr(legality.ygjson, "load_cards", lambda: cards)
    monkeypatch.setattr(legality.ygjson, "load_legality", lambda: {"formats": [], "events": events})
    monkeypatch.setattr(legality.ygoprodeck, "cards", lambda refresh=False: prodeck)
    monkeypatch.setattr(legality, "_load_ygojson", lambda: None)
    monkeypatch.setattr("sys.argv", ["legality.py", "--check", "--as-of", "2026-10-28"])
    with pytest.raises(SystemExit) as e:
        legality.main()
    return e.value.code, capsys.readouterr().out


def test_check_exits_1_on_a_difference_and_0_without(monkeypatch, capsys):
    events = [event(status="banned")]
    code, out = run_check(monkeypatch, capsys, events, [{"id": int(CARD), "banlist_info": {"ban_tcg": "Forbidden"}}])
    assert code == 0 and "0 differences" in out and "speed_duel not checked" in out
    code, out = run_check(monkeypatch, capsys, events, [{"id": int(CARD), "banlist_info": {"ban_tcg": "Limited"}}])
    assert code == 1 and f"card {CARD} tcg: events say banned, ygoprodeck says limited" in out
