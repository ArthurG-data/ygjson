"""YGOPRODeck's v7 API as plain JSON, cached under .cache/ygoprodeck (never committed).

Four endpoints, each fetched once and read from disk afterwards; pass refresh=True to download one again, or fetch
into fetch.cache_dir(cache, refresh=True) (--refresh on import_ygoprodeck) to replace the four together.
cardinfo.php?misc=yes is 25 MB: one request returns every card with its prints and images.
"""
from __future__ import annotations

from pathlib import Path

import fetch

API = "https://db.ygoprodeck.com/api/v7"
FETCH_DELAY_S = 0.1
DEFAULT_CACHE = Path(__file__).resolve().parents[1] / ".cache" / "ygoprodeck"

_ENDPOINTS = {
    "cardinfo.json": f"{API}/cardinfo.php?misc=yes",
    "cardsets.json": f"{API}/cardsets.php",
    "archetypes.json": f"{API}/archetypes.php",
    "dbver.json": f"{API}/checkDBVer.php",
}


def _get(filename: str, cache: Path, refresh: bool):
    path = cache / filename
    if not refresh and (data := fetch.read_json(path)) is not None:
        return data
    raw, data = fetch.get_json(_ENDPOINTS[filename], timeout=120, delay=FETCH_DELAY_S)
    fetch.write_atomic(path, raw)
    return data


def cards(cache: Path = DEFAULT_CACHE, refresh: bool = False) -> list[dict]:
    """Every card, as cardinfo.php?misc=yes returns it (its `data` list)."""
    return _get("cardinfo.json", cache, refresh)["data"]


def sets(cache: Path = DEFAULT_CACHE, refresh: bool = False) -> list[dict]:
    """cardsets.php: {set_name, set_code (the prefix), num_of_cards, tcg_date?, set_image?} per set."""
    return _get("cardsets.json", cache, refresh)


def archetypes(cache: Path = DEFAULT_CACHE, refresh: bool = False) -> list[str]:
    """archetypes.php: the archetype names."""
    return [a["archetype_name"] for a in _get("archetypes.json", cache, refresh)]


def db_version(cache: Path = DEFAULT_CACHE, refresh: bool = False) -> dict:
    """checkDBVer.php: {"database_version": "147.60", "last_update": "2026-10-25 16:01:59"}."""
    return _get("dbver.json", cache, refresh)[0]
