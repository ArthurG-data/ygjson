"""Yugipedia's set pages as wikitext, cached under .cache/yugipedia (never committed), and the set infobox parsed.

Pages are fetched through the MediaWiki API (`action=query&prop=revisions&rvprop=content&rvslots=main`, formatversion 2)
and stored one JSON object per page: `page_<pageid>.json` for a page asked for by id (up to 50 ids per request),
`title_<slug of the title>.json` for one asked for by title. A page that does not exist is cached as a marker
(`{"missing": true, ...}`), so it is asked for once. A cached file is never fetched again unless refresh=True.
Requests are one second apart and carry the project's User-Agent, as Yugipedia asks.

`infobox(wikitext)` parses the first `{{Infobox set ...}}` template into {key: value} with the markup stripped, and
`parse_date` turns a release date into an ISO date. A date given to the month only is put on the 1st of the month.
`limitation_lists(title)` follows a Forbidden & Limited list page's `next` links and parses each `{{Limitation list}}`.
"""
from __future__ import annotations

import datetime
import html
import json
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Iterable
from pathlib import Path

import ygjson

API = "https://yugipedia.com/api.php"
USER_AGENT = "ygjson/0.1 (+https://github.com/ArthurG-data/ygjson)"
FETCH_DELAY_S = 1.0
BATCH = 50
DEFAULT_CACHE = Path(__file__).resolve().parents[1] / ".cache" / "yugipedia"

_last_request = 0.0


def _query(params: dict[str, str]) -> dict:
    """One API request, at least FETCH_DELAY_S after the previous one."""
    global _last_request
    wait = _last_request + FETCH_DELAY_S - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    base = {"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main", "format": "json",
            "formatversion": "2", "redirects": "1"}
    url = API + "?" + urllib.parse.urlencode({**base, **params})
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    finally:
        _last_request = time.monotonic()


def _read(path: Path) -> dict | None:
    """The cached object, or None when it is absent or is a missing-page marker."""
    if not path.exists():
        return None
    page = json.loads(path.read_text(encoding="utf-8"))
    return None if page.get("missing") else page


def _write(path: Path, page: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(page, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def pages_by_id(pageids: Iterable[int], cache: Path = DEFAULT_CACHE, refresh: bool = False) -> dict[int, dict | None]:
    """{pageid: page object or None (the page does not exist)}, fetching the ids not yet cached 50 per request."""
    ids = list(dict.fromkeys(int(i) for i in pageids))
    todo = [i for i in ids if refresh or not (cache / f"page_{i}.json").exists()]
    for start in range(0, len(todo), BATCH):
        chunk = todo[start:start + BATCH]
        found = {p["pageid"]: p for p in _query({"pageids": "|".join(map(str, chunk))})["query"]["pages"]
                 if not p.get("missing") and "pageid" in p}
        for i in chunk:
            _write(cache / f"page_{i}.json", found.get(i) or {"missing": True, "pageid": i})
    return {i: _read(cache / f"page_{i}.json") for i in ids}


def page_by_id(pageid: int, cache: Path = DEFAULT_CACHE, refresh: bool = False) -> dict | None:
    """The page object ({pageid, title, revisions: [...]}) or None when the page does not exist."""
    return pages_by_id([pageid], cache, refresh)[int(pageid)]


def page_by_title(title: str, cache: Path = DEFAULT_CACHE, refresh: bool = False) -> dict | None:
    """The page with this exact title (a redirect is followed), or None; a missing title is cached and not asked twice
    unless refresh=True."""
    path = cache / f"title_{ygjson.slugify(title)}.json"
    if refresh or not path.exists():
        pages = _query({"titles": title})["query"]["pages"]
        page = next((p for p in pages if not p.get("missing") and "pageid" in p), None)
        _write(path, page or {"missing": True, "title": title})
    return _read(path)


def wikitext(page: dict) -> str:
    return page["revisions"][0]["slots"]["main"]["content"]


# --- infobox ---------------------------------------------------------------------------------------------------

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_OPEN = re.compile(r"\{\{\s*Infobox set\b", re.IGNORECASE)
_RUBY = re.compile(r"\{\{\s*Ruby\s*\|([^|{}]*)(?:\|[^{}]*)?\}\}", re.IGNORECASE)
_LINK = re.compile(r"\[\[([^\[\]]*)\]\]")
_REF = re.compile(r"<ref\b[^>]*?/>|<ref\b[^>]*>.*?</ref>", re.DOTALL | re.IGNORECASE)
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"</?[A-Za-z][^>]*>")


def _link_text(m: re.Match) -> str:
    target = m.group(1)
    return target.rsplit("|", 1)[-1] if "|" in target else target


def clean(value: str) -> str:
    """Strip the markup from one infobox value: [[A|B]] -> B, [[A]] -> A, '' italics, {{Ruby|a|b}} -> a, <ref>, <br>
    (-> "; "), HTML tags. A bullet list ("* a\\n* b") becomes "a; b"."""
    value = _REF.sub("", _COMMENT.sub("", value))
    value = _BR.sub("; ", value)
    value = _RUBY.sub(r"\1", value)
    for _ in range(3):  # a link inside a link's label is rare; three passes cover it
        value = _LINK.sub(_link_text, value)
    value = value.replace("'''", "").replace("''", "")
    value = _TAG.sub("", value)
    lines = [ln.strip() for ln in value.strip().splitlines() if ln.strip()]
    if lines and all(ln.startswith("*") for ln in lines):
        lines = [ln.lstrip("*").strip() for ln in lines]
        return "; ".join(ln for ln in lines if ln)
    return " ".join(lines)


def _template_body(text: str, opener: re.Pattern = _OPEN) -> str | None:
    """The text between the template `opener` matches and its matching `}}`, nested templates and links balanced."""
    m = opener.search(text)
    if not m:
        return None
    depth, i = 1, m.end()
    while i < len(text):
        if text.startswith("{{", i):
            depth, i = depth + 1, i + 2
        elif text.startswith("}}", i):
            depth, i = depth - 1, i + 2
            if depth == 0:
                return text[m.end():i - 2]
        else:
            i += 1
    return text[m.end():]  # unterminated: take the rest rather than lose the page


def _split_fields(body: str) -> list[str]:
    """Split on the `|` that sit outside any {{ }} and [[ ]]."""
    fields, depth, link, start, i = [], 0, 0, 0, 0
    while i < len(body):
        two = body[i:i + 2]
        if two == "{{":
            depth, i = depth + 1, i + 2
        elif two == "}}":
            depth, i = max(depth - 1, 0), i + 2
        elif two == "[[":
            link, i = link + 1, i + 2
        elif two == "]]":
            link, i = max(link - 1, 0), i + 2
        elif body[i] == "|" and depth == 0 and link == 0:
            fields.append(body[start:i])
            start, i = i + 1, i + 1
        else:
            i += 1
    fields.append(body[start:])
    return fields


def infobox_raw(text: str) -> dict[str, str] | None:
    """The first {{Infobox set}} as {key: value} with the values as written, or None when the page has none. Keys are
    lower-cased and keep their slashes (`fr/de/it/sp_release_date`)."""
    body = _template_body(_COMMENT.sub("", text))
    if body is None:
        return None
    out: dict[str, str] = {}
    for field in _split_fields(body):
        key, eq, value = field.partition("=")
        key = key.strip().lower()
        if eq and key:
            out[key] = value.strip()
    return out


def infobox(text: str) -> dict[str, str] | None:
    """infobox_raw with every value cleaned (`clean`); an empty value is kept as ""."""
    raw = infobox_raw(text)
    return None if raw is None else {k: clean(v) for k, v in raw.items()}


def page_url(title: str) -> str:
    """The page's address, spaces as underscores and MediaWiki's safe characters left alone."""
    return "https://yugipedia.com/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe=";@$!*(),/~:")


def file_url(name: str) -> str:
    """Special:FilePath redirects to the image file called `name` (a File: prefix is dropped)."""
    name = re.sub(r"^(?:file|image):", "", name.strip(), flags=re.IGNORECASE)
    return "https://yugipedia.com/wiki/Special:FilePath/" + urllib.parse.quote(name.replace(" ", "_"), safe="")


# --- dates -----------------------------------------------------------------------------------------------------

_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
     "december"), 1)}
_DATE_FULL = re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$")
_DATE_MONTH = re.compile(r"^([A-Za-z]+)\.?,?\s+(\d{4})$")
_DATE_DMY = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\.?,?\s+(\d{4})$")


def parse_date(value: str | None) -> str | None:
    """"December 9, 2004" -> "2004-12-09"; "December 2002" -> "2002-12-01" (a month-only date goes to the 1st, the
    earliest day the text allows). None for an empty value, a bare year, or anything that is not a real date."""
    text = clean(value or "")
    if not text:
        return None
    if m := _DATE_FULL.match(text):
        month, day, year = m.group(1), m.group(2), m.group(3)
    elif m := _DATE_DMY.match(text):
        day, month, year = m.group(1), m.group(2), m.group(3)
    elif m := _DATE_MONTH.match(text):
        month, day, year = m.group(1), "1", m.group(2)
    else:
        return None
    number = _MONTHS.get(month.lower())
    if number is None:
        return None
    iso = f"{int(year):04d}-{number:02d}-{int(day):02d}"
    try:
        datetime.date.fromisoformat(iso)
    except ValueError:
        return None
    return iso


_ITALIC = re.compile(r"(?<!')''(?!')(.+?)(?<!')''(?!')")


def named_in(raw: str) -> list[str]:
    """The names an infobox value points at: its ''italic'' spans and the targets and labels of its [[links]], in
    order, without duplicates. `''Dark Crisis'' promotional cards` -> ["Dark Crisis"]."""
    names = [m.group(1) for m in _ITALIC.finditer(_COMMENT.sub("", raw))]
    for m in re.finditer(r"\[\[([^\[\]]*)\]\]", raw):
        names += [part.strip() for part in m.group(1).split("|")]
    return list(dict.fromkeys(clean(n) for n in names if n.strip()))


# --- limitation lists ------------------------------------------------------------------------------------------

_OPEN_LIST = re.compile(r"\{\{\s*Limitation list\b", re.IGNORECASE)
_LIST_SECTIONS = {"forbidden": "banned", "limited": "limited", "semi_limited": "semi_limited"}
_LIST_FORMAT = "Advanced Format"
MAX_DROPPED_SHARE = 0.25


def limitation_list(text: str) -> dict | None:
    """The page's {{Limitation list}} as {date, next, medium, format, statuses}: `date` is `start_date` in ISO form,
    `next` the title of the following list or None, `statuses` {card name: banned, limited or semi_limited}. A line's
    `// note` is dropped.

    None when the page has no such template, when `start_date` is not a full date, or when the forbidden or limited
    section is empty: a card a list leaves out is legal, so a partial list would move cards that did not change."""
    body = _template_body(_COMMENT.sub("", text), _OPEN_LIST)
    if body is None:
        return None
    fields: dict[str, str] = {}
    for field in _split_fields(body):
        key, eq, value = field.partition("=")
        if eq:
            fields[key.strip().lower()] = value.strip()
    start = clean(fields.get("start_date", ""))
    date = parse_date(start) if _DATE_FULL.match(start) or _DATE_DMY.match(start) else None
    if date is None or not fields.get("forbidden") or not fields.get("limited"):
        return None
    statuses: dict[str, str] = {}
    for section, status in _LIST_SECTIONS.items():
        for line in fields.get(section, "").splitlines():
            name = html.unescape(line.split("//")[0]).strip()
            if name:
                statuses[name] = status
    return {"date": date, "next": clean(fields.get("next", "")) or None, "medium": clean(fields.get("medium", "")),
            "format": clean(fields.get("format", "")), "statuses": statuses}


def _follows(item: dict, medium: str, previous: dict | None) -> bool:
    """Whether a page can be the list after `previous`: the same medium, the Advanced Format or none named (OCG pages name
    none), a later date, and no more than MAX_DROPPED_SHARE of the previous list's cards gone. A list leaves out every legal card, so a page cut short
    would move the rest to legal."""
    if item["medium"] != medium or item["format"] not in ("", _LIST_FORMAT):
        return False
    if previous is None:
        return True
    dropped = previous["statuses"].keys() - item["statuses"].keys()
    return item["date"] > previous["date"] and len(dropped) <= len(previous["statuses"]) * MAX_DROPPED_SHARE


def limitation_lists(first: str, medium: str, cache: Path = DEFAULT_CACHE) -> list[dict]:
    """Each `medium` list from the page titled `first` onward, oldest first, following `next`. A page with no `next` is
    asked for again, since it gains one when a new list comes out. The walk ends at a next page that is missing, that
    holds no readable list or that cannot follow the last one (see _follows), so a bad page holds back its list and those
    after it. ValueError when `first` itself holds no list of this medium."""
    lists: list[dict] = []
    title: str | None = first
    while title:
        parsed = _cached_list(title, cache, refresh=False)
        if parsed is None or parsed["next"] is None:
            parsed = _cached_list(title, cache, refresh=True)
        if parsed is None or not _follows(parsed, medium, lists[-1] if lists else None):
            break
        lists.append(parsed)
        title = parsed["next"]
    if not lists:
        raise ValueError(f"{first}: no limitation list")
    return lists


def _cached_list(title: str, cache: Path, refresh: bool) -> dict | None:
    page = page_by_title(title, cache, refresh=refresh)
    return limitation_list(wikitext(page)) if page else None
