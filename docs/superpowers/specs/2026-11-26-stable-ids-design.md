# Stable ids

Date: 2026-11-26. Status: for approval.

## Why

The owner stores ygjson ids in their own systems (AutoMana collections among them). **An id ygjson has published must
never disappear.** Today it can: a print id is built from facts we keep correcting, so a correction gives the print a
new id and the old one is gone.

Measured over the history of `main` and this branch, 223 print ids disappeared while their card and number still
exist:

- 197 because the rarity was corrected: `legendary-5d-s-decks:93708824:L5DD-ENA12:unknown` became `…:common`;
  `starter-deck-yu-gi-oh-5d-s:97204936:5DS1-EN042:common` became `…:super_rare`.
- 26 because a variant appeared or vanished: `quarter-century-stampede:74677427:RA04-EN109:platinum_secret_rare`
  split into `…:4th-art` and `…:7th-art`; `quarter-century-bonanza:24094653:RA03-EN051:collectors_rare:a` became the
  base print (and `:b` stayed).
- One old id can stand for several prints: `the-chronicles-deck-spirit-charmers-all-foil-edition:37744402:CH02-EN003:unknown`
  became a `secret_rare` and a `starlight_rare`.

Printing ids are `<print id>:<language>:<edition>`, so they disappeared with their prints, and they also disappear
when a print's editions are corrected.

Card ids disappear too. A card id is YGOPRODeck's id. YGOPRODeck gives an unreleased card a placeholder id above
100,000,000 and replaces it with the passcode once the card is out. 76 such placeholder cards sit in `data/cards`
today (they are only kept because of a bug); each has exactly one live card with the same English name, e.g.
`101403001` and `82951145`, both "Helpoemer, Chanter of the Sun God".

Set ids and archetype slugs have never changed, but they can: a new name that sorts earlier takes an existing slug
(`ygjson.dedupe_slugs`), and sealed ids are recomputed from TCGplayer names on every run.

## Goals

1. Every id ygjson has ever published (in a release or on `main`) resolves forever, to a live record or to a retired
   record that says what replaced it.
2. A print's id never changes when its rarity or variant is corrected, or when it moves to another set with the same
   card, printed number, rarity and variant. A print whose number changes keeps its id only with product evidence;
   without it the old id is retired with the new print as its successor, because another number may be another card.
3. Ids are the same on every machine for the same inputs and history: two people rebuilding get the same ids.
4. Anyone holding an old readable print id can find the print it became.
5. CI fails if a change would make a published id disappear.

## Non-goals

- Fixing the matching bugs from the review (cross-set treatments, stale editions, retired cards kept as live). They
  are separate work. This design only needs that, once fixed, they retire ids instead of dropping them.
- Ids for non-English printings. `language` stays in the printing id so they can come later.
- Making card ids opaque. A passcode is printed on the card and never changes; only placeholders churn.

## Anti-goals

- **An id that resolves to the wrong print.** That is worse than a retired id: a collection would silently hold a
  card it does not hold. When the evidence for "A became B" is not conclusive, A is retired with its candidates
  listed, never guessed onto one of them. (This matches the project's rule: what no rule settles goes to review.)
- An id scheme that recomputes ids from facts. MTGJSON derived its uuids from card facts and broke them when the facts
  changed; that is the failure we are leaving.

## Approaches considered

- **A. Freeze the readable ids.** A print keeps the readable id it was born with. Rejected: the id then contradicts the
  print's own fields (about 200 ids would already say `unknown` for a known rarity), and gets worse with every fix.
- **B. Opaque permanent ids in a committed ledger, with the readable key kept as a field. Chosen by the owner.** The
  id carries no facts, so no correction can change it. Every readable key a print ever had stays findable.
- **C. Keep recomputing readable ids, publish redirects.** Rejected: ids still disappear from the data; every reader
  must follow redirects.

## Design

### Two names for a print

- `key`: today's readable id, `<set id>:<card id>:<number>:<rarity>[:<variant>]`, computed exactly as now. It
  describes the print and **may change**. The importers keep using it to find a print between runs, so their logic does
  not change.
- `id`: a UUID, minted once and **never changed**. It is what readers store.

A print record gains `id` (UUID) and `key` (today's id). `formerKeys` lists the keys the print had before, oldest
first. A printing's id becomes `<print id>:<language>:<edition>` (`7c1d…e9:en:first`), and its record carries
`key`, `<print key>:<language>:<edition>`, for readability.

### The ledger

`ids/` holds the committed ledger, one file per kind, sorted, written by `save_json` so diffs stay readable:

| File | Holds one entry per |
|---|---|
| `ids/prints.json` | print id ever issued: `id`, `key`, `formerKeys`, `status` (`live` or `retired`), `successors`, and `products`, the TCGplayer product ids it held when last live (the evidence rule 2 needs once the importers have moved them) |
| `ids/printings.json` | printing id ever issued: `id`, `key`, `formerIds` (the readable printing ids it was published under, `<print key>:en:<edition>`), `status`, `successors` |
| `ids/cards.json` | card id ever seen: `id`, `name`, `konamiId`, `status`, `successors` (the name and Konami id are the evidence for a successor once the card has left `data/cards`) |
| `ids/sets.json` | set: `id`, the source names it has carried (`names`), `status` |
| `ids/archetypes.json` | archetype: `slug`, the names it has carried, `status` |
| `ids/sealed.json` | sealed product: `id`, its TCGplayer product id, `status` |

The ledger only grows. An entry is never removed, an `id` is never edited, and a `retired` entry is never made `live`
again except by the revival rule below.

### Minting

A new print's id is `uuid5(YGJSON_NAMESPACE, <its key at birth>)`, where `YGJSON_NAMESPACE` is a fixed UUID in
`tools/ygjson.py`. The UUID is computed **once**, at birth, then read from the ledger forever; it is never recomputed
from the current key. Deriving it from the birth key (rather than `uuid4`) makes two people who build the same new
print mint the same id, so branches don't conflict. If that UUID is already in the ledger (a print born with this key
later changed key and is still live), the name hashed is `<birth key>#2`, then `#3`, until the UUID is free.

### Reconcile: carrying ids across a run

A new step, `tools/ids.py`, runs **once, after the whole import pipeline** (after `import_sealed.py`), and before
`validate.py` and `build.py`. The ledger therefore only ever records complete pipeline states. A partial run (one
importer alone) leaves prints in a half-built state, and reconciling it would retire and revive hundreds of ids for
nothing. It compares the prints now in `data/cards` with the ledger and decides each print's id. Doing this in one step
keeps the id rules in one place instead of threading them through every path that changes a key (`_rekey`, variant
splits, minting).

Cards are reconciled first (see Cards), so that a print whose card went from a placeholder id to a passcode is matched
under the passcode: before the rules below, every orphan's key is rewritten through `ids/cards.json`, replacing a
retired card id with its one successor.

Definitions: an **orphan** is a `live` ledger entry whose key no current print has. A **newcomer** is a current print
whose key no `live` ledger entry has as its `key`.

For each newcomer, in this order, the first rule that settles it wins:

1. **Former key.** A `retired` entry has the key as its `key` or in `formerKeys`: that id, made `live` again. (A rarity
   that flips back gets its old id back.) A key that a `live` entry has in its `formerKeys` does not revive anything:
   that print kept its id under its new key, and the newcomer is a different print.
2. **Same TCGplayer product.** Exactly one orphan held one of the newcomer's TCGplayer product ids (its ledger
   `products`), and no other newcomer holds that product: the orphan's id. (Covers variant splits: the product that sat
   on the base print lands on `:4th-art`.)
3. **Same place.** Exactly one orphan and exactly one newcomer share `(set, card, number)`: the orphan's id. (Covers
   rarity corrections, `unknown` becoming known, and `:a` becoming the base print.)
4. **Same card in another set.** Exactly one orphan and exactly one newcomer share `(card, number, rarity, variant)`
   and differ only in set: the orphan's id. The number is printed on the card, so the same card, number, rarity and
   variant is the same physical card filed under another set (on `main`: WCS 2025 Limited Pack's Exodia prints folded
   into 25LP). Decided by the owner.
5. **Hand decision.** `mappings/ids.json` names this key: the id it gives (see Hand decisions).
6. Otherwise: a new id (minting, above).

A number change is deliberately not a rule: the orphan is retired, and the newcomer at the same `(set, card)` is its
successor (below). Decided by the owner.

The id's entry then sets `key` to the new key and appends the old key to `formerKeys`.

Every orphan left after that is `retired`. Its `successors` are the current prints at the first of these places that
holds any, in order (`reconcile._successor_places`):

1. the same `(set, card, number, rarity)`;
2. the same `(set, card, number)`;
3. the same `(card, number, rarity, variant)`, in any set (numbered prints only);
4. the same `(card, number)`, in any set (numbered prints only);
5. the same `(set, card, rarity, variant)`, for a corrected number.

The list may be empty. A reader can follow a single successor without asking anyone. It is listed in `review/ids.json` so a person can
confirm it. A **split** (one orphan, two newcomers, no product evidence) therefore keeps no id: the old id is retired
with both prints as successors, and each print gets a new id. That is the anti-goal at work: we do not guess which of
the two the reader held.

Printings follow their print. A printing id that no longer exists (its print retired, or its edition dropped) is
`retired`; its successors are the same language and edition on the print's successors, or, for a dropped edition,
the print's remaining printings. An edition that comes back makes the same printing id `live` again.

### Hand decisions

`mappings/ids.json` is hand-kept, like the other files in `mappings/`, and each entry cites its evidence. An entry may:

- give a newcomer key the id of a retired print (rule 5), which makes that id `live` again. The decision follows its
  print: when the print's key changes later, the hand key stays in its `formerKeys` and the decision still holds; or
- set the `successors` of a retired print or a retired card. A card given one successor takes its prints there, as a
  successor found by name does.

It may never give a `live` id to a second print; `validate.py` rejects that. This is how a person acts on
`review/ids.json`.

### Cards

When YGOPRODeck drops a card id, the card record leaves `data/cards` (fixing the bug that keeps it) and its ledger
entry in `ids/cards.json` becomes `retired`. Its successor is the one live card with the same English name (from the
ledger's `name`), else the one with the same `konamiId`. With zero or several candidates it is retired with no
successor and goes to review. All 76 placeholder cards today have exactly one successor by name.

### Sets, archetypes and sealed products

These keep readable slugs as ids; their slugs hold only a name, not facts we correct, and none has changed. The ledger
freezes them:

- A set is found by the YGOPRODeck name it carries now or any name in its ledger `names`. A `dedupe_slugs` that is
  given the ledger gives a new name the next free suffix and never takes a slug the ledger holds.
- **A rename** is recognised only by an id the set already carries, never by the name: a new YGOPRODeck name whose set
  has the same YGOJSON id, Yugipedia page id or Konami database id as exactly one set that has just lost its name. That
  set keeps its slug and adds the new name to `names`. With no such id, the new name is a new set, and the old one is
  retired with the new one as its successor when its code and release date match exactly one new set.
- **A deliberate merge** through `mappings/ygoprodeck_set_aliases.json` (on `main`: WCS 2025 Limited Pack into 25LP)
  retires the alias set's slug with the target as its successor. Its name stops finding a set of its own.
- An archetype is found by its name, case-sensitively; a rename is recognised by its YGOJSON id. Otherwise the old slug
  is retired with no successor.
- A sealed product is found by its TCGplayer product id, so a renamed product keeps its slug.
- One that disappears from its source is `retired` and stays in the ledger; it has no successor unless a rule above
  gives one.

### What readers see

- `AllPrintings.json`, `AllCards.json` and `AllProducts.json` reference prints by UUID. Each print and printing record
  has `key`.
- A new release file, `Ids.json`, holds the whole ledger: every id ever issued, its status, its successors, and every
  former key. A reader with any id or any old readable key looks it up there.
- `meta` in every file gains `idsVersion: 1`.
- The release that introduces this is `0.3.0`, and its notes say how to migrate stored ids: look each up in `Ids.json`
  by `key`/`formerKeys`.

### Seeding the ledger

`tools/ids.py --seed` walks the history of `origin/main` (which holds the merged branches and the `v0.1.0`, `v0.2.0`
tags; local `main` is behind it) oldest first and runs reconcile on each commit's prints in turn, starting from an
empty ledger. Every key ever published becomes a ledger entry: a live print's id, a former key of one, or a retired id
with successors. Run once, committed with the change. After that, reconcile only runs forward.

Printing ids were never committed, only built into release files. The seed reads the printing ids from the
`AllPrintings.json` of each GitHub release (`v0.1.0`, `v0.2.0`), since those are the ones anyone could have stored, and
records each as a `formerIds` entry of the printing it became. It also builds the printings of each `main` commit, so
an id built from `main` resolves too.

### Checks

`validate.py` adds:

- every print and printing in the data has a ledger entry, and its `id`/`key` match it;
- every `live` ledger entry is in the data, every `retired` one is not;
- successors exist (live, or retired with their own successors);
- no UUID appears twice.

CI adds a ledger diff against the base branch: no entry removed, no `id` changed, no `formerKeys` shortened. A pull
request that would drop a published id fails.

## Constraints

- No network in reconcile; it reads `data/` and `ids/` only.
- Deterministic: same data, same ledger, same result. Ties are broken by sorted key, never by dict order.
- Python 3.11, standard library only (`uuid`), same style as the other tools.
- The ledger for prints is about 50,000 entries (a few MB). Fine in git.

## Left to the builder

- Exact field order and file shapes beyond the columns above; the JSON Schema for `ids/*.json`.
- How reconcile is wired into the importers (called at the end of each, or a separate command in the documented
  build order).
- Test fixtures. At minimum: a rarity correction keeps the id; `unknown` → known keeps the id; a variant split carries
  the id with the product; a split with no product evidence retires; a flip back revives; a placeholder card retires to
  its passcode; a set rename keeps its slug; the seed over two synthetic commits.
