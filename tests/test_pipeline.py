import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import pipeline

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "pipeline" / "cache"


@pytest.fixture
def repo(tmp_path):
    """A copy of the repository's tools and schemas with no data, and the small snapshot of
    tests/fixtures/pipeline (see make_pipeline_fixture.py) as its .cache."""
    for name in ("tools", "schema", "legality"):
        shutil.copytree(ROOT / name, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "mappings").mkdir()  # the real mappings name sets the snapshot lacks; set types name none
    shutil.copy(ROOT / "mappings" / "set_types.json", tmp_path / "mappings" / "set_types.json")
    for name in ("tcgplayer_groups.json", "tcgplayer_products.json", "ygoprodeck_set_aliases.json"):
        (tmp_path / "mappings" / name).write_text("{}\n")
    (tmp_path / "legality" / "bans.json").write_text('{"events": []}\n')
    (tmp_path / "sets").mkdir()
    shutil.copy(ROOT / "sets" / "eras.json", tmp_path / "sets" / "eras.json")
    shutil.copytree(FIXTURE, tmp_path / ".cache")
    commit = json.loads((FIXTURE / "ygojson" / "commit.json").read_text())["commit"]
    (tmp_path / "sources.json").write_text(json.dumps({"ygojson": {"commit": commit, "increment": 0}}))
    return tmp_path


def run(repo, *args, tool="pipeline.py"):
    return subprocess.run([sys.executable, str(repo / "tools" / tool), *args], cwd=repo, capture_output=True,
                          text=True)


def stages_run(out: str) -> list[str]:
    return [line.split()[1] for line in out.splitlines() if line.startswith("== ")]


def read(repo, path):
    return json.loads((repo / path).read_text())


# --- end to end -------------------------------------------------------------------------------------------------

def test_the_whole_pipeline_turns_the_snapshot_into_valid_data(repo):
    done = run(repo, "--offline")
    assert done.returncode == 0, done.stdout + done.stderr
    assert stages_run(done.stdout) == list(pipeline.STAGES)

    (lob,) = [s for s in read(repo, "sets/sets.json") if s["id"] == "legend-of-blue-eyes-white-dragon"]
    assert lob["identifiers"]["yugipediaId"] == 2484  # YGOJSON gave the page, Yugipedia the infobox
    assert lob["type"] == "booster"
    assert lob["tcgplayerGroupIds"] == [330]
    cards = {c["name"]: c for body in (repo / "data" / "cards").glob("*.json") for c in json.loads(body.read_text())["cards"]}
    assert set(cards) == {"Blue-Eyes White Dragon", "Dark Magician", "Exodia the Forbidden One"}
    assert "ygojsonId" in cards["Blue-Eyes White Dragon"]["identifiers"]  # YGOJSON matched the card by password
    assert any(p.get("identifiers", {}).get("tcgplayerProductIds") for p in cards["Dark Magician"]["prints"])
    assert list((repo / "data" / "sealed").glob("*.json"))
    assert read(repo, "ids/prints.json")["prints"]

    manifest = read(repo, "sources.json")
    assert set(manifest) == {"ygoprodeck", "ygojson", "tcgcsv", "yugipedia"}
    checked = run(repo, tool="validate.py")
    assert checked.returncode == 0, checked.stdout + checked.stderr  # sources.json matches the cache too


def test_a_second_run_changes_nothing_and_from_runs_only_the_later_stages(repo):
    assert run(repo, "--offline").returncode == 0
    before = pipeline.outputs_hash(repo)
    again = run(repo, "--offline", "--from", "import_tcgcsv")
    assert again.returncode == 0, again.stdout + again.stderr
    assert stages_run(again.stdout) == ["import_tcgcsv", "import_sealed", "ids"]
    assert run(repo, "--offline").returncode == 0
    assert pipeline.outputs_hash(repo) == before


def test_a_failing_stage_stops_the_run(repo):
    (repo / ".cache" / "tcgcsv" / "2_330_prices.json").unlink()  # offline, it cannot be fetched
    done = run(repo, "--offline")
    assert done.returncode == 1
    assert stages_run(done.stdout) == ["import_ygoprodeck", "import_ygojson", "import_yugipedia", "import_tcgcsv"]
    assert "not downloaded, YGJSON_OFFLINE is set" in done.stderr
    assert "stopped: import_tcgcsv failed; not run: import_sealed, ids" in done.stdout
    assert not (repo / "ids").exists()
    refused = run(repo, "--offline", "--from", "import_sealed")
    assert refused.returncode == 1
    assert "the last run completed only import_yugipedia" in refused.stderr
    assert "run --from import_tcgcsv" in refused.stderr


def test_from_is_refused_after_the_data_changed_outside_the_pipeline(repo):
    assert run(repo, "--offline").returncode == 0
    sets = read(repo, "sets/sets.json")
    sets[0]["name"] += " (edited)"
    (repo / "sets" / "sets.json").write_text(json.dumps(sets))
    refused = run(repo, "--offline", "--from", "import_tcgcsv")
    assert refused.returncode == 1
    assert "the data changed since the pipeline last ran" in refused.stderr
    assert stages_run(refused.stdout) == []


def test_from_is_refused_when_an_earlier_source_s_cache_moved_on(repo):
    assert run(repo, "--offline").returncode == 0
    dbver = repo / ".cache" / "ygoprodeck" / "dbver.json"
    dbver.write_text(json.dumps([{**json.loads(dbver.read_text())[0], "database_version": "999.1"}]))
    refused = run(repo, "--offline", "--from", "import_ygojson")
    assert refused.returncode == 1
    assert ".cache/ygoprodeck holds" in refused.stderr and "run --from import_ygoprodeck" in refused.stderr


# --- the run itself ---------------------------------------------------------------------------------------------

@pytest.fixture
def stages(monkeypatch):
    """Stages that only record their name and args; `stages.status` gives the exit status of each, in turn."""
    class Stages:
        ran: list = []
        status: dict = {}

    def run_stage(stage, args, env):
        Stages.ran.append((stage, list(args)))
        queue = Stages.status.get(stage, [])
        return queue.pop(0) if queue else 0

    monkeypatch.setattr(pipeline, "run_stage", run_stage)
    monkeypatch.setattr(pipeline, "save_state", lambda stage: None)
    return Stages


def test_a_rename_runs_the_stages_once_more(stages):
    stages.status = {"ids": [pipeline.RENAMED]}
    assert pipeline.run("import_tcgcsv", ["tcgcsv"], offline=True) == 0
    assert [s for s, _ in stages.ran] == ["import_tcgcsv", "import_sealed", "ids", *pipeline.STAGES]
    assert stages.ran[0] == ("import_tcgcsv", ["--refresh"])
    assert all(args == [] for _, args in stages.ran[1:])  # the refresh is not repeated


def test_a_second_rename_stops_the_run(stages):
    stages.status = {"ids": [pipeline.RENAMED, pipeline.RENAMED]}
    assert pipeline.run("import_ygoprodeck", [], offline=True) == pipeline.RENAMED
    assert len(stages.ran) == 2 * len(pipeline.STAGES)


def test_refresh_passes_each_source_s_flag_to_its_stage(stages):
    assert pipeline.run("import_ygoprodeck", ["ygojson", "ygoprodeck"], offline=False) == 0
    assert dict(stages.ran) == {"import_ygoprodeck": ["--refresh"], "import_ygojson": ["--update"],
                                "import_yugipedia": [], "import_tcgcsv": [], "import_sealed": [], "ids": []}


MANIFEST = {"ygoprodeck": {"databaseVersion": "1"}}


@pytest.mark.parametrize("start, refresh, state, problem", [
    ("import_ygoprodeck", ["tcgcsv"], {}, None),
    ("import_sealed", ["tcgcsv"], {"completed": "ids", "outputs": "h"}, "--refresh tcgcsv: its stage import_tcgcsv"),
    ("import_tcgcsv", [], {}, "no record of an earlier pipeline run"),
    ("import_tcgcsv", [], {"completed": "import_ygojson", "outputs": "h"}, "run --from import_yugipedia"),
    ("import_tcgcsv", [], {"completed": "import_yugipedia", "outputs": "h"}, None),
    ("import_tcgcsv", [], {"completed": "ids", "outputs": "h"}, None),
    ("import_tcgcsv", [], {"completed": "ids", "outputs": "other"}, "the data changed"),
])
def test_refusals(tmp_path, start, refresh, state, problem):
    found = pipeline.refusals(start, refresh, state, "h", MANIFEST, tmp_path)
    assert (found == []) if problem is None else (len(found) == 1 and problem in found[0])
