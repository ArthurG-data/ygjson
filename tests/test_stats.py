import json
import shutil
import subprocess

import pytest
from test_ygjson import ARCHETYPES, CARDS, LEGALITY, SEALED, SETS

import stats

DATA = {"sets": SETS, "cards": CARDS, "archetypes": ARCHETYPES["archetypes"],
        "sealed": [p for body in SEALED.values() for p in body["products"]], "events": LEGALITY["events"]}


def test_counts_on_the_small_fixture():
    c = stats.counts(DATA, {"sealed": {"noSet": [{"productId": 1}], "ignored": {"noSet": [{"productId": 2}]}}})
    assert (c["sets"], c["cards"], c["prints"], c["printings"], c["prints_with_product"]) == (1, 1, 2, 3, 1)
    assert c["prints_no_product"] == 1 and c["prints_own_editions"] == 1  # PRINT_B is unlimited only
    assert c["type.booster"] == 1 and c["region.EN"] == 2 and "match.number+rarity" not in c  # no tcgplayer field
    assert c["archetypes.ygoprodeck"] == 1 and c["archetypes.no_member"] == 0  # Dark Magician has its card
    assert c["sealed.booster_pack"] == 1 and c["sealed.status.partial"] == 1 and c["sealed.no_set"] == 1
    assert c["events.tcg"] == 1 and c["events.limited"] == 1 and c["events.ygojson"] == 1


def test_render_rewrites_each_marker_and_reports_what_changed():
    text = "Holds <!--n:sets-->9<!--/n--> sets and <!--n:cards-->1<!--/n--> card.\nAlso <!--n:region.EN-->2<!--/n-->."
    new, problems = stats.render(text, {"sets": "1,066", "cards": "1", "region.EN": "2"})
    assert new == "Holds <!--n:sets-->1,066<!--/n--> sets and <!--n:cards-->1<!--/n--> card.\nAlso <!--n:region.EN-->2<!--/n-->."
    assert problems == ["README.md:1: sets is 9, the data says 1,066"]
    assert stats.render(new, {"sets": "1,066", "cards": "1", "region.EN": "2"}) == (new, [])


def test_an_unknown_key_or_a_malformed_marker_is_reported():
    assert stats.render("<!--n:nope-->1<!--/n-->", {})[1] == ["README.md: no count named 'nope'"]
    (problem,) = stats.render("<!--n:sets-->1 and no end", {"sets": "1"})[1]
    assert "1 markers are malformed" in problem


def test_every_marker_in_the_readme_names_a_known_count():
    _, problems = stats.render(stats.README.read_text(encoding="utf-8"), stats.values())
    assert [p for p in problems if "no count named" in p or "malformed" in p] == []


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    (tmp_path / "sets").mkdir()
    (tmp_path / "data" / "cards").mkdir(parents=True)
    (tmp_path / "data" / "sealed").mkdir()
    (tmp_path / "legality").mkdir()
    (tmp_path / "sets" / "sets.json").write_text(json.dumps(SETS))
    (tmp_path / "data" / "cards" / "046.json").write_text(json.dumps(CARDS["046"]))
    (tmp_path / "data" / "archetypes.json").write_text(json.dumps(ARCHETYPES))
    (tmp_path / "data" / "sealed" / f"{SETS[0]['id']}.json").write_text(json.dumps(SEALED[SETS[0]["id"]]))
    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "test")
    git("add", ".")
    git("commit", "-q", "-m", "data")
    git("tag", "v1.0.0")
    return tmp_path


def test_a_tagged_release_counts_the_data_at_its_tag(repo):
    shutil.rmtree(repo / "data" / "sealed")  # the working tree moves on after the tag
    (repo / "data" / "sealed").mkdir()
    assert stats.release("1.0.0", repo)["sealed"] == 1
    assert stats.release("1.1.0", repo)["sealed"] == 0  # not tagged yet: the working tree


def test_values_name_the_version_in_pyproject(repo):
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.0.0"\n')
    (repo / "review").mkdir()
    vals = stats.values(repo)
    assert vals["release.version"] == "1.0.0" and vals["release.sets"] == "1" and vals["sets"] == "1"
