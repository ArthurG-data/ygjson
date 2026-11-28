"""The hand decisions the tools honour on every run: mappings/ignore.json and mappings/print_overrides.json.

ignore.json records review items that are known and accepted, so they stop being re-decided on every rebuild:

    {"<review file stem>": {"<list in that file>": [{"match": {field: value, ...}, "why": "..."}]}}

An entry matches every item of that list whose fields include all of `match` (tcgplayer-2 / unmatched /
{"productId": 23322}). `save_review`, which every importer writes its review file with, moves the matched items out of
their list into the file's `ignored` section ({list: [items]}), so the lists hold only what is still to settle and the
ignored items stay on record.

print_overrides.json records print-level facts a source gets wrong:

    {"prints": {"<print id>": {"editions": [...], "why": "..."}}}

import_tcgcsv applies them last (`apply_print_overrides`). Only OVERRIDABLE fields can be set: a print's set, number,
rarity and variant make its id, so they are not overridden here.

`problems` is what validate.py reports: an entry with no `why`, an ignore entry that matches nothing in its review
list or its ignored items, an ignore entry whose item is still in the list (the importer has not run since), an
ignored item no entry accepts any more (the same), and an override whose print does not exist or does not carry the
override's values. `review_counts` counts what each review list still holds, the number to bring down.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import ygjson

IGNORE = ygjson.ROOT / "mappings" / "ignore.json"
PRINT_OVERRIDES = ygjson.ROOT / "mappings" / "print_overrides.json"
REVIEW = ygjson.ROOT / "review"
IGNORED = "ignored"
OVERRIDABLE = ("editions",)


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if not k.startswith("_")}


def load_ignore(path: Path = IGNORE) -> dict:
    return _load(path)


def load_print_overrides(path: Path = PRINT_OVERRIDES) -> dict[str, dict]:
    return _load(path).get("prints", {})


def matches(entry: Mapping, item) -> bool:
    return isinstance(item, Mapping) and all(item.get(k) == v for k, v in entry["match"].items())


def filter_review(stem: str, body: dict, ignore: Mapping) -> dict:
    """`body` with the items ignore.json accepts moved from their lists to body["ignored"]."""
    rules = ignore.get(stem, {})
    out = {k: v for k, v in body.items() if k != IGNORED}
    ignored: dict[str, list] = {}
    for key, entries in rules.items():
        items = out.get(key)
        if not isinstance(items, list):
            continue
        kept = [i for i in items if not any(matches(e, i) for e in entries)]
        if len(kept) < len(items):
            ignored[key] = [i for i in items if any(matches(e, i) for e in entries)]
            out[key] = kept
    if ignored:
        out[IGNORED] = ignored
    return out


def save_review(path: Path, body: dict, ignore: Mapping | None = None) -> None:
    """Write a review file, with the items ignore.json accepts moved to its `ignored` section."""
    ygjson.save_json(path, filter_review(path.stem, body, load_ignore() if ignore is None else ignore))


def load_reviews(review: Path = REVIEW) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(review.glob("*.json"))}


def review_counts(reviews: Mapping[str, dict]) -> dict[str, int]:
    """{"<file>.<list>": items still to settle} for every list in the review files, ignored items left out."""
    return {f"{stem}.{key}": len(value) for stem, body in sorted(reviews.items())
            for key, value in sorted(body.items()) if key != IGNORED and isinstance(value, list)}


def apply_print_overrides(files: dict[str, dict], set_editions: Mapping[str, list[str]],
                          overrides: Mapping[str, dict]) -> tuple[int, list[str]]:
    """Set each override's fields on its print, in place. `editions` equal to the set's are left off the print, as
    everywhere else. (prints changed, override ids that name no print)."""
    by_id = {p["id"]: p for body in files.values() for c in body["cards"] for p in c["prints"]}
    changed = 0
    for pid, entry in overrides.items():
        p = by_id.get(pid)
        if p is None:
            continue
        before = json.dumps(p, sort_keys=True)
        for field in OVERRIDABLE:
            if field in entry:
                p[field] = list(entry[field])
        if p.get("editions") == set_editions.get(p["set"]):
            p.pop("editions")
        changed += before != json.dumps(p, sort_keys=True)
    return changed, sorted(pid for pid in overrides if pid not in by_id)


def problems(ignore: Mapping, overrides: Mapping[str, dict], reviews: Mapping[str, dict], files: dict[str, dict],
             sets: list[dict]) -> list[str]:
    """One message per hand decision that is malformed, stale or not yet applied."""
    errors = []
    for stem, rules in sorted(ignore.items()):
        body = reviews.get(stem)
        for key, entries in sorted(rules.items()):
            where = f"ignore.json: {stem}/{key}"
            if body is None or not isinstance(body.get(key), list):
                errors.append(f"{where}: review/{stem}.json has no list {key}")
                continue
            for e in entries:
                if not str(e.get("why", "")).strip() or not e.get("match"):
                    errors.append(f"{where}: an entry needs a non-empty match and why: {e}")
                elif any(matches(e, i) for i in body[key]):
                    errors.append(f"{where}: {e['match']} is still in the list: rerun the importer that writes it")
                elif not any(matches(e, i) for i in body.get(IGNORED, {}).get(key, [])):
                    errors.append(f"{where}: {e['match']} matches nothing: the item is gone, remove the entry")
    for stem, body in sorted(reviews.items()):
        for key, items in sorted(body.get(IGNORED, {}).items()):
            entries = ignore.get(stem, {}).get(key, [])
            left = [i for i in items if not any(matches(e, i) for e in entries)]
            if left:
                errors.append(f"review/{stem}.json: {len(left)} ignored {key} items no ignore.json entry accepts any "
                              f"more: rerun the importer that writes it")
    by_id = {p["id"]: p for body in files.values() for c in body["cards"] for p in c["prints"]}
    set_editions = {s["id"]: s.get("editions", []) for s in sets}
    for pid, entry in sorted(overrides.items()):
        where = f"print_overrides.json: {pid}"
        extra = sorted(set(entry) - {*OVERRIDABLE, "why"})
        if not str(entry.get("why", "")).strip():
            errors.append(f"{where}: no why")
        if extra:
            errors.append(f"{where}: {', '.join(extra)} cannot be overridden (only {', '.join(OVERRIDABLE)})")
        p = by_id.get(pid)
        if p is None:
            errors.append(f"{where}: no such print: remove the entry, or move it to the print's new id")
        elif "editions" in entry and ygjson.print_editions(p, set_editions.get(p["set"], [])) != entry["editions"]:
            errors.append(f"{where}: the print's editions are not the override's: rerun import_tcgcsv")
    return errors
