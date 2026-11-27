"""Cut the small source snapshot tests/test_pipeline.py runs the whole pipeline on, out of a full .cache.

    uv run python tests/fixtures/make_pipeline_fixture.py [CACHE]

Keeps one set, Legend of Blue Eyes White Dragon, and three of its cards (Blue-Eyes White Dragon, Dark Magician, Exodia
the Forbidden One), with only their LOB prints: YGOPRODeck's records of them, the YGOJSON sets, cards, series and
sealed products that name them, TCGplayer group 330 with the products for those cards and its sealed products, and the
set infobox of each YGOJSON set's Yugipedia page. Writes tests/fixtures/pipeline/cache/<source>/, replacing what was there.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "tools"))
import yugipedia  # noqa: E402

OUT = HERE / "pipeline" / "cache"
SET_NAME = "Legend of Blue Eyes White Dragon"
CARDS = {89631139, 46986420, 33396948}  # YGOPRODeck ids
GROUP = 330
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def keep_cards(node, ids: set[str]):
    """`node` without the entries of other cards: a key that is a card uuid, or a list item naming a card."""
    if isinstance(node, dict):
        return {k: keep_cards(v, ids) for k, v in node.items() if not UUID.match(k) or k in ids}
    if isinstance(node, list):
        return [keep_cards(v, ids) for v in node
                if not (isinstance(v, dict) and isinstance(v.get("card"), str) and v["card"] not in ids)]
    return node


def main(cache: Path) -> None:
    shutil.rmtree(OUT, ignore_errors=True)

    p = cache / "ygoprodeck"
    cards = [c for c in read(p / "cardinfo.json")["data"] if c["id"] in CARDS]
    for c in cards:
        c["card_sets"] = [s for s in c["card_sets"] if s["set_name"] == SET_NAME]
    write(OUT / "ygoprodeck" / "cardinfo.json", {"data": cards})
    write(OUT / "ygoprodeck" / "cardsets.json", [s for s in read(p / "cardsets.json") if s["set_name"] == SET_NAME])
    names = {c.get("archetype") for c in cards}
    write(OUT / "ygoprodeck" / "archetypes.json", [a for a in read(p / "archetypes.json") if a["archetype_name"] in names])
    shutil.copy(p / "dbver.json", OUT / "ygoprodeck" / "dbver.json")

    j = cache / "ygojson"
    passwords = {str(i["id"]) for c in cards for i in c["card_images"]}  # Dark Magician's art 46986414 is YGOJSON's
    theirs = [c for c in read(j / "cards.json") if passwords & set(c.get("passwords", []))]
    card_ids = {c["id"] for c in theirs}
    sets = [keep_cards(s, card_ids) for s in read(j / "sets.json") if s.get("name", {}).get("en") == SET_NAME]
    set_ids = {s["id"] for s in sets}
    for c in theirs:
        c["sets"] = [s for s in c.get("sets", []) if s in set_ids]
    write(OUT / "ygojson" / "cards.json", theirs)
    write(OUT / "ygojson" / "sets.json", sets)
    write(OUT / "ygojson" / "series.json", [keep_cards(s, card_ids) for s in read(j / "series.json")
                                            if card_ids & set(s.get("members", []))])
    write(OUT / "ygojson" / "sealedProducts.json", [keep_cards(s, card_ids) for s in read(j / "sealedProducts.json")
                                                    if SET_NAME in json.dumps(s.get("name", {}))])
    shutil.copy(j / "meta.json", OUT / "ygojson" / "meta.json")
    shutil.copy(j / "commit.json", OUT / "ygojson" / "commit.json")

    t = cache / "tcgcsv"
    groups = read(t / "2_groups.json")
    write(OUT / "tcgcsv" / "2_groups.json", {**groups, "results": [g for g in groups["results"] if g["groupId"] == GROUP]})
    numbers = {s["set_code"] for c in cards for s in c["card_sets"]}
    products = read(t / f"2_{GROUP}_products.json")
    kept = [r for r in products["results"]
            if not any(e["name"] in ("Number", "Rarity") for e in r.get("extendedData", []))
            or any(e["name"] == "Number" and e["value"] in numbers for e in r.get("extendedData", []))]
    write(OUT / "tcgcsv" / f"2_{GROUP}_products.json", {**products, "results": kept})
    ids = {r["productId"] for r in kept}
    prices = read(t / f"2_{GROUP}_prices.json")
    write(OUT / "tcgcsv" / f"2_{GROUP}_prices.json", {**prices, "results": [r for r in prices["results"]
                                                                           if r["productId"] in ids]})

    y = cache / "yugipedia"
    for s in sets:  # only the set infobox, all import_yugipedia reads
        path = y / f"page_{s.get('externalIDs', {}).get('yugipedia', {}).get('id')}.json"
        if path.exists():
            page = read(path)
            slot = page["revisions"][0]["slots"]["main"]
            start = yugipedia._OPEN.search(slot["content"])
            body = yugipedia._template_body(slot["content"])
            assert start is not None and body is not None, path
            slot["content"] = slot["content"][start.start():start.end() + len(body) + 2]
            write(OUT / "yugipedia" / path.name, page)
    print(f"{len(cards)} cards, {len(sets)} YGOJSON sets, {len(kept)} TCGplayer products written to {OUT}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parents[1] / ".cache")
