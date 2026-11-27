"""Run the import pipeline: the six stages that turn the cached sources into the committed data, in order.

    uv run python tools/pipeline.py [--from STAGE] [--refresh SOURCE ...] [--offline]

The stages are import_ygoprodeck, import_ygojson, import_yugipedia, import_tcgcsv, import_sealed and ids. Each runs as
its own process and prints its own summary; the first that fails stops the run with its exit status, and the stages
after it do not run. When ids exits 3 (a set or archetype was renamed, see ids.py) the stages run once more from the
start, as ids asks.

Each importer keeps what the earlier ones wrote and adds its own fields, so a stage is only right on top of the stages
before it. After each stage the pipeline notes in .cache/pipeline.json which stage last completed and a hash of the
files the stages write (sets/sets.json, data/, ids/, review/, sources.json). --from STAGE starts there, and refuses
unless the stage before it was the last to complete, or a later one, and the files are still as that run left them (a
checkout, or a tool run by hand, changes them: then run the whole pipeline), and unless every earlier stage's source
cache holds the snapshot sources.json says the data came from (an earlier stage would write something else).

--refresh SOURCE downloads a source again before its stage runs: ygoprodeck and tcgcsv (their --refresh), ygojson (the
branch's current commit, import_ygojson's --update). Its stage must be one the run includes. --offline lets no stage
download anything (YGJSON_OFFLINE, see fetch.py): a stage whose cache is incomplete fails instead.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

import fetch
import sources
import ygjson

STAGES = ("import_ygoprodeck", "import_ygojson", "import_yugipedia", "import_tcgcsv", "import_sealed", "ids")
SOURCE_STAGE = {"ygoprodeck": "import_ygoprodeck", "ygojson": "import_ygojson", "yugipedia": "import_yugipedia",
                "tcgcsv": "import_tcgcsv"}
REFRESH_ARGS = {"ygoprodeck": ["--refresh"], "ygojson": ["--update"], "tcgcsv": ["--refresh"]}
RENAMED = 3  # ids.py's exit status after a rename
TOOLS = Path(__file__).resolve().parent
STATE = ygjson.ROOT / ".cache" / "pipeline.json"
OUTPUTS = ("sets/sets.json", "data", "ids", "review", "sources.json")


def outputs_hash(root: Path = ygjson.ROOT) -> str:
    """One hash over every file the stages write, by path and content."""
    h = hashlib.sha256()
    for name in OUTPUTS:
        top = root / name
        files = sorted(p for p in top.rglob("*") if p.is_file()) if top.is_dir() else [top] if top.exists() else []
        for p in files:
            h.update(p.relative_to(root).as_posix().encode("utf-8") + b"\0")
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def load_state(path: Path = STATE) -> dict:
    state = fetch.read_json(path)
    return state if isinstance(state, dict) else {}


def save_state(stage: str, path: Path = STATE, root: Path = ygjson.ROOT) -> None:
    fetch.write_atomic(path, json.dumps({"completed": stage, "outputs": outputs_hash(root)}, indent=1) + "\n")


def refusals(start: str, refresh: Sequence[str], state: dict, current_hash: str, manifest: dict,
             cache: Path) -> list[str]:
    """Why a run from `start` refreshing `refresh` would build on stale data; empty when it may run."""
    first = STAGES.index(start)
    problems = [f"--refresh {s}: its stage {SOURCE_STAGE[s]} comes before --from {start}, so the run would not import "
                f"what it downloads" for s in refresh if STAGES.index(SOURCE_STAGE[s]) < first]
    if first == 0:
        return problems
    before = STAGES[first - 1]
    done = state.get("completed")
    if done not in STAGES:
        problems.append(f"--from {start}: no record of an earlier pipeline run; run the whole pipeline")
    elif STAGES.index(done) < first - 1:
        problems.append(f"--from {start}: the last run completed only {done}, so {before} has not run on its output; "
                        f"run --from {STAGES[STAGES.index(done) + 1]}")
    elif state.get("outputs") != current_hash:
        problems.append(f"--from {start}: the data changed since the pipeline last ran (a checkout, or a tool run by "
                        f"hand); run the whole pipeline")
    held = sources.from_cache(cache)
    for source, stage in SOURCE_STAGE.items():
        if STAGES.index(stage) < first and source in held and held[source] != manifest.get(source):
            problems.append(f"--from {start}: .cache/{source} holds {held[source]}, but the data was imported from "
                            f"{manifest.get(source)}; run --from {stage}")
    return problems


def run_stage(stage: str, args: Sequence[str], env: dict[str, str]) -> int:
    print(f"== {stage} {' '.join(args)}".rstrip(), flush=True)
    began = time.monotonic()
    status = subprocess.run([sys.executable, str(TOOLS / f"{stage}.py"), *args], cwd=ygjson.ROOT, env=env).returncode
    print(f"   {stage}: {'done' if status == 0 else f'exit {status}'} in {time.monotonic() - began:.1f}s", flush=True)
    return status


def run(start: str, refresh: Sequence[str], offline: bool) -> int:
    """Run the stages from `start`; the exit status of the first that fails, else 0."""
    env = {**os.environ, **({fetch.OFFLINE: "1"} if offline else {})}
    pending = {SOURCE_STAGE[s]: REFRESH_ARGS[s] for s in refresh}
    for attempt in (1, 2):
        for stage in STAGES[STAGES.index(start):]:
            status = run_stage(stage, pending.pop(stage, []), env)
            if status == RENAMED and stage == "ids" and attempt == 1:
                print("ids renamed a set or archetype: running the stages again so the data carries the new name",
                      flush=True)
                start = STAGES[0]
                break
            if status != 0:
                later = STAGES[STAGES.index(stage) + 1:]
                print(f"stopped: {stage} failed" + (f"; not run: {', '.join(later)}" if later else ""), flush=True)
                return status
            save_state(stage)
        else:
            return 0
    return RENAMED  # not reached: the second attempt either finishes or returns


def main(argv: Sequence[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="start", choices=STAGES, default=STAGES[0], help="start at this stage")
    ap.add_argument("--refresh", action="append", default=[], choices=sorted(REFRESH_ARGS),
                    help="download this source again before its stage (repeatable)")
    ap.add_argument("--offline", action="store_true", help="download nothing: use only the caches")
    args = ap.parse_args(argv)
    refresh = list(dict.fromkeys(args.refresh))
    problems = refusals(args.start, refresh, load_state(), outputs_hash(), sources.load(), sources.CACHE)
    if problems:
        sys.exit("refusing to run:\n" + "\n".join(problems))
    sys.exit(run(args.start, refresh, args.offline))


if __name__ == "__main__":
    main()
