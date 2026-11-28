"""Summarise a refresh: how the data in the working tree differs from git REV's, as the refresh pull request's body.

    uv run python tools/refresh_summary.py [--base REV] [--out FILE]

The body gives, per kind of id, the live count before and after and the ids added and retired (from the ledger
under ids/); the ban-list events added and removed (legality/bans.json); the review counts that moved; and sources.json
before and after. It is printed, and written to FILE when given. `changed=true|false` goes to $GITHUB_OUTPUT when that
is set: true when the data (sets/, data/, ids/, legality/) differs from REV. A refresh that moves only sources.json or
review/ changes nothing a reader of the data sees, and opens no pull request.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import decisions
import ids
import sources
import ygjson

DATA = ("sets", "data", "ids", "legality")
REVIEWS = ygjson.ROOT / "review"
BANS = ygjson.LEGALITY / "bans.json"
SHOWN = 40  # ban events listed one by one; the rest are counted


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ygjson.ROOT, capture_output=True)


def _json_at(rev: str, path: str):
    shown = _git("show", f"{rev}:{path}")
    return json.loads(shown.stdout) if shown.returncode == 0 else None


def data_changed(rev: str) -> bool:
    """Whether sets/, data/, ids/ or legality/ in the working tree differ from `rev`, untracked files included."""
    diff = _git("diff", "--name-only", rev, "--", *DATA).stdout.strip()
    new = _git("ls-files", "--others", "--exclude-standard", "--", *DATA).stdout.strip()
    return bool(diff or new)


def snapshot_at(rev: str) -> dict:
    listed = _git("ls-tree", "--name-only", f"{rev}:review").stdout.decode().split()
    return {"ledger": ids.ledger_at(rev), "events": (_json_at(rev, "legality/bans.json") or {}).get("events", []),
            "reviews": {n.removesuffix(".json"): _json_at(rev, f"review/{n}") for n in listed if n.endswith(".json")},
            "sources": _json_at(rev, "sources.json") or {}}


def snapshot_now() -> dict:
    return {"ledger": ids.load_ledger(), "events": json.loads(BANS.read_text(encoding="utf-8"))["events"],
            "reviews": {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(REVIEWS.glob("*.json"))},
            "sources": sources.load()}


def _size(value) -> int | None:
    return len(value) if isinstance(value, (list, dict)) else value if isinstance(value, int) else None


def _event(e: Mapping) -> tuple:
    """(card, format, status, the date it took effect or, for an undated status, "in force by <date>", source)"""
    return e["card"], e["format"], e["status"], e.get("effective") or f"in force by {e['inForceBy']}", e["source"]


def _delta(before: int, after: int) -> str:
    return f"{before:,} → {after:,} ({after - before:+,})" if before != after else f"{after:,}"


def body(before: dict, after: dict, names: Mapping[str, str], today: str) -> str:
    """The pull request body. `names` gives a card's name by id, for the ban-list events."""
    out = [f"Weekly refresh of the sources, {today}.", "", "## Ids", "",
           "| Kind | Live | Added | Retired |", "|---|---|---|---|"]
    for kind in ids.KINDS:
        old, new = before["ledger"].get(kind, {}), after["ledger"].get(kind, {})
        live_old = sum(e["status"] == "live" for e in old.values())
        live_new = sum(e["status"] == "live" for e in new.values())
        added = len(new.keys() - old.keys())
        retired = sum(1 for i, e in new.items()
                      if e["status"] == "retired" and old.get(i, {}).get("status") != "retired")
        out.append(f"| {kind} | {_delta(live_old, live_new)} | {added:,} | {retired:,} |")

    old_events, new_events = {_event(e) for e in before["events"]}, {_event(e) for e in after["events"]}
    added_events, removed_events = sorted(new_events - old_events), sorted(old_events - new_events)
    out += ["", "## Ban list", "", f"{len(added_events)} events added, {len(removed_events)} removed."]
    for title, rows in (("Added", added_events), ("Removed", removed_events)):
        if rows:
            out += ["", f"{title}:", "", "| Card | Format | Status | Date | Source |", "|---|---|---|---|---|"]
            out += [f"| {names.get(c, c)} | {f} | {s} | {d} | {src} |" for c, f, s, d, src in rows[:SHOWN]]
            if len(rows) > SHOWN:
                out.append(f"| … and {len(rows) - SHOWN} more | | | | |")

    moved, same = [], 0
    for name in sorted(before["reviews"].keys() | after["reviews"].keys()):
        old_review, new_review = before["reviews"].get(name) or {}, after["reviews"].get(name) or {}
        for key in sorted(old_review.keys() | new_review.keys()):
            a, b = _size(old_review.get(key)), _size(new_review.get(key))
            if key == decisions.IGNORED or (a is None and b is None):
                continue
            if (a or 0) == (b or 0):
                same += 1
            else:
                moved.append(f"| {name} | {key} | {_delta(a or 0, b or 0)} |")
    out += ["", "## Review", ""]
    if moved:
        out += ["| File | Count | Before → after |", "|---|---|---|", *moved, ""]
    out.append(f"{same} other review counts unchanged." if moved else f"All {same} review counts unchanged.")

    out += ["", "## Sources", "", "| Source | Before | After |", "|---|---|---|"]
    for name in sources.IMPORTER:
        old_source, new_source = before["sources"].get(name), after["sources"].get(name)
        shown = [", ".join(f"{k} {v}" for k, v in sorted(s.items())) if s else "—" for s in (old_source, new_source)]
        out.append(f"| {name} | {shown[0]} | {'unchanged' if old_source == new_source else shown[1]} |")
    out += ["", "<details><summary>sources.json</summary>", "", "```json",
            json.dumps(after["sources"], indent=1, sort_keys=True), "```", "", "</details>"]
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="HEAD", help="the git revision to compare with (default HEAD)")
    ap.add_argument("--out", type=Path, help="also write the body here")
    args = ap.parse_args()
    names = {c["id"]: c["name"] for b in ygjson.load_cards().values() for c in b["cards"]}
    text = body(snapshot_at(args.base), snapshot_now(), names, datetime.date.today().isoformat())
    changed = data_changed(args.base)
    print(text)
    print(f"data changed against {args.base}: {'yes' if changed else 'no'}")
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    if (output := os.environ.get("GITHUB_OUTPUT")):
        with open(output, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")


if __name__ == "__main__":
    main()
