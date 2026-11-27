import copy
import json
import subprocess

import pytest
from test_ygjson import ARCHETYPES, CARD, PRINT_A, SEALED, SET, SETS

import ids
import seed_ids

FIXED = f"{SET}:46986414:LOB-EN005:secret_rare"  # PRINT_A after its rarity is corrected


def _git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                          cwd=repo, check=True, capture_output=True, text=True).stdout


def _write(repo, path, doc):
    file = repo / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(doc), encoding="utf-8")


def _commit(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path):
    """Three commits: a scaffold with no data; the fixture data without sealed products or set aliases; then PRINT_A's
    rarity fixed, with sealed products and an alias mapping added."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "README.md").write_text("scaffold\n", encoding="utf-8")
    _commit(repo, "scaffold")
    _write(repo, "sets/sets.json", SETS)
    _write(repo, "data/cards/046.json", {"cards": [CARD]})
    _write(repo, "data/archetypes.json", ARCHETYPES)
    _commit(repo, "data")
    card = copy.deepcopy(CARD)
    card["prints"][0].update(id=FIXED, rarity="secret_rare")
    _write(repo, "data/cards/046.json", {"cards": [card]})
    _write(repo, f"data/sealed/{SET}.json", SEALED[SET])
    _write(repo, "mappings/ygoprodeck_set_aliases.json", {"old-lob": {"set": SET, "why": "same set"}})
    _commit(repo, "fix the rarity")
    return repo


def _release(tmp_path, data):
    out = tmp_path / "release"
    _write(out, "AllPrintings.json", {"meta": {"version": "0.1.0"}, "data": data})
    return out


def test_seed_carries_the_id_across_a_rarity_fix(repo):
    history = seed_ids.commits("HEAD", root=repo)
    assert len(history) == 3 and history[-1] == _git(repo, "rev-parse", "HEAD").strip()
    assert seed_ids.snapshot(history[0], root=repo) == ([], {}, {"archetypes": []}, {}, {})
    assert seed_ids.snapshot(history[2], root=repo)[4] == {"old-lob": SET}

    ledger, review = seed_ids.seed(history, {}, root=repo)

    born = ids.mint(PRINT_A, set())
    entry = ledger["prints"][born]
    assert entry["key"] == FIXED and entry["formerKeys"] == [PRINT_A] and entry["status"] == "live"
    assert len(ledger["prints"]) == 2 and all(e["status"] == "live" for e in ledger["prints"].values())
    printing = ledger["printings"][f"{born}:en:first"]
    assert printing["key"] == f"{FIXED}:en:first" and printing["formerIds"] == [f"{PRINT_A}:en:first"]
    assert set(ledger["sealed"]) == {"lob-booster-pack"} and set(ledger["sets"]) == {SET}
    assert review == {"prints": [], "cards": [], "renames": []}


def test_seed_review_is_the_final_ledgers(repo):
    card = copy.deepcopy(CARD)
    card["prints"] = [{**CARD["prints"][1], "id": f"{SET}:46986414:LOB-EN105:common", "number": "LOB-EN105"}]
    _write(repo, "data/cards/046.json", {"cards": [card]})
    _commit(repo, "renumber the common, drop the secret")

    ledger, review = seed_ids.seed(seed_ids.commits("HEAD", root=repo), {}, root=repo)

    assert review == ids.review_body(ledger, set(), [])
    born = ids.mint(PRINT_A, set())
    assert review["prints"] == [{"id": born, "key": FIXED, "reason": "dead-end", "successors": []}]


def test_seed_records_release_printing_ids_as_former_ids(repo, tmp_path):
    born = ids.mint(PRINT_A, set())
    release = _release(tmp_path, {
        f"{PRINT_A}:en:first": {"print": PRINT_A, "language": "en", "edition": "first"},  # built on main: known
        "old-build:en:unlimited": {"print": PRINT_A, "language": "en", "edition": "unlimited"},
        "branch-only:en:first": {"print": f"{SET}:1:LOB-EN099:common", "language": "en", "edition": "first"},
        "dropped-edition": {"print": PRINT_A, "language": "en", "edition": "limited"},
    })

    ledger, review = seed_ids.seed(seed_ids.commits("HEAD", root=repo), {"v0.1.0": release}, root=repo)

    assert ledger["printings"][f"{born}:en:first"]["formerIds"] == [f"{PRINT_A}:en:first"]
    assert ledger["printings"][f"{born}:en:unlimited"]["formerIds"] == [f"{PRINT_A}:en:unlimited",
                                                                         "old-build:en:unlimited"]
    assert review["unresolved"] == ["branch-only:en:first", "dropped-edition"]


def test_seed_refuses_a_non_empty_ledger(repo, tmp_path, capsys):
    ledger = {k: {} for k in ids.KINDS}
    ledger["sealed"] = {"x": {"id": "x", "tcgplayerProductId": 1, "status": "live", "successors": []}}
    ids.save_ledger(ledger, repo / "ids")
    before = {p.name: p.read_bytes() for p in (repo / "ids").iterdir()}

    with pytest.raises(SystemExit) as e:
        seed_ids.main(["--rev", "HEAD"], root=repo)

    assert e.value.code == 2
    assert {p.name: p.read_bytes() for p in (repo / "ids").iterdir()} == before
    assert not (repo / "review").exists()
    assert "ids/" in capsys.readouterr().err


def test_seed_cli_writes_the_ledger_and_exits_1_on_unresolved(repo, tmp_path, capsys):
    release = _release(tmp_path, {"branch-only:en:first": {"print": "nope:1:X:common", "language": "en",
                                                           "edition": "first"}})

    with pytest.raises(SystemExit) as e:
        seed_ids.main(["--rev", "HEAD", "--release", f"v0.1.0={release}"], root=repo)

    assert e.value.code == 1
    assert ids.load_ledger(repo / "ids") == seed_ids.seed(seed_ids.commits("HEAD", root=repo),
                                                          {"v0.1.0": release}, root=repo)[0]
    assert json.loads((repo / "review" / "ids.json").read_text())["unresolved"] == ["branch-only:en:first"]
    out = capsys.readouterr().out
    assert "prints 2 live 0 retired" in out and "1 unresolved" in out
