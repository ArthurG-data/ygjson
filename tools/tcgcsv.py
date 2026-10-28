"""TCGplayer's Yu-Gi-Oh! catalogue as mirrored by TCGCSV (category 2), cached under .cache/tcgcsv."""
from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

TCGCSV = "https://tcgcsv.com/tcgplayer"
CATEGORY = 2
USER_AGENT = "ygjson/0.1 (+https://github.com/ArthurG-data/ygjson)"
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
        name, tags = self.name, []
        while (m := _SUFFIX.search(name)) and m.start() > 0:
            tags.insert(0, m.group(1).strip())
            name = name[:m.start()]
        return name.strip(), tags


def _get(url: str, cache: Path, refresh: bool) -> dict:
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / (url.removeprefix(TCGCSV + "/").replace("/", "_") + ".json")
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    time.sleep(FETCH_DELAY_S)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data.get("success", True):
        raise RuntimeError(f"{url}: {data.get('errors')}")
    path.write_text(json.dumps(data), encoding="utf-8")
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
