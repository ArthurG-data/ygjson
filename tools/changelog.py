"""What changed in the id ledger since an earlier release: the ids added, retired and renamed, for a release to publish.

    uv run python tools/changelog.py [--since REV] [--version 0.3.0]

Compares ids/ with the ledger committed at git REV (the previous release tag) and writes dist/Changes.json and
dist/CHANGES.md, which the release attaches and opens its notes with. Without --since, or when REV holds no ledger,
every id is added: the release is the first to publish the ledger.

For each kind (prints, printings, cards, sets, archetypes, sealed, oracles):

  added    ids REV did not hold.
  retired  ids live at REV and retired now, with the live ids they lead to (their successors).
  renamed  ids live at both whose readable name changed: a print's or printing's `key`, a card's `name`, the last
           of a set's or archetype's `names`. A sealed product or an oracle has no name in the ledger, so
           none is renamed: an oracle gaining a card is not a rename.

An id that is new and already retired counts as added only. Changes.json is {"meta": {"version", "date", "since"},
"data": {kind: {"added": [id], "retired": [{"id", "successors"}], "renamed": [{"id", "from", "to"}]}}}, each list
sorted by id.
"""
from __future__ import annotations

import argparse
import datetime
import json
from collections.abc import Mapping

import ids
import ygjson

DIST = ygjson.ROOT / "dist"
SHOWN = 25  # entries per list in CHANGES.md; Changes.json has them all


def _name(kind: str, entry: Mapping) -> str | None:
    """The readable name of a ledger entry, the one a rename changes; None for a kind without one."""
    if kind in ("prints", "printings"):
        return entry.get("key")
    if kind == "cards":
        return entry.get("name")
    if kind in ("sets", "archetypes"):
        return (entry.get("names") or [None])[-1]
    return None


def changes(before: Mapping[str, Mapping[str, dict]], after: Mapping[str, Mapping[str, dict]]) -> dict[str, dict]:
    """{kind: {"added", "retired", "renamed"}} from ledger `before` to ledger `after` (see the module docstring)."""
    out: dict[str, dict] = {}
    for kind in ids.KINDS:
        old, new = before.get(kind, {}), after.get(kind, {})
        added, retired, renamed = [], [], []
        for i, entry in sorted(new.items()):
            was = old.get(i)
            if was is None:
                added.append(i)
                continue
            if was["status"] == "live" and entry["status"] == "retired":
                retired.append({"id": i, "successors": entry.get("successors", [])})
            elif was["status"] == entry["status"] == "live" and _name(kind, was) != _name(kind, entry):
                renamed.append({"id": i, "from": _name(kind, was), "to": _name(kind, entry)})
        out[kind] = {"added": added, "retired": retired, "renamed": renamed}
    return out


def markdown(data: Mapping[str, dict], since: str | None, first: bool) -> str:
    """The release notes' opening: a table of counts per kind, then the first SHOWN of each list."""
    if first:
        total = sum(len(d["added"]) for d in data.values())
        return (f"## Ids\n\nThe first release to publish the id ledger: all {total:,} ids are new. `Ids.json` lists "
                f"them, and `Changes.json` lists them by kind.\n")
    lines = [f"## Ids since {since}", "", "| Kind | Added | Retired | Renamed |", "|---|---:|---:|---:|"]
    lines += [f"| {kind} | {len(d['added']):,} | {len(d['retired']):,} | {len(d['renamed']):,} |"
              for kind, d in data.items()]
    lines += ["", "`Changes.json` lists every id; a retired id names the live ids it leads to."]
    for kind, d in data.items():
        shown = [*(f"- retired `{r['id']}` → " + (", ".join(f"`{s}`" for s in r["successors"]) or "nothing")
                   for r in d["retired"][:SHOWN]),
                 *(f"- renamed `{r['id']}`: `{r['from']}` → `{r['to']}`" for r in d["renamed"][:SHOWN])]
        if not shown:
            continue
        lines += ["", f"### {kind}", "", *shown]
        hidden = max(len(d["retired"]) - SHOWN, 0) + max(len(d["renamed"]) - SHOWN, 0)
        if hidden:
            lines.append(f"- and {hidden:,} more in `Changes.json`")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", metavar="REV", help="the previous release tag; omit for the first release")
    ap.add_argument("--version", default="0.0.0-dev")
    args = ap.parse_args()
    before = ids.ledger_at(args.since) if args.since else {}
    first = not any(before.values())
    data = changes(before, ids.load_ledger())
    DIST.mkdir(exist_ok=True)
    meta = {"version": args.version, "date": datetime.date.today().isoformat(), "since": None if first else args.since}
    (DIST / "Changes.json").write_text(json.dumps({"meta": meta, "data": data}, ensure_ascii=False, sort_keys=True),
                                       encoding="utf-8")
    (DIST / "CHANGES.md").write_text(markdown(data, args.since, first), encoding="utf-8")
    print("dist/Changes.json written: " + ", ".join(
        f"{kind} +{len(d['added'])} -{len(d['retired'])} ~{len(d['renamed'])}" for kind, d in data.items()))


if __name__ == "__main__":
    main()
