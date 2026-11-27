import json
import uuid

import pytest

import ids

PRINT = {"id": "7d674373-b170-5fd8-ab33-29bacad29ffa", "key": "lob:89631139:LOB-001:ultra_rare", "formerKeys": [],
         "status": "live", "successors": [], "products": [1, 2]}


def test_mint_is_uuid5_of_the_birth_key():
    assert ids.mint("lob:89631139:LOB-001:ultra_rare", set()) == str(uuid.uuid5(ids.YGJSON_NAMESPACE, "lob:89631139:LOB-001:ultra_rare"))


def test_mint_skips_a_taken_id():
    first = ids.mint("k", set())
    assert ids.mint("k", {first}) == str(uuid.uuid5(ids.YGJSON_NAMESPACE, "k#2"))
    second = ids.mint("k", {first})
    assert ids.mint("k", {first, second}) == str(uuid.uuid5(ids.YGJSON_NAMESPACE, "k#3"))


def test_namespace_is_the_project_url_uuid():
    assert ids.YGJSON_NAMESPACE == uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/ArthurG-data/ygjson")


def test_ledger_round_trips_sorted(tmp_path):
    ledger = {k: {} for k in ids.KINDS}
    ledger["prints"] = {"b": {"id": "b", "key": "x", "formerKeys": [], "status": "live", "successors": [], "products": []},
                        "a": {"id": "a", "key": "y", "formerKeys": [], "status": "live", "successors": [], "products": []}}
    ids.save_ledger(ledger, tmp_path)
    assert [e["id"] for e in json.loads((tmp_path / "prints.json").read_text())["prints"]] == ["a", "b"]
    assert ids.load_ledger(tmp_path) == ledger


def test_missing_ledger_loads_empty(tmp_path):
    assert ids.load_ledger(tmp_path) == {k: {} for k in ids.KINDS}


def _ledger():
    base = {"status": "live", "successors": []}
    return {
        "prints": {PRINT["id"]: PRINT},
        "printings": {"x": {"id": PRINT["id"] + ":en:first", "key": "k:en:first", "formerIds": ["k:en:first"], **base}},
        "cards": {"1": {"id": "1", "name": "Blue-Eyes", "konamiId": 4007, **base}},
        "sets": {"lob": {"id": "lob", "names": ["Legend of Blue Eyes"], "code": "LOB", "releaseDate": "2002-03-08",
                         "identity": ["a", "b"], **base}},
        "archetypes": {"hero": {"id": "hero", "names": ["HERO"], "identity": ["x"], **base}},
        "sealed": {"1": {"id": "lob-box", "tcgplayerProductId": 5, **base}},
    }


def test_ledger_entries_match_the_schema():
    ledger = _ledger()
    assert ids.schema_errors(ledger) == []
    ledger["prints"][PRINT["id"]] = {**PRINT, "status": "gone"}
    assert ids.schema_errors(ledger)


def test_schema_rejects_a_bad_printing_id():
    ledger = _ledger()
    ledger["printings"]["x"]["id"] = "not-a-uuid:en:first"
    assert ids.schema_errors(ledger)


def test_held_names_and_reserved_cover_live_and_retired_entries():
    ledger = {"sets": {"b": {"id": "b", "names": ["Old", "New"], "status": "live", "successors": []},
                       "a": {"id": "a", "names": ["Gone", "New"], "status": "retired", "successors": []}}}
    assert ids.held_names(ledger, "sets") == {"Old": "b", "New": "a", "Gone": "a"}  # a name under two slugs: smallest
    assert ids.reserved(ledger, "sets") == {"a", "b"}
    assert ids.held_names(ledger, "archetypes") == {} and ids.reserved(ledger, "archetypes") == set()


def _hand_ledger():
    base = {"formerKeys": [], "products": []}
    return {"prints": {
        "live1": {"id": "live1", "key": "k1", "status": "live", "successors": [], **base},
        "gone1": {"id": "gone1", "key": "k2", "status": "retired", "successors": [], **base},
        "gone2": {"id": "gone2", "key": "k3", "status": "retired", "successors": [], **base}}}


def _write_hand(tmp_path, doc):
    path = tmp_path / "ids.json"
    path.write_text(json.dumps(doc))
    return path


def test_hand_entry_without_why_is_refused(tmp_path):
    path = _write_hand(tmp_path, {"_comment": "c", "prints": {"k9": {"id": "gone1", "why": " "}}, "successors": {}})
    with pytest.raises(ValueError, match="k9"):
        ids.load_hand(path)
    path = _write_hand(tmp_path, {"prints": {}, "successors": {"gone1": {"successors": ["live1"]}}})
    with pytest.raises(ValueError, match="gone1"):
        ids.load_hand(path)


def test_missing_hand_file_is_empty(tmp_path):
    assert ids.load_hand(tmp_path / "nope.json") == ({}, {})


def test_hand_may_not_give_a_live_id_to_a_second_print(tmp_path):
    path = _write_hand(tmp_path, {"prints": {"a": {"id": "live1", "why": "w"}, "b": {"id": "ghost", "why": "w"},
                                            "c": {"id": "gone1", "why": "w"}},
                                  "successors": {"live1": {"successors": ["gone1"], "why": "w"},
                                                 "gone2": {"successors": ["ghost"], "why": "w"},
                                                 "gone1": {"successors": ["live1"], "why": "w"}}})
    hand = ids.load_hand(path)
    assert hand == ({"a": "live1", "b": "ghost", "c": "gone1"},
                    {"live1": ["gone1"], "gone2": ["ghost"], "gone1": ["live1"]})
    errors = ids.hand_errors(_hand_ledger(), hand)
    assert len(errors) == 4
    assert any("a" in e and "live1" in e for e in errors)
    assert any("ghost" in e for e in errors)
    assert not any("'c'" in e for e in errors)


def test_hand_successors_override_the_computed_ones():
    entries = _hand_ledger()["prints"]
    out = ids.apply_successors(entries, {"gone1": ["live1"], "live1": ["gone1"]})
    assert out["gone1"]["successors"] == ["live1"]
    assert out["live1"]["successors"] == []
    assert entries["gone1"]["successors"] == []


def _p(id_, status="live", successors=()):
    return {"id": id_, "key": f"k-{id_}", "formerKeys": [], "status": status, "successors": list(successors),
            "products": []}


def _c(id_, status="live", successors=()):
    return {"id": id_, "name": f"n-{id_}", "status": status, "successors": list(successors)}


def test_review_lists_the_retired_ids_that_do_not_reach_exactly_one_live_id():
    prints = {e["id"]: e for e in [
        _p("live1"), _p("live2"),
        _p("one", "retired", ["live1"]),                  # one live successor: settled by itself
        _p("chain", "retired", ["one"]),                  # through a retired id to one live id: settled
        _p("dead", "retired"),                            # nothing: dead end
        _p("deadchain", "retired", ["dead"]),             # through a dead end: dead end
        _p("split", "retired", ["live2", "live1"]),       # two live ids: several
        _p("wide", "retired", ["split", "one"]),          # reaches live1 and live2: several
        _p("loop", "retired", ["loop2"]), _p("loop2", "retired", ["loop"]),  # a cycle reaches nothing
        _p("handed", "retired", ["live1", "live2"]),      # settled by mappings/ids.json
    ]}
    cards = {e["id"]: e for e in [_c("9"), _c("1", "retired", ["9"]), _c("2", "retired")]}
    body = ids.review_body({"prints": prints, "cards": cards}, {"handed"},
                           [{"from": "q", "to": "r", "name": "Q"}, {"from": "p", "to": "s", "name": "P"}])
    assert body["prints"] == [
        {"id": "dead", "key": "k-dead", "reason": "dead-end", "successors": []},
        {"id": "deadchain", "key": "k-deadchain", "reason": "dead-end", "successors": []},
        {"id": "loop", "key": "k-loop", "reason": "dead-end", "successors": []},
        {"id": "loop2", "key": "k-loop2", "reason": "dead-end", "successors": []},
        {"id": "split", "key": "k-split", "reason": "several", "successors": ["live1", "live2"]},
        {"id": "wide", "key": "k-wide", "reason": "several", "successors": ["live1", "live2"]},
    ]
    assert body["cards"] == [{"id": "2", "name": "n-2", "reason": "dead-end", "successors": []}]
    assert [r["from"] for r in body["renames"]] == ["p", "q"]
    assert set(body) == {"prints", "cards", "renames"}


def test_an_applied_hand_decision_keeps_check_green():
    import copy
    from test_ygjson import ARCHETYPES, CARD, PRINT_A, SEALED, SET, SETS
    files = lambda card: {"046": {"cards": [card]}}
    without_a = {**copy.deepcopy(CARD), "prints": copy.deepcopy(CARD["prints"][1:])}
    moved = copy.deepcopy(CARD)
    key = f"{SET}:46986414:LOB-EN105:ultra_rare"
    moved["prints"][0].update(id=key, number="LOB-EN105")
    ledger = {k: {} for k in ids.KINDS}
    for card in (CARD, without_a):
        ledger, _, _ = ids.run(ledger, SETS, files(card), ARCHETYPES, SEALED, ({}, {}), {})
    old = ids.mint(PRINT_A, set())
    assert ledger["prints"][old]["status"] == "retired"
    hand = ({key: old}, {})
    ledger, _, _ = ids.run(ledger, SETS, files(moved), ARCHETYPES, SEALED, hand, {})
    assert ledger["prints"][old]["status"] == "live" and ledger["prints"][old]["key"] == key
    assert ids.check(ledger, SETS, files(moved), ARCHETYPES, SEALED, hand) == []
    assert any("is live" in e for e in ids.hand_errors(ledger, ({PRINT_A: old}, {})))  # live under another key


def test_hand_may_not_give_one_retired_id_to_two_keys():
    errors = ids.hand_errors(_hand_ledger(), ({"a": "gone1", "b": "gone1"}, {}))
    assert len(errors) == 1
    assert "'a'" in errors[0] and "'b'" in errors[0] and "gone1" in errors[0]


def _fixture_run(ledger=None, sets=None):
    from test_ygjson import ARCHETYPES, CARDS, SEALED, SETS
    ledger = ledger if ledger is not None else {k: {} for k in ids.KINDS}
    return ids.run(ledger, sets or SETS, CARDS, ARCHETYPES, SEALED, ({}, {}), {})


def _fixture_check(ledger):
    from test_ygjson import ARCHETYPES, CARDS, SEALED, SETS
    return ids.check(ledger, SETS, CARDS, ARCHETYPES, SEALED)


def test_run_twice_leaves_the_ledger_byte_identical(tmp_path):
    first, review, renames = _fixture_run()
    assert renames == [] and review == {"prints": [], "cards": [], "renames": []}
    assert {k: len(v) for k, v in first.items()} == {"prints": 2, "printings": 3, "cards": 1, "sets": 1,
                                                     "archetypes": 1, "sealed": 1}
    ids.save_ledger(first, tmp_path / "a")
    second, _, _ = _fixture_run(ids.load_ledger(tmp_path / "a"))
    ids.save_ledger(second, tmp_path / "b")
    for kind in ids.KINDS:
        assert (tmp_path / "a" / f"{kind}.json").read_bytes() == (tmp_path / "b" / f"{kind}.json").read_bytes()


def test_review_comes_from_the_ledger_and_is_the_same_on_a_rerun():
    import copy
    from test_ygjson import ARCHETYPES, CARD, PRINT_A, SEALED, SET, SETS
    files = lambda card: {"046": {"cards": [card]}}
    split = copy.deepcopy(CARD)  # PRINT_A's ultra_rare becomes a secret_rare and a starlight_rare
    split["prints"][0].update(id=f"{SET}:46986414:LOB-EN005:secret_rare", rarity="secret_rare", identifiers={})
    split["prints"].append({**split["prints"][0], "id": f"{SET}:46986414:LOB-EN005:starlight_rare",
                            "rarity": "starlight_rare"})
    ledger, _, _ = ids.run({k: {} for k in ids.KINDS}, SETS, files(CARD), ARCHETYPES, SEALED, ({}, {}), {})
    ledger, review, _ = ids.run(ledger, SETS, files(split), ARCHETYPES, SEALED, ({}, {}), {})
    old = ids.mint(PRINT_A, set())
    assert [(r["id"], r["reason"], len(r["successors"])) for r in review["prints"]] == [(old, "several", 3)]
    again, rerun, _ = ids.run(ledger, SETS, files(split), ARCHETYPES, SEALED, ({}, {}), {})
    assert again == ledger and rerun == review
    _, settled, _ = ids.run(ledger, SETS, files(split), ARCHETYPES, SEALED,
                            ({}, {old: ledger["prints"][old]["successors"][:1]}), {})
    assert settled["prints"] == []


def test_check_reports_a_print_with_no_ledger_entry():
    from test_ygjson import PRINT_A
    ledger, _, _ = _fixture_run()
    assert _fixture_check(ledger) == []
    pid = next(i for i, e in ledger["prints"].items() if e["key"] == PRINT_A)
    del ledger["prints"][pid]
    errors = _fixture_check(ledger)
    assert any(PRINT_A in e and "no live ledger entry" in e for e in errors)


def test_check_reports_retired_entries_in_the_data_and_missing_successors():
    ledger, _, _ = _fixture_run()
    ledger["sets"]["legend-of-blue-eyes-white-dragon"]["status"] = "retired"
    ledger["cards"]["46986414"]["successors"] = ["nowhere"]
    ledger["sealed"]["gone-box"] = {"id": "other-box", "tcgplayerProductId": 9, "status": "live", "successors": []}
    errors = _fixture_check(ledger)
    assert any("legend-of-blue-eyes-white-dragon" in e and "retired" in e for e in errors)
    assert any("46986414" in e and "nowhere" in e for e in errors)
    assert any("gone-box" in e and "other-box" in e for e in errors)  # dict key and id disagree
    assert any("other-box" in e and "not in the data" in e for e in errors)


def test_check_includes_hand_errors():
    ledger, _, _ = _fixture_run()
    errors = ids.check(ledger, *_fixture_data(), hand=({"x:y:z:w": "ghost"}, {}))
    assert any("ghost" in e for e in errors)


def _fixture_data():
    from test_ygjson import ARCHETYPES, CARDS, SEALED, SETS
    return SETS, CARDS, ARCHETYPES, SEALED


def test_diff_errors_reports_a_removed_entry():
    before, _, _ = _fixture_run()
    after = {k: dict(v) for k, v in before.items()}
    assert ids.diff_errors(before, after) == []
    removed = next(iter(after["printings"]))
    del after["printings"][removed]
    errors = ids.diff_errors(before, after)
    assert len(errors) == 1 and "printings" in errors[0] and removed in errors[0] and "removed" in errors[0]


def test_diff_errors_reports_a_shortened_former_keys():
    before = {"prints": {"a": {**PRINT, "id": "a", "key": "k3", "formerKeys": ["k1", "k2"]}},
              "sets": {"s": {"id": "s", "names": ["One", "Two"], "status": "live", "successors": []}}}
    grown = {"prints": {"a": {**before["prints"]["a"], "key": "k4", "formerKeys": ["k1", "k2", "k3"]}},
             "sets": {"s": {**before["sets"]["s"], "names": ["One", "Two", "Three"]}}}
    assert ids.diff_errors(before, grown) == []
    after = {"prints": {"a": {**before["prints"]["a"], "formerKeys": ["k2"]}},
             "sets": {"s": {**before["sets"]["s"], "names": ["Two", "One"]}}}
    errors = ids.diff_errors(before, after)
    assert any("prints a" in e and "formerKeys" in e for e in errors)
    assert any("sets s" in e and "names" in e for e in errors)


def test_diff_errors_reports_a_changed_id_and_birth_key():
    before = {"prints": {"a": {**PRINT, "id": "a", "key": "k1", "formerKeys": []}}}
    assert any("id" in e for e in ids.diff_errors(before, {"prints": {"a": {**PRINT, "id": "b"}}}))
    reborn = {"prints": {"a": {**before["prints"]["a"], "key": "k2", "formerKeys": []}}}
    assert any("born" in e for e in ids.diff_errors(before, reborn))


def test_diff_errors_reports_a_lost_key_and_successors_shrunk_to_none():
    before = {"prints": {"a": {**PRINT, "id": "a", "key": "k2", "formerKeys": ["k1"]},
                         "r": {**PRINT, "id": "r", "key": "k9", "status": "retired", "successors": ["a"]},
                         "q": {**PRINT, "id": "q", "key": "k8", "status": "retired", "successors": ["a"]}},
              "printings": {"p": {"id": "p", "key": "k2:en:first", "formerIds": [], "status": "live",
                                  "successors": []}}}
    kept = {"prints": {"a": {**before["prints"]["a"], "key": "k3", "formerKeys": ["k1", "k2"]},
                       "r": {**before["prints"]["r"], "successors": ["a", "b"]},
                       "q": {**before["prints"]["q"], "status": "live", "successors": []}},
            "printings": {"p": {**before["printings"]["p"], "key": "k3:en:first", "formerIds": ["k2:en:first"]}}}
    assert ids.diff_errors(before, kept) == []
    lost = {"prints": {"a": {**before["prints"]["a"], "key": "k3"},
                       "r": {**before["prints"]["r"], "successors": []}, "q": before["prints"]["q"]},
            "printings": {"p": {**before["printings"]["p"], "key": "k3:en:first"}}}
    errors = ids.diff_errors(before, lost)
    assert len(errors) == 3
    assert any("prints a" in e and "'k2'" in e for e in errors)
    assert any("printings p" in e and "'k2:en:first'" in e for e in errors)
    assert any("prints r" in e and "successors" in e for e in errors)


def _cli(monkeypatch, tmp_path, ledger, sets):
    from test_ygjson import ARCHETYPES, CARDS, SEALED
    import ygjson
    monkeypatch.setattr(ids, "IDS", tmp_path / "ids")
    monkeypatch.setattr(ids, "REVIEW", tmp_path / "review" / "ids.json")
    monkeypatch.setattr(ids, "HAND", tmp_path / "mappings" / "ids.json")
    monkeypatch.setattr(ids, "SET_ALIASES", tmp_path / "mappings" / "aliases.json")
    monkeypatch.setattr(ygjson, "load_sets", lambda: sets)
    monkeypatch.setattr(ygjson, "load_cards", lambda: CARDS)
    monkeypatch.setattr(ygjson, "load_archetypes", lambda: ARCHETYPES)
    monkeypatch.setattr(ygjson, "load_sealed", lambda: SEALED)
    ids.save_ledger(ledger, tmp_path / "ids")


def test_cli_writes_the_ledger_and_the_review(monkeypatch, tmp_path, capsys):
    from test_ygjson import SETS
    _cli(monkeypatch, tmp_path, {k: {} for k in ids.KINDS}, SETS)
    ids.main([])
    assert ids.load_ledger(tmp_path / "ids") == _fixture_run()[0]
    assert json.loads((tmp_path / "review" / "ids.json").read_text()) == {"prints": [], "cards": [], "renames": []}
    assert "prints 2 live 0 retired" in capsys.readouterr().out


def test_rename_exits_3(monkeypatch, tmp_path, capsys):
    from test_ygjson import SETS
    sets = [{**SETS[0], "identifiers": {"ygojsonId": "lob-uuid"}}]
    ledger = {k: {} for k in ids.KINDS}
    ledger["sets"] = {"lob-old": {"id": "lob-old", "names": ["LOB"], "identity": ["ygojson:lob-uuid"],
                                  "status": "live", "successors": []}}
    _cli(monkeypatch, tmp_path, ledger, sets)
    with pytest.raises(SystemExit) as e:
        ids.main([])
    assert e.value.code == 3
    out = capsys.readouterr().out
    assert "lob-old" in out and "legend-of-blue-eyes-white-dragon" in out and "rerun the pipeline" in out
    saved = ids.load_ledger(tmp_path / "ids")
    assert saved["sets"]["lob-old"]["names"] == ["LOB", "Legend of Blue Eyes White Dragon"]
    assert "legend-of-blue-eyes-white-dragon" not in saved["sets"]
    review = json.loads((tmp_path / "review" / "ids.json").read_text())
    assert review["renames"] == [{"from": "lob-old", "to": "legend-of-blue-eyes-white-dragon",
                                  "name": "Legend of Blue Eyes White Dragon"}]


def test_a_rename_leaves_the_prints_alone_until_the_rerun(monkeypatch, tmp_path, capsys):
    import ygjson
    from test_ygjson import ARCHETYPES, CARDS, SEALED, SET, SETS
    named = lambda slug, name: json.loads(json.dumps(
        [[{**SETS[0], "name": name, "identifiers": {"ygojsonId": "lob-uuid"}}], CARDS, SEALED]).replace(SET, slug))
    published = named("lob-old", "LOB")  # the set as published, under its old slug
    renamed = named(SET, "Legend of Blue Eyes White Dragon")  # YGOPRODeck renamed it: the import made a new slug
    mapped = named("lob-old", "Legend of Blue Eyes White Dragon")  # the rerun maps the new name to the old slug
    ledger, _, _ = ids.run({k: {} for k in ids.KINDS}, *published[:2], ARCHETYPES, published[2], ({}, {}), {})
    _cli(monkeypatch, tmp_path, ledger, published[0])
    before = {kind: (tmp_path / "ids" / f"{kind}.json").read_bytes() for kind in ids.KINDS}

    for step in (renamed, mapped):
        monkeypatch.setattr(ygjson, "load_sets", lambda: step[0])
        monkeypatch.setattr(ygjson, "load_cards", lambda: step[1])
        monkeypatch.setattr(ygjson, "load_sealed", lambda: step[2])
        if step is renamed:
            with pytest.raises(SystemExit) as e:
                ids.main([])
            assert e.value.code == 3
            for kind in ("prints", "printings", "cards", "sealed"):
                assert (tmp_path / "ids" / f"{kind}.json").read_bytes() == before[kind]
            assert ids.load_ledger(tmp_path / "ids")["sets"]["lob-old"]["names"] == [
                "LOB", "Legend of Blue Eyes White Dragon"]
            assert json.loads((tmp_path / "review" / "ids.json").read_text())["renames"][0]["from"] == "lob-old"
        else:
            ids.main([])  # no rename left: exits normally

    saved = ids.load_ledger(tmp_path / "ids")
    assert all(e["status"] == "live" for e in saved["prints"].values())
    assert saved["prints"].keys() == ledger["prints"].keys()
    assert not [k for e in saved["prints"].values() for k in e["formerKeys"] if SET in k]
    assert not [k for e in saved["printings"].values() for k in e["formerIds"] if SET in k]
    assert ids.check(saved, *mapped[:2], ARCHETYPES, mapped[2]) == []


def _git(cwd, *args):
    import subprocess
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


def test_ledger_at_reads_a_revision_and_refuses_an_unknown_one(tmp_path):
    _git(tmp_path, "init", "-q")
    ledger = {k: {} for k in ids.KINDS}
    ledger["prints"] = {PRINT["id"]: PRINT}
    ids.save_ledger(ledger, tmp_path / "ids")
    (tmp_path / "ids" / "sealed.json").unlink()
    _git(tmp_path, "add", "ids")
    _git(tmp_path, "commit", "-q", "-m", "ledger")
    (tmp_path / "ids" / "prints.json").write_text('{"prints": []}')
    assert ids.ledger_at("HEAD", tmp_path) == ledger
    with pytest.raises(SystemExit, match="no-such-rev"):
        ids.ledger_at("no-such-rev", tmp_path)


def test_ledger_at_exits_on_a_git_failure_other_than_a_missing_file(tmp_path, monkeypatch):
    import subprocess
    _git(tmp_path, "init", "-q")
    ledger = {k: {} for k in ids.KINDS}
    ledger["prints"] = {PRINT["id"]: PRINT}
    ids.save_ledger(ledger, tmp_path / "ids")
    _git(tmp_path, "add", "ids")
    _git(tmp_path, "commit", "-q", "-m", "ledger")
    real = subprocess.run

    def broken(args, **kw):
        if args[:2] == ["git", "show"]:
            return subprocess.CompletedProcess(args, 128, b"", b"fatal: unable to read 1234abcd")
        return real(args, **kw)

    monkeypatch.setattr(ids.subprocess, "run", broken)
    with pytest.raises(SystemExit, match="unable to read"):
        ids.ledger_at("HEAD", tmp_path)


def test_a_duplicate_id_in_a_ledger_file_is_refused(tmp_path):
    (tmp_path / "prints.json").write_text(json.dumps({"prints": [PRINT, {**PRINT, "key": "other"}]}))
    with pytest.raises(ValueError, match=f"prints.*{PRINT['id']}"):
        ids.load_ledger(tmp_path)
    _git(tmp_path, "init", "-q")
    (tmp_path / "ids").mkdir()
    (tmp_path / "prints.json").rename(tmp_path / "ids" / "prints.json")
    _git(tmp_path, "add", "ids")
    _git(tmp_path, "commit", "-q", "-m", "dup")
    with pytest.raises(ValueError, match=f"prints.*{PRINT['id']}"):
        ids.ledger_at("HEAD", tmp_path)


def test_a_retired_print_whose_key_came_back_under_another_id_points_at_it():
    import copy
    from test_ygjson import ARCHETYPES, CARD, PRINT_A, SEALED, SET, SETS
    files = lambda *cards: {"046": {"cards": list(cards)}}
    placeholder = {**copy.deepcopy(CARD), "id": "ph1", "identifiers": {}}
    del placeholder["passcode"]
    placeholder["prints"] = [{**CARD["prints"][0], "id": f"{SET}:ph1:LOB-EN005:ultra_rare", "identifiers": {}}]
    without_a = {**copy.deepcopy(CARD), "prints": copy.deepcopy(CARD["prints"][1:])}
    ledger = {k: {} for k in ids.KINDS}
    for step in (files(CARD, placeholder), files(without_a, placeholder), files(CARD)):
        ledger, _, _ = ids.run(ledger, SETS, step, ARCHETYPES, SEALED, ({}, {}), {})
    holder = next(i for i, e in ledger["prints"].items() if e["status"] == "live" and e["key"] == PRINT_A)
    old = next(i for i, e in ledger["prints"].items() if e["status"] == "retired" and e["key"] == PRINT_A)
    assert holder in ledger["prints"][old]["successors"]
    assert ids.check(ledger, SETS, files(CARD), ARCHETYPES, SEALED) == []
    ledger["prints"][old]["successors"] = []
    assert any(old in e and "retired" in e for e in ids.check(ledger, SETS, files(CARD), ARCHETYPES, SEALED))
