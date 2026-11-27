import pytest

import validate
import ygjson


def test_a_print_naming_a_missing_set_is_reported_without_a_traceback(monkeypatch, capsys):
    card = {"id": "1", "name": "A", "prints": [{"id": "nope:1:X-001:common", "set": "nope", "number": "X-001",
                                               "rarity": "common"}]}
    monkeypatch.setattr(ygjson, "load_sets", lambda: [])
    monkeypatch.setattr(ygjson, "load_eras", lambda: [])
    monkeypatch.setattr(ygjson, "load_cards", lambda: {"000": {"cards": [card]}})
    monkeypatch.setattr(ygjson, "load_archetypes", lambda: {"archetypes": []})
    monkeypatch.setattr(ygjson, "load_sealed", lambda: {})
    monkeypatch.setattr(ygjson, "load_legality", lambda: {"formats": [], "events": []})
    monkeypatch.setattr(ygjson, "validate", lambda *a: ["print nope:1:X-001:common: set nope does not exist"])
    monkeypatch.setattr("sys.argv", ["validate.py"])
    with pytest.raises(SystemExit) as stop:
        validate.main()
    assert stop.value.code == 1
    assert capsys.readouterr().out.splitlines() == ["print nope:1:X-001:common: set nope does not exist", "1 problems"]
