"""Seed the permanent-id ledger from main's history and the published releases, once.

    uv run python tools/seed_ids.py [--rev origin/main] [--release v0.1.0=DIR --release v0.2.0=DIR]

Starting from an empty ledger, runs the reconcile of tools/ids.py on the data of each first-parent commit of REV,
oldest first, with no hand decisions, so every key ever on main gets an entry: a live print's id, a former key of
one, or a retired id with successors. A file a commit lacks loads empty. A set or archetype rename is not an error
here: it is listed under "renames" in review/ids.json with its commit. Then each DIR/AllPrintings.json (a release's
{"data": {printing id: record}}) adds every printing id it published that the ledger does not hold to the formerIds
of the printing its record's print and language and edition now have. review/ids.json is the final ledger's review
(see tools/ids.py) with those renames; the ids no printing can take are listed under "unresolved", and the run exits
1 after writing ids/ and the review. Refuses (exit 2, nothing written) when ids/ already holds entries: after the
seed, reconcile only runs forward.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import ids
import ygjson


def _git(args: list[str], root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True)


def commits(rev: str = "origin/main", *, root: Path = ygjson.ROOT) -> list[str]:
    """The first-parent commits of `rev`, oldest first. Exits on a rev git lacks."""
    out = _git(["rev-list", "--first-parent", "--reverse", rev], root)
    if out.returncode != 0:
        sys.exit(f"{rev}: no such git revision")
    return out.stdout.decode("utf-8").split()


def _show(commit: str, path: str, root: Path, empty):
    """The JSON file at `path` in `commit`, or `empty` when the commit lacks it."""
    shown = _git(["show", f"{commit}:{path}"], root)
    return json.loads(shown.stdout.decode("utf-8")) if shown.returncode == 0 else empty


def _bodies(commit: str, directory: str, root: Path) -> dict[str, dict]:
    """{stem: body} of the .json files in `directory` at `commit`, sorted by stem; empty when it is not there."""
    listed = _git(["ls-tree", "--name-only", commit, f"{directory}/"], root).stdout.decode("utf-8").split()
    return {Path(p).stem: _show(commit, p, root, {}) for p in sorted(listed) if p.endswith(".json")}


def snapshot(commit: str, *, root: Path = ygjson.ROOT) -> tuple[list[dict], dict[str, dict], dict, dict[str, dict],
                                                                dict[str, str]]:
    """(sets, card files, archetypes, sealed files, {alias set slug: merge target}) as committed at `commit`, in the
    shapes of the ygjson loaders; what the commit lacks loads empty."""
    aliases = _show(commit, "mappings/ygoprodeck_set_aliases.json", root, {})
    return (_show(commit, "sets/sets.json", root, []), _bodies(commit, "data/cards", root),
            _show(commit, "data/archetypes.json", root, {"archetypes": []}), _bodies(commit, "data/sealed", root),
            {alias: entry["set"] for alias, entry in aliases.items()})


def _owner(prints: dict[str, dict], key: str) -> str | None:
    """The print id that holds `key`: the entry whose key it is, else one that had it, live first, smallest id."""
    holders = [i for i, e in prints.items() if e["key"] == key or key in e["formerKeys"]]
    return min(holders, key=lambda i: (prints[i]["key"] != key, prints[i]["status"] != "live", i), default=None)


def add_release(ledger: dict[str, dict[str, dict]], data: dict[str, dict]) -> list[str]:
    """Add each printing id of a release's `data` the ledger does not hold to the formerIds of the printing its print,
    language and edition now have, in place; the ids no printing can take, sorted."""
    printings = ledger["printings"]
    known = {i for e in printings.values() for i in [e["key"], *e["formerIds"]]}
    unresolved = []
    for published, record in sorted(data.items()):
        if published in printings or published in known:
            continue
        owner = _owner(ledger["prints"], record["print"])
        entry = printings.get(f"{owner}:{record['language']}:{record['edition']}") if owner else None
        if entry is None:
            unresolved.append(published)
            continue
        entry["formerIds"].append(published)
        known.add(published)
    return unresolved


def seed(commits: list[str], releases: dict[str, Path], *,
         root: Path = ygjson.ROOT) -> tuple[dict[str, dict[str, dict]], dict]:
    """(ledger, review): reconcile replayed over `commits` from an empty ledger, then the printing ids of each release
    ({name: directory holding its AllPrintings.json}, in the order given) recorded. The review is the final ledger's
    (ids.review_body), with every commit's renames (each carrying its "commit") and, when there are any, the
    "unresolved" published printing ids."""
    ledger: dict[str, dict[str, dict]] = {kind: {} for kind in ids.KINDS}
    renames: list[dict] = []
    for commit in commits:
        sets, files, archetypes, sealed, merges = snapshot(commit, root=root)
        ledger, _, found = ids.run(ledger, sets, files, archetypes, sealed, ({}, {}), merges)
        renames += [{**r, "commit": commit} for r in found]
    unresolved: set[str] = set()
    for directory in releases.values():
        data = json.loads((Path(directory) / "AllPrintings.json").read_text(encoding="utf-8"))["data"]
        unresolved.update(add_release(ledger, data))
    review = ids.review_body(ledger, (), renames)
    return ledger, {**review, "unresolved": sorted(unresolved)} if unresolved else review


def _release(arg: str) -> tuple[str, Path]:
    name, sep, directory = arg.partition("=")
    if not sep or not name or not directory:
        raise argparse.ArgumentTypeError(f"{arg!r} is not NAME=DIR")
    return name, Path(directory)


def main(argv: list[str] | None = None, *, root: Path = ygjson.ROOT) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rev", default="origin/main", help="the branch whose first-parent history is replayed")
    ap.add_argument("--release", type=_release, action="append", default=[], metavar="NAME=DIR",
                    help="a published release whose DIR/AllPrintings.json printing ids must resolve")
    args = ap.parse_args(argv)
    ids_dir, review_path = root / "ids", root / "review" / "ids.json"
    held = sum(len(entries) for entries in ids.load_ledger(ids_dir).values())
    if held:
        print(f"ids/ already holds {held} entries: the seed runs once, on an empty ledger", file=sys.stderr)
        sys.exit(2)

    history = commits(args.rev, root=root)
    ledger, review = seed(history, dict(args.release), root=root)
    ids.save_ledger(ledger, ids_dir)
    ygjson.save_json(review_path, review)
    counts = [f"{kind} {sum(e['status'] == 'live' for e in ledger[kind].values())} live "
              f"{sum(e['status'] == 'retired' for e in ledger[kind].values())} retired" for kind in ids.KINDS]
    print(f"ids/ seeded from {len(history)} commits and {len(args.release)} releases: " + ", ".join(counts)
          + f"; {len(review['renames'])} renames, {len(review.get('unresolved', []))} unresolved")
    for published in review.get("unresolved", []):
        print(f"unresolved: {published}")
    if review.get("unresolved"):
        sys.exit(1)


if __name__ == "__main__":
    main()
