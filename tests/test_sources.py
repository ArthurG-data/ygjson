import datetime
import json
import os

import pytest

import fetch
import import_ygojson
import sources
import ygojson_aggregate

COMMIT = "5d97ede58b68994c3e99a43d419ed5d2c44c7284"
MANIFEST = {"ygoprodeck": {"databaseVersion": "147.67", "lastUpdate": "2026-11-04 16:00:24"},
            "ygojson": {"commit": COMMIT, "increment": 1559},
            "tcgcsv": {"modifiedOn": "2026-10-27"}, "yugipedia": {"pages": 2, "fetchedThrough": "2026-11-05"}}
NOV_5 = datetime.datetime(2026, 11, 5, 12, tzinfo=datetime.UTC).timestamp()


def write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body))
    return path


@pytest.fixture
def cache(tmp_path):
    """A cache holding exactly MANIFEST's snapshots."""
    write(tmp_path / "ygoprodeck" / "dbver.json", [{"database_version": "147.67", "last_update": "2026-11-04 16:00:24"}])
    write(tmp_path / "ygojson" / "meta.json", {"increment": 1559})
    write(tmp_path / "ygojson" / "commit.json", {"commit": COMMIT})
    write(tmp_path / "tcgcsv" / "2_groups.json", {"results": [{"modifiedOn": "2026-08-25T20:31:08.153"},
                                                              {"modifiedOn": "2026-10-27T18:09:35.5"}]})
    for name, when in (("page_1.json", NOV_5 - 86400 * 30), ("title_a-0123456789.json", NOV_5)):
        os.utime(write(tmp_path / "yugipedia" / name, {"pageid": 1}), (when, when))
    write(tmp_path / "yugipedia" / ".page_2.json.99.tmp", "{")  # a write in progress is no page
    return tmp_path


def test_from_cache_reads_each_source(cache):
    assert sources.from_cache(cache) == MANIFEST
    assert sources.problems(MANIFEST, cache) == []


def test_only_the_caches_that_exist_are_compared(tmp_path):
    assert sources.from_cache(tmp_path) == {}
    assert sources.problems(MANIFEST, tmp_path) == []


def test_a_cache_holding_another_snapshot_names_the_importer_to_rerun(cache):
    write(cache / "ygoprodeck" / "dbver.json", [{"database_version": "148.12", "last_update": "2026-11-26 12:02:57"}])
    (problem,) = sources.problems(MANIFEST, cache)
    assert problem.startswith("sources.json: ygoprodeck is {'databaseVersion': '147.67'")
    assert problem.endswith("rerun import_ygoprodeck.py")


def test_a_ygojson_cache_not_downloaded_at_a_commit_does_not_match(cache):
    (cache / "ygojson" / "commit.json").unlink()
    assert sources.from_cache(cache)["ygojson"] == {"commit": None, "increment": 1559}
    (problem,) = sources.problems(MANIFEST, cache)
    assert "rerun import_ygojson.py" in problem


@pytest.mark.parametrize("manifest, error", [
    ({}, "'ygoprodeck' is a required property"),
    ({**MANIFEST, "ygojson": {"commit": "latest", "increment": 1559}}, "does not match"),
    ({**MANIFEST, "tcgcsv": {"modifiedOn": "2026-10-27T18:09:35"}}, "is not a 'date'"),
    ({**MANIFEST, "konami": {}}, "Additional properties"),
])
def test_the_manifest_is_checked_against_its_schema_without_the_cache(manifest, error):
    problems = sources.problems(manifest, cache=None)
    assert problems and all(p.startswith("sources.json: ") for p in problems)
    assert error in problems[0]


def test_record_sets_one_source_and_keeps_the_others(tmp_path):
    path = tmp_path / "sources.json"
    sources.record("tcgcsv", {"modifiedOn": "2026-10-27"}, path)
    sources.record("ygojson", {"commit": COMMIT, "increment": 1}, path)
    sources.record("tcgcsv", {"modifiedOn": "2026-11-05"}, path)
    assert sources.load(path) == {"tcgcsv": {"modifiedOn": "2026-11-05"}, "ygojson": {"commit": COMMIT, "increment": 1}}


def test_rewriting_a_page_with_the_same_bytes_keeps_its_fetch_date(cache):
    page = cache / "yugipedia" / "title_a-0123456789.json"
    fetch.write_atomic(page, page.read_text())
    assert sources.yugipedia(cache / "yugipedia")["fetchedThrough"] == "2026-11-05"


# --- YGOJSON pinned to a commit ---------------------------------------------------------------------------------

def test_blob_sha_is_git_s():
    assert ygojson_aggregate.blob_sha(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


@pytest.fixture
def github(monkeypatch):
    """A fake GitHub holding COMMIT with two files; `github.served` can be set to serve other bytes for a file."""
    files = {"meta.json": b'{"increment": 1559}', "cards.json": b"[]"}

    class GitHub:
        served = dict(files)
        asked: list = []

    def get_json(url, **kw):
        GitHub.asked.append(url)
        if url.endswith("/branches/v1%2Faggregate"):
            return "", {"commit": {"sha": COMMIT}}
        assert url == f"{ygojson_aggregate.API}/git/trees/{COMMIT}"
        tree = [{"path": n, "type": "blob", "sha": ygojson_aggregate.blob_sha(b)} for n, b in files.items()]
        return "", {"tree": [*tree, {"path": "docs", "type": "tree", "sha": "x"}]}

    def get_bytes(url, check=None, **kw):
        GitHub.asked.append(url)
        body = GitHub.served[url.rsplit("/", 1)[1]]
        if check is not None:
            check(body, {})
        return body

    monkeypatch.setattr(fetch, "get_json", get_json)
    monkeypatch.setattr(fetch, "get_bytes", get_bytes)
    return GitHub


def test_download_fetches_each_file_of_the_commit_and_records_it(github, tmp_path):
    assert ygojson_aggregate.download(COMMIT, tmp_path / "ygojson") == ["cards.json", "meta.json"]
    assert f"{ygojson_aggregate.RAW}/{COMMIT}/cards.json" in github.asked
    assert sorted(p.name for p in (tmp_path / "ygojson").iterdir()) == ["cards.json", "commit.json", "meta.json"]
    assert ygojson_aggregate.cached_commit(tmp_path / "ygojson") == COMMIT


def test_a_file_whose_blob_hash_differs_is_refused_and_the_old_cache_kept(github, tmp_path):
    write(tmp_path / "ygojson" / "cards.json", "old")
    github.served["cards.json"] = b"[1]"
    with pytest.raises(fetch.Retry, match="blob hash"):
        ygojson_aggregate.download(COMMIT, tmp_path / "ygojson")
    assert [p.name for p in (tmp_path / "ygojson").iterdir()] == ["cards.json"]
    assert (tmp_path / "ygojson" / "cards.json").read_text() == "old"


@pytest.mark.parametrize("commit", ["v1/aggregate", "latest", COMMIT[:10]])
def test_only_a_full_sha_is_downloaded(github, tmp_path, commit):
    with pytest.raises(ValueError, match="not a full commit sha"):
        ygojson_aggregate.download(commit, tmp_path)
    assert github.asked == []


def test_the_importer_downloads_the_pinned_commit_only_when_the_cache_holds_another(github, tmp_path, monkeypatch):
    monkeypatch.setattr(import_ygojson, "CACHE", tmp_path / "ygojson")
    monkeypatch.setattr(sources, "load", lambda: MANIFEST)
    assert import_ygojson.pinned_cache() == COMMIT
    asked = len(github.asked)
    assert import_ygojson.pinned_cache() == COMMIT
    assert len(github.asked) == asked  # already cached at that commit


def test_update_takes_the_branch_s_current_commit(github, tmp_path, monkeypatch):
    monkeypatch.setattr(import_ygojson, "CACHE", tmp_path / "ygojson")
    monkeypatch.setattr(sources, "load", lambda: {})
    assert import_ygojson.pinned_cache(update=True) == COMMIT
    assert ygojson_aggregate.cached_commit(tmp_path / "ygojson") == COMMIT


def test_with_no_pin_the_importer_asks_for_update(github, tmp_path, monkeypatch):
    monkeypatch.setattr(import_ygojson, "CACHE", tmp_path / "ygojson")
    monkeypatch.setattr(sources, "load", lambda: {})
    with pytest.raises(SystemExit, match="--update"):
        import_ygojson.pinned_cache()
    assert github.asked == []
