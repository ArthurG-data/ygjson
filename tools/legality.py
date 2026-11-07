"""Write legality/bans.json from YGOJSON's ban history, Yugipedia's dated lists and the current lists of YGOPRODeck
and YGOJSON, or check it.

    uv run python tools/legality.py [--check] [--refresh] [--as-of YYYY-MM-DD]

An event says a card's status in a format changed. A status in force on a date is the card's last event on or before
it, and before its first event the card is legal. Statuses are copies allowed: banned 0, limited 1, semi_limited 2,
legal 3.

Build (the default) reads .cache/ygojson/cards.json and .cache/ygoprodeck/cardinfo.json, matches a YGOJSON card to
ours through identifiers.ygojsonId, reads Yugipedia's list pages from LIST_PAGES onward, and adds:

  history  every dated entry of a card's YGOJSON legality history in tcg, ocg and speed (speed_duel), as an event with
           `effective` and source "ygojson". forbidden is banned, limited limited, semilimited semi_limited,
           unlimited legal. Speed Duel's limit1 and limit2 are limited and semi_limited, and limit3 is legal.
           unreleased is not a status and makes no event.
  lists    every change a tcg or ocg list makes, as an event with the list's `effective` date and source "yugipedia".
           A list names every limited card, so a card it leaves out is legal, unless a name on the list matches no
           single card of ours: the card left out may be that name, so that list moves only the cards it names. A card
           that already has an event on that date keeps it, and a list that starts after today waits. The walk stops at
           a page of another medium or format, at a date that does not move forward, or at a page that drops over a
           quarter of the last list, and the tool prints the last date it read.
  current  the status of the lead source: YGOPRODeck's banlist_info for tcg, ocg and goat (a card with no entry for a
           format is legal, except a name with < >: YGOPRODeck gives none of them a status, including cards Konami's
           list limits, so its silence says nothing), YGOJSON's current for speed_duel. It becomes an event only when it differs from the card's
           last event (or from legal when there is none), with `inForceBy` set to the day the tool first saw it. The
           change may have started earlier: neither source says when. The source is "ygoprodeck" or "ygojson".

Events with `effective` already in legality/bans.json are never rewritten or removed. An `inForceBy` event is removed
once the dated events give the same status on its date, because they say when the change happened. A `legal` one also
goes once the lead source no longer states the card, since nothing then says the card is free of a restriction. Any
other stays and keeps its date, so a difference between the sources stays visible. A history entry whose card, format and
date already have an event is not added again. Events are sorted by card id, format and date.

--check replays the committed events to today and compares them with the lead source's current status: it prints
each difference and exits 1 if there is any. It needs YGOPRODeck's list (downloaded into .cache/ygoprodeck when it
is not there; --refresh downloads it again). It also needs .cache/ygojson to check speed_duel and skips that format
without it. A difference means a ban list changed since the last run of this tool: run it without --check.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import re
import sys
import unicodedata

import ygjson
import ygoprodeck
import yugipedia

YGOJSON_CARDS = ygjson.ROOT / ".cache" / "ygojson" / "cards.json"
BANS = ygjson.LEGALITY / "bans.json"

STATUS = {"forbidden": "banned", "limited": "limited", "semilimited": "semi_limited", "unlimited": "legal",
          "limit1": "limited", "limit2": "semi_limited", "limit3": "legal"}
YGOJSON_FORMATS = {"tcg": "tcg", "ocg": "ocg", "speed": "speed_duel"}
YGOPRODECK_STATUS = {"Forbidden": "banned", "Limited": "limited", "Semi-Limited": "semi_limited"}
YGOPRODECK_FORMATS = {"ban_tcg": "tcg", "ban_ocg": "ocg", "ban_goat": "goat"}
LEAD = {"tcg": "ygoprodeck", "ocg": "ygoprodeck", "goat": "ygoprodeck", "speed_duel": "ygojson"}
FAR_FUTURE = "9999-12-31"
# YGOJSON's exact dates end with these lists. The walk starts on them, so it also corrects a status YGOJSON got wrong.
LIST_PAGES = {"tcg": ("October 2025 Lists (TCG)", "TCG"), "ocg": ("October 2025 Lists (OCG)", "OCG")}

Key = tuple[str, str]  # (card id, format id)


def event_date(event: dict) -> str:
    return event.get("effective") or event["inForceBy"]


def sort_events(events: list[dict]) -> list[dict]:
    """By card id (numeric), format, date. Events of one date keep their order."""
    return sorted(events, key=lambda e: (int(e["card"]), e["format"], event_date(e)))


def current(events: list[dict], as_of: str) -> dict[Key, str]:
    """{(card, format): status} in force on as_of: each card's last event on or before it. A card with no such event
    is legal and has no entry."""
    out: dict[Key, str] = {}
    for e in sort_events(events):
        if event_date(e) <= as_of:
            out[(e["card"], e["format"])] = e["status"]
    return out


def ygojson_ids(files: dict[str, dict]) -> dict[str, str]:
    """{YGOJSON card uuid: our card id}."""
    return {c["identifiers"]["ygojsonId"]: c["id"] for body in files.values() for c in body["cards"]
            if "ygojsonId" in c.get("identifiers", {})}


def history_events(ygojson_cards: list[dict], ids: dict[str, str]) -> list[dict]:
    """One event per dated history entry of every YGOJSON card we have, in tcg, ocg and speed."""
    out = []
    for c in ygojson_cards:
        card = ids.get(c["id"])
        if card is None:
            continue
        for fmt, body in (c.get("legality") or {}).items():
            if fmt not in YGOJSON_FORMATS:
                continue
            for h in body.get("history", []):
                if h["legality"] in STATUS:
                    out.append({"card": card, "format": YGOJSON_FORMATS[fmt], "status": STATUS[h["legality"]],
                                "effective": h["date"], "source": "ygojson"})
    return out


def lead_status(prodeck_cards: list[dict] | None, ygojson_cards: list[dict] | None, ids: dict[str, str],
                card_ids: set[str]) -> dict[Key, str]:
    """The lead source's current status. tcg, ocg and goat: every card of ours YGOPRODeck lists, legal when its
    banlist_info has no entry, and no status for a name with < > that has no banlist_info. speed_duel: every card YGOJSON matches and gives a status."""
    out: dict[Key, str] = {}
    for c in prodeck_cards or []:
        card = str(c["id"])
        if card not in card_ids:
            continue
        info = c.get("banlist_info") or {}
        if not info and "<" in c.get("name", ""):
            continue
        for key, fmt in YGOPRODECK_FORMATS.items():
            out[(card, fmt)] = YGOPRODECK_STATUS.get(info.get(key), "legal")
    for c in ygojson_cards or []:
        card = ids.get(c["id"])
        status = STATUS.get(((c.get("legality") or {}).get("speed") or {}).get("current"))
        if card is not None and status is not None:
            out[(card, "speed_duel")] = status
    return out


def _name_key(name: str) -> str:
    """A name without case, spaces and punctuation: Yugipedia writes "Maliss P Dormouse" for "Maliss <P> Dormouse"."""
    return re.sub(r"[\W_]", "", unicodedata.normalize("NFKC", name).casefold())


def ids_by_name(files: dict[str, dict]) -> dict[str, str | None]:
    """{name key: card id}, with None for a key two cards share."""
    out: dict[str, str | None] = {}
    for body in files.values():
        for c in body["cards"]:
            key = _name_key(c["name"])
            out[key] = None if key in out and out[key] != c["id"] else c["id"]
    return out


def list_statuses(named: dict[str, str], ids: dict[str, str | None]) -> tuple[dict[str, str], list[str]]:
    """({card id: status}, the names that match no card or more than one) for a list's {card name: status}."""
    statuses, unmatched = {}, []
    for name, status in named.items():
        card = ids.get(_name_key(name))
        if card is None:
            unmatched.append(name)
        else:
            statuses[card] = status
    return statuses, unmatched


def list_events(lists: list[dict], dated: list[dict], today: str) -> list[dict]:
    """One event per card each list moves, oldest list first, comparing with `dated` and the events before it. A list
    is {format, date, statuses: {card id: status}, complete}. A card it leaves out is legal only when `complete`, which
    says every name on the list matched a card."""
    out: list[dict] = []
    for item in sorted(lists, key=lambda l: (l["format"], l["date"])):
        if item["date"] > today:
            continue
        fmt = item["format"]
        before = {card: s for (card, f), s in current(dated + out, item["date"]).items() if f == fmt}
        cards = before.keys() | item["statuses"].keys() if item["complete"] else item["statuses"].keys()
        for card in sorted(cards, key=int):
            status = item["statuses"].get(card, "legal")
            if before.get(card, "legal") != status:
                out.append({"card": card, "format": fmt, "status": status, "effective": item["date"], "source": "yugipedia"})
    return out


def merge(existing: list[dict], history: list[dict], lead: dict[Key, str], today: str,
          lists: list[dict] = ()) -> tuple[list[dict], list[dict]]:
    """(all events sorted, the events added). Existing dated events are kept as they are. A history or list event is
    added unless the card, format and date already have one. An existing inForceBy event is dropped when the dated
    events give the same status on its date, or when it says legal and the lead no longer states the card. A lead status that differs from the last event is added with inForceBy
    today."""
    seen = {(e["card"], e["format"], e["effective"]) for e in existing if "effective" in e}
    new = [e for e in history if (e["card"], e["format"], e["effective"]) not in seen]
    dated = [e for e in existing if "effective" in e] + new
    seen |= {(e["card"], e["format"], e["effective"]) for e in new}
    listed = [e for e in list_events(list(lists), dated, today) if (e["card"], e["format"], e["effective"]) not in seen]
    new += listed
    dated += listed
    unexplained = [e for e in existing if "inForceBy" in e
                   and (e["status"] != "legal" or (e["card"], e["format"]) in lead)
                   and current(dated, e["inForceBy"]).get((e["card"], e["format"]), "legal") != e["status"]]
    existing = [e for e in existing if "effective" in e] + unexplained
    events = sort_events(existing + new)
    last = current(events, FAR_FUTURE)
    for (card, fmt), status in sorted(lead.items(), key=lambda kv: (int(kv[0][0]), kv[0][1])):
        if last.get((card, fmt), "legal") != status:
            new.append({"card": card, "format": fmt, "status": status, "inForceBy": today, "source": LEAD[fmt]})
    return sort_events(existing + new), sort_events(new)


def check(events: list[dict], lead: dict[Key, str], as_of: str) -> list[str]:
    """One message per (card, format) whose replayed status is not the lead source's."""
    replay = current(events, as_of)
    return [f"card {card} {fmt}: events say {replay.get((card, fmt), 'legal')}, {LEAD[fmt]} says {status}"
            for (card, fmt), status in sorted(lead.items(), key=lambda kv: (int(kv[0][0]), kv[0][1]))
            if replay.get((card, fmt), "legal") != status]


def _load_ygojson() -> list[dict] | None:
    import json
    return json.loads(YGOJSON_CARDS.read_text(encoding="utf-8")) if YGOJSON_CARDS.exists() else None


def _read_lists(files: dict[str, dict]) -> tuple[list[dict], list[str]]:
    """(the lists from LIST_PAGES onward, with card ids, and the list names that match no single card)."""
    ids = ids_by_name(files)
    lists, unmatched = [], set()
    for fmt, (title, medium) in LIST_PAGES.items():
        read = yugipedia.limitation_lists(title, medium)
        print(f"{fmt} lists read through {read[-1]['date']}")
        for item in read:
            statuses, missing = list_statuses(item["statuses"], ids)
            lists.append({"format": fmt, "date": item["date"], "statuses": statuses, "complete": not missing})
            unmatched.update(missing)
    return lists, sorted(unmatched)


def _counts(events: list[dict]) -> None:
    print(f"{len(events)} events")
    print("by format: " + ", ".join(f"{k} {v}" for k, v in sorted(collections.Counter(e["format"] for e in events).items())))
    print("by status: " + ", ".join(f"{k} {v}" for k, v in sorted(collections.Counter(e["status"] for e in events).items())))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="compare the committed events with the lead sources; exit 1 on a difference")
    ap.add_argument("--refresh", action="store_true", help="download YGOPRODeck's card list again")
    ap.add_argument("--as-of", default=datetime.date.today().isoformat(), help="the date to replay to, and to stamp new events with")
    args = ap.parse_args()

    files = ygjson.load_cards()
    card_ids = {c["id"] for body in files.values() for c in body["cards"]}
    ids = ygojson_ids(files)
    existing = ygjson.load_legality()["events"]
    prodeck = ygoprodeck.cards(refresh=args.refresh)
    ygojson_cards = _load_ygojson()

    if args.check:
        lead = lead_status(prodeck, ygojson_cards, ids, card_ids)
        if ygojson_cards is None:
            print("speed_duel not checked: no .cache/ygojson")
        problems = check(existing, lead, args.as_of)
        for p in problems:
            print(p)
        _counts(existing)
        print(f"{len(problems)} differences from the lead sources on {args.as_of}")
        sys.exit(1 if problems else 0)

    if ygojson_cards is None:
        sys.exit(f"{YGOJSON_CARDS} is missing: download YGOJSON's aggregate cards.json there first")
    lead = lead_status(prodeck, ygojson_cards, ids, card_ids)
    lists, unmatched = _read_lists(files)
    events, new = merge(existing, history_events(ygojson_cards, ids), lead, args.as_of, lists)
    errors = ygjson.validate(ygjson.load_sets(), ygjson.load_eras(), files, ygjson.load_archetypes(),
                             ygjson.load_sealed(), {"formats": ygjson.load_legality()["formats"], "events": events})
    if errors:
        sys.exit("refusing to write:\n" + "\n".join(errors[:20]))
    ygjson.save_json(BANS, {"events": events})
    _counts(events)
    print(f"{len(new)} new today, {len(existing) + len(new) - len(events)} undated rows replaced")
    if unmatched:
        print(f"{len(unmatched)} list names match no single card: " + ", ".join(unmatched))
    if new:
        print("new by source: " + ", ".join(f"{k} {v}" for k, v in sorted(collections.Counter(e["source"] for e in new).items())))


if __name__ == "__main__":
    main()
