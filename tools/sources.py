"""sources.json: the snapshot of each source the committed data was imported from.

    ygoprodeck  {"databaseVersion", "lastUpdate"}  checkDBVer.php, as import_ygoprodeck read it
    ygojson     {"commit", "increment"}            the v1/aggregate commit import_ygojson read, and its increment
    tcgcsv      {"modifiedOn"}                     the latest modifiedOn among the groups import_tcgcsv read
    yugipedia   {"pages", "fetchedThrough"}        the pages cached, and the day (UTC) the newest of them was fetched

Each importer records its own source once it has read it (`record`); legality.py records yugipedia too, since it reads
the Forbidden & Limited pages into the same cache. `problems` checks the manifest against its schema and, for each
source whose cache exists, against what the cache holds (`from_cache`). build.py copies the manifest into
meta.sources. Only YGOJSON can be downloaded again as it was (at its commit); the others serve only today's data, so
for them the manifest says which cache a release came from, and validate.py tells whether a cache is that one.
"""
from __future__ import annotations

import datetime
from collections.abc import Mapping
from pathlib import Path

import fetch
import ygjson
import ygojson_aggregate

PATH = ygjson.ROOT / "sources.json"
CACHE = ygjson.ROOT / ".cache"
IMPORTER = {"ygoprodeck": "import_ygoprodeck.py", "ygojson": "import_ygojson.py", "tcgcsv": "import_tcgcsv.py",
            "yugipedia": "import_yugipedia.py"}


def ygoprodeck(dbver: Mapping) -> dict:
    return {"databaseVersion": dbver["database_version"], "lastUpdate": dbver["last_update"]}


def ygojson(commit: str, meta: Mapping) -> dict:
    return {"commit": commit, "increment": meta["increment"]}


def tcgcsv(groups: list[dict]) -> dict:
    return {"modifiedOn": max(g["modifiedOn"] for g in groups)[:10]}


def yugipedia(cache: Path) -> dict | None:
    """The pages in a Yugipedia cache directory and the UTC day the newest was written, or None when it holds none."""
    times = [p.stat().st_mtime for p in cache.glob("*.json") if p.name.startswith(("page_", "title_"))]
    if not times:
        return None
    newest = datetime.datetime.fromtimestamp(max(times), datetime.UTC).date().isoformat()
    return {"pages": len(times), "fetchedThrough": newest}


def load(path: Path = PATH) -> dict:
    return fetch.read_json(path) or {}


def record(name: str, snapshot: dict, path: Path = PATH) -> None:
    """Set one source's snapshot in the manifest, keeping the others."""
    ygjson.save_json(path, {**load(path), name: snapshot})


def from_cache(cache: Path = CACHE) -> dict:
    """{source: snapshot} for each source whose cache is there. A YGOJSON cache not downloaded at a commit has
    commit None."""
    out: dict = {}
    if isinstance(dbver := fetch.read_json(cache / "ygoprodeck" / "dbver.json"), list) and dbver:
        out["ygoprodeck"] = ygoprodeck(dbver[0])
    if isinstance(meta := fetch.read_json(cache / "ygojson" / "meta.json"), dict):
        out["ygojson"] = {"commit": ygojson_aggregate.cached_commit(cache / "ygojson"), "increment": meta["increment"]}
    if isinstance(groups := fetch.read_json(cache / "tcgcsv" / "2_groups.json"), dict) and groups.get("results"):
        out["tcgcsv"] = tcgcsv(groups["results"])
    if (pages := yugipedia(cache / "yugipedia")) is not None:
        out["yugipedia"] = pages
    return out


def problems(manifest: dict, cache: Path | None = CACHE) -> list[str]:
    """One message per problem: the manifest's shape, then each source whose cache (when `cache` is given) holds
    another snapshot than the manifest names."""
    errors = ygjson._schema_errors("sources.schema.json", "sources.json", manifest)
    if errors or cache is None:
        return errors
    for name, held in from_cache(cache).items():
        if held != manifest[name]:
            errors.append(f"sources.json: {name} is {manifest[name]}, but .cache/{name} holds {held}: "
                          f"rerun {IMPORTER[name]}")
    return errors
