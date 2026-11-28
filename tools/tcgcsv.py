"""TCGplayer's Yu-Gi-Oh! catalogue as mirrored by TCGCSV (category 2), cached under .cache/tcgcsv."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fetch

TCGCSV = "https://tcgcsv.com/tcgplayer"
CATEGORY = 2
FETCH_DELAY_S = 0.5

# Trailing tags TCGplayer appends to a name to tell variants apart: "(Secret Rare)", "(Starlight Rare)",
# "(Alternate Art)", "(Duel Terminal)", "(Red)" and "[1st Edition]".
_SUFFIX = re.compile(r"\s*[(\[]([^()\[\]]*)[)\]]\s*$")


@dataclass(frozen=True)
class Product:
    product_id: int
    group_id: int
    name: str
    clean_name: str
    image_url: str
    url: str
    extended: dict
    released_on: str | None = None  # TCGplayer's own release date for the product (presaleInfo), when it gives one

    @property
    def number(self) -> str | None:
        return self.extended.get("Number")

    @property
    def rarity(self) -> str | None:
        return self.extended.get("Rarity")

    @property
    def is_single(self) -> bool:
        """A single has a card number or a rarity; sealed products and accessories have neither."""
        return bool(self.extended.get("Number") or self.extended.get("Rarity"))

    def base_name_and_tags(self) -> tuple[str, list[str]]:
        """The name without its trailing parenthesised or bracketed tags, and the tags in reading order."""
        return base_name_and_tags(self.name)


def base_name_and_tags(name: str) -> tuple[str, list[str]]:
    """A product name without its trailing parenthesised or bracketed tags, and the tags in reading order."""
    tags: list[str] = []
    while (m := _SUFFIX.search(name)) and m.start() > 0:
        tags.insert(0, m.group(1).strip())
        name = name[:m.start()]
    return name.strip(), tags


def _check(data: Any, headers: Mapping[str, str]) -> None:
    if not isinstance(data, dict) or "results" not in data:
        raise fetch.Refuse("the reply holds no results")
    if not data.get("success", True):
        raise fetch.Refuse(f"TCGCSV says {data.get('errors')}")


def _get(url: str, cache: Path, refresh: bool) -> dict:
    path = cache / (url.removeprefix(TCGCSV + "/").replace("/", "_") + ".json")
    if not refresh and (data := fetch.read_json(path)) is not None:
        return data
    _, data = fetch.get_json(url, delay=FETCH_DELAY_S, check=_check)
    fetch.write_atomic(path, json.dumps(data))
    return data


def groups(cache: Path, refresh: bool = False) -> list[dict]:
    return _get(f"{TCGCSV}/{CATEGORY}/groups", cache, refresh)["results"]


def products(group_id: int, cache: Path, refresh: bool = False) -> list[Product]:
    rows = _get(f"{TCGCSV}/{CATEGORY}/{group_id}/products", cache, refresh)["results"]
    return [Product(product_id=r["productId"], group_id=r["groupId"], name=r["name"],
                    clean_name=r.get("cleanName") or "", image_url=r.get("imageUrl") or "", url=r.get("url") or "",
                    extended={e["name"]: e["value"] for e in r.get("extendedData") or []},
                    released_on=((r.get("presaleInfo") or {}).get("releasedOn") or "")[:10] or None)
            for r in rows]


def prices(group_id: int, cache: Path, refresh: bool = False) -> list[dict]:
    return _get(f"{TCGCSV}/{CATEGORY}/{group_id}/prices", cache, refresh)["results"]
