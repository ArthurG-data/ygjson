"""Write legality/bans.json from YGOJSON's ban history and the current lists of YGOPRODeck and YGOJSON, or check it.

    uv run python tools/legality.py [--check] [--refresh] [--as-of YYYY-MM-DD]

An event says a card's status in a format changed. A status in force on a date is the card's last event on or before
it, and before its first event the card is legal. Statuses are copies allowed: banned 0, limited 1, semi_limited 2,
legal 3.

Build (the default) reads .cache/ygojson/cards.json and .cache/ygoprodeck/cardinfo.json, matches a YGOJSON card to
ours through identifiers.ygojsonId, and adds:

  history  every dated entry of a card's YGOJSON legality history in tcg, ocg and speed (speed_duel), as an event with
           `effective` and source "ygojson". forbidden is banned, limited limited, semilimited semi_limited,
           unlimited legal. Speed Duel's limit1 and limit2 are limited and semi_limited, and limit3 is legal.
           unreleased is not a status and makes no event.
  current  the status of the lead source: YGOPRODeck's banlist_info for tcg, ocg and goat (a card with no entry for a
           format is legal), YGOJSON's current for speed_duel. It becomes an event only when it differs from the card's
           last event (or from legal when there is none), with `inForceBy` set to the day the tool first saw it. The
           change may have started earlier: neither source says when. The source is "ygoprodeck" or "ygojson".

Events already in legality/bans.json are never rewritten or removed, so a date stays what it was when first written.
A history entry whose card, format and date already have an event is not added again. Events are sorted by card id,
format and date.

--check replays the committed events to today and compares them with the lead source's current status: it prints
each difference and exits 1 if there is any. It needs YGOPRODeck's list (downloaded into .cache/ygoprodeck when it
is not there; --refresh downloads it again). It also needs .cache/ygojson to check speed_duel and skips that format
without it. A difference means a ban list changed since the last run of this tool: run it without --check.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import sys

import ygjson
import ygoprodeck

YGOJSON_CARDS = ygjson.ROOT / ".cache" / "ygojson" / "cards.json"
BANS = ygjson.LEGALITY / "bans.json"

STATUS = {"forbidden": "banned", "limited": "limited", "semilimited": "semi_limited", "unlimited": "legal",
          "limit1": "limited", "limit2": "semi_limited", "limit3": "legal"}
YGOJSON_FORMATS = {"tcg": "tcg", "ocg": "ocg", "speed": "speed_duel"}
YGOPRODECK_STATUS = {"Forbidden": "banned", "Limited": "limited", "Semi-Limited": "semi_limited"}
YGOPRODECK_FORMATS = {"ban_tcg": "tcg", "ban_ocg": "ocg", "ban_goat": "goat"}
LEAD = {"tcg": "ygoprodeck", "ocg": "ygoprodeck", "goat": "ygoprodeck", "speed_duel": "ygojson"}
FAR_FUTURE = "9999-12-31"

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
    banlist_info has no entry. speed_duel: every card YGOJSON matches and gives a status."""
    out: dict[Key, str] = {}
    for c in prodeck_cards or []:
        card = str(c["id"])
        if card not in card_ids:
            continue
        info = c.get("banlist_info") or {}
        for key, fmt in YGOPRODECK_FORMATS.items():
            out[(card, fmt)] = YGOPRODECK_STATUS.get(info.get(key), "legal")
    for c in ygojson_cards or []:
        card = ids.get(c["id"])
        status = STATUS.get(((c.get("legality") or {}).get("speed") or {}).get("current"))
        if card is not None and status is not None:
            out[(card, "speed_duel")] = status
    return out


def merge(existing: list[dict], history: list[dict], lead: dict[Key, str], today: str) -> tuple[list[dict], list[dict]]:
    """(all events sorted, the events added). Existing events are kept as they are; a history event is added unless
    the card, format and date already have one; a lead status that differs from the last event is added with
    inForceBy today."""
    seen = {(e["card"], e["format"], e["effective"]) for e in existing if "effective" in e}
    new = [e for e in history if (e["card"], e["format"], e["effective"]) not in seen]
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
    events, new = merge(existing, history_events(ygojson_cards, ids), lead, args.as_of)
    errors = ygjson.validate(ygjson.load_sets(), ygjson.load_eras(), files, ygjson.load_archetypes(),
                             ygjson.load_sealed(), {"formats": ygjson.load_legality()["formats"], "events": events})
    if errors:
        sys.exit("refusing to write:\n" + "\n".join(errors[:20]))
    ygjson.save_json(BANS, {"events": events})
    _counts(events)
    print(f"{len(new)} new today")
    if new:
        print("new by source: " + ", ".join(f"{k} {v}" for k, v in sorted(collections.Counter(e["source"] for e in new).items())))


if __name__ == "__main__":
    main()
