"""The counts the README quotes, computed from the committed data, and kept in the README between markers.

    uv run python tools/stats.py [--write]

Each number in README.md sits between markers, `<!--n:KEY-->1,066<!--/n-->`, and `counts()` gives every KEY. With
--write the README is rewritten with today's values; without it the tool prints each number that differs and exits 1
(CI runs it so). Everything is read from committed files (sets/, data/, legality/, review/), so it needs no .cache.

The release paragraph names the version in pyproject.toml. Its counts (the `release.*` keys) are the data at that
version's tag (v<version>) when the tag exists, else the data in the working tree: a release is prepared by bumping
the version and running --write, and the tag then points at data with the same counts. Every other key describes the
data in the working tree.
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from collections.abc import Mapping
from pathlib import Path

import decisions
import rarities
import ygjson

README = ygjson.ROOT / "README.md"
MARKER = re.compile(r"<!--n:([A-Za-z0-9_.+-]+)-->(.*?)<!--/n-->")
OPENER = "<!--n:"


def _load(root: Path) -> dict:
    """The data files under `root` (a checkout or an extracted tag), without validating them."""
    def each(folder: Path) -> list[dict]:
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))]

    cards = dict(enumerate(each(root / "data" / "cards")))
    sealed = dict(enumerate(each(root / "data" / "sealed")))
    bans = root / "legality" / "bans.json"
    return {"sets": json.loads((root / "sets" / "sets.json").read_text(encoding="utf-8")), "cards": cards,
            "archetypes": json.loads((root / "data" / "archetypes.json").read_text(encoding="utf-8"))["archetypes"],
            "sealed": [p for body in sealed.values() for p in body["products"]],
            "events": json.loads(bans.read_text(encoding="utf-8"))["events"] if bans.exists() else []}


def _totals(d: dict) -> dict[str, int]:
    """The headline counts: what the release paragraph quotes."""
    editions = {s["id"]: s.get("editions", []) for s in d["sets"]}
    prints = [p for body in d["cards"].values() for c in body["cards"] for p in c["prints"]]
    return {"sets": len(d["sets"]), "cards": sum(len(b["cards"]) for b in d["cards"].values()), "prints": len(prints),
            "printings": sum(len(ygjson.print_editions(p, editions.get(p["set"], []))) for p in prints),
            "archetypes": len(d["archetypes"]), "sealed": len(d["sealed"]), "events": len(d["events"]),
            "prints_with_product": sum(1 for p in prints if p.get("identifiers", {}).get("tcgplayerProductIds"))}


def counts(d: dict, reviews: Mapping[str, dict]) -> dict[str, int]:
    """Every count the README quotes about the data `d` (see _load), by marker key."""
    out: dict[str, int] = dict(_totals(d))
    sets, archetypes, sealed, events = d["sets"], d["archetypes"], d["sealed"], d["events"]
    cards = [c for body in d["cards"].values() for c in body["cards"]]
    prints = [p for c in cards for p in c["prints"]]
    by_id = {s["id"]: s for s in sets}

    codes = collections.Counter(s["code"] for s in sets)
    out["prefixes_shared"] = sum(1 for n in codes.values() if n > 1)
    for t, n in collections.Counter(s["type"] for s in sets).items():
        out[f"type.{t}"] = n
    out["sets_with_series"] = sum(1 for s in sets if s.get("series"))
    out["sets_with_parent"] = sum(1 for s in sets if s.get("parent"))
    for t in ("sneak_peek", "special_edition"):
        out[f"type.{t}.with_parent"] = sum(1 for s in sets if s["type"] == t and s.get("parent"))
    art = [s["releases"][0].get("keyArt", {}).get("url", "") for s in sets if s.get("releases")]
    out["keyart.ygoprodeck"] = sum(1 for u in art if "ygoprodeck.com" in u)
    out["keyart.ygojson"] = sum(1 for u in art if u and "ygoprodeck.com" not in u)

    def mixes_limited(s: dict) -> bool:
        eds = s.get("editions", [])
        return "limited" in eds and len(eds) > 1

    out["prints_own_editions"] = sum(1 for p in prints if "editions" in p)
    out["prints_voted_editions"] = sum(1 for p in prints if "editions" in p and mixes_limited(by_id.get(p["set"], {}))
                                       and not p.get("identifiers", {}).get("tcgplayerProductIds"))
    out["cards_monster"] = sum(1 for c in cards if c["kind"] == "monster")
    out["cards_konami"] = sum(1 for c in cards if "konamiId" in c["identifiers"])
    out["cards_ygojson"] = sum(1 for c in cards if "ygojsonId" in c["identifiers"])
    for r, n in collections.Counter(p.get("region") for p in prints).items():
        if r:
            out[f"region.{r}"] = n
    out["rarity_codes"] = len({*rarities.ALIASES.values()} - {rarities.UNKNOWN})
    unknown = [p for p in prints if p["rarity"] == rarities.UNKNOWN]
    out["prints_unknown"] = len(unknown)
    out["printings_no_finish"] = sum(len(ygjson.print_editions(p, by_id[p["set"]].get("editions", [])))
                                     for p in unknown)
    for m, n in collections.Counter(p["tcgplayer"]["match"] for p in prints if "tcgplayer" in p).items():
        out[f"match.{m}"] = n
    out["prints_several_products"] = sum(1 for p in prints
                                         if len(p.get("identifiers", {}).get("tcgplayerProductIds", [])) > 1)
    out["prints_no_product"] = out["prints"] - out["prints_with_product"]

    members = collections.Counter(a for c in cards for a in c.get("archetypes", []))
    out["archetypes.ygoprodeck"] = sum(1 for a in archetypes if a["source"] == "ygoprodeck")
    out["archetypes.ygojson"] = sum(1 for a in archetypes if a["source"] == "ygojson")
    out["archetypes.not_archetype"] = sum(1 for a in archetypes if a.get("isArchetype") is False)
    out["archetypes.no_member"] = sum(1 for a in archetypes if not members[a["slug"]])

    for c, n in collections.Counter(p["category"] for p in sealed).items():
        out[f"sealed.{c}"] = n
    for s, n in collections.Counter(p["contentsStatus"] for p in sealed).items():
        out[f"sealed.status.{s}"] = n
    out["sealed.ygojson"] = sum(1 for p in sealed if p.get("identifiers", {}).get("ygojsonId"))
    out["sealed.no_set"] = len(reviews.get("sealed", {}).get("noSet", []))

    out["events.ygojson"] = sum(1 for e in events if e["source"] == "ygojson" and "effective" in e)
    out["events.yugipedia"] = sum(1 for e in events if e["source"] == "yugipedia")
    out["events.in_force_by"] = sum(1 for e in events if "inForceBy" in e)
    for k in ("format", "status"):
        for v, n in collections.Counter(e[k] for e in events).items():
            out[f"events.{v}"] = n
    return out


def _version(root: Path = ygjson.ROOT) -> str:
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def release(version: str, root: Path = ygjson.ROOT) -> dict[str, int]:
    """The headline counts of release `version`: the data at tag v<version>, or the working tree before it is tagged."""
    tag = f"v{version}"
    found = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"], cwd=root,
                           capture_output=True)
    if found.returncode != 0:
        return _totals(_load(root))
    held = subprocess.run(["git", "ls-tree", "--name-only", tag], cwd=root, capture_output=True,
                          check=True).stdout.decode().split()
    paths = [p for p in ("sets", "data", "legality") if p in held]
    archive = subprocess.run(["git", "archive", "--format=tar", tag, *paths], cwd=root, capture_output=True,
                             check=True).stdout
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(tmp, filter="data")
        return _totals(_load(Path(tmp)))


def values(root: Path = ygjson.ROOT) -> dict[str, str]:
    """Every marker key and the text it holds: counts with thousands separators, and the release version."""
    version = _version(root)
    out = {k: f"{n:,}" for k, n in counts(_load(root), decisions.load_reviews(root / "review")).items()}
    out |= {f"release.{k}": f"{n:,}" for k, n in release(version, root).items()}
    out["release.version"] = version
    return out


def render(text: str, vals: Mapping[str, str]) -> tuple[str, list[str]]:
    """`text` with each marker holding its value, and one message per marker whose value changed or whose key is
    not known."""
    problems: list[str] = []

    def put(m: re.Match) -> str:
        key, old = m.group(1), m.group(2)
        if key not in vals:
            problems.append(f"README.md: no count named {key!r}")
            return m.group(0)
        if old != vals[key]:
            line = text.count("\n", 0, m.start()) + 1
            problems.append(f"README.md:{line}: {key} is {old}, the data says {vals[key]}")
        return f"<!--n:{key}-->{vals[key]}<!--/n-->"

    out = MARKER.sub(put, text)
    if text.count(OPENER) != len(MARKER.findall(text)):
        problems.append(f"README.md: {text.count(OPENER) - len(MARKER.findall(text))} markers are malformed: a key "
                        f"other than letters, digits and _.+-, or no <!--/n--> on the same line")
    return out, problems


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="rewrite the README's numbers from the data")
    args = ap.parse_args()
    text = README.read_text(encoding="utf-8")
    new, problems = render(text, values())
    unknown = [p for p in problems if "no count named" in p or "malformed" in p]
    if args.write:
        README.write_text(new, encoding="utf-8")
        print(f"README.md: {len(problems) - len(unknown)} numbers updated, {len(MARKER.findall(text))} in all")
        for p in unknown:
            print(p)
        sys.exit(1 if unknown else 0)
    for p in problems:
        print(p)
    print(f"{len(problems)} README numbers differ from the data (run tools/stats.py --write)" if problems
          else f"README.md: all {len(MARKER.findall(text))} numbers match the data")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
