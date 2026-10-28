"""YGOPRODeck's v7 API as plain JSON, cached under .cache/ygoprodeck (never committed).

Four endpoints, each fetched once and read from disk afterwards; pass refresh=True (--refresh on the importers) to
download them again. cardinfo.php?misc=yes is 25 MB: one request returns every card with its prints and images.
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

API = "https://db.ygoprodeck.com/api/v7"
USER_AGENT = "ygjson/0.1 (+https://github.com/ArthurG-data/ygjson)"
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
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    cache.mkdir(parents=True, exist_ok=True)
    time.sleep(FETCH_DELAY_S)
    req = urllib.request.Request(_ENDPOINTS[filename], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)  # parse before writing, so a truncated download never lands in the cache
    path.write_text(raw, encoding="utf-8")
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
