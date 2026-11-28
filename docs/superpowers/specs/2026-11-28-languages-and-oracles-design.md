# Printings in every Western language, card text, oracles and UUIDs

Date: 2026-11-28. Status: for approval.

## Why

ygjson is one of three sister datasets, with pkmjson (Pokémon) and rbjson (Riftbound), and AutoMana is the only
reader. It stores ygjson's ids, and AutoMana's API will accept them as input to fetch its data, once the site is
public. A review found two things ygjson lacks and its sisters have:

- **Printings in other languages.** Every printing is English (`<print uuid>:en:<edition>`). The schema accepts no
  other language. A card's name is given in ten languages, but there is no French or German printing with its own id.
- **Oracles.** There is no `oracleId` and no card text.

The owner wants ygjson to have the same features as pkmjson and rbjson. The field names don't have to match theirs.
Nobody outside AutoMana reads the data yet, so the shape can change. But every id already published must keep
resolving, as the stable-ids design requires.

## Goals

1. A printing per language for the Western Yu-Gi-Oh! TCG languages: English, French, German, Italian, Spanish and
   Portuguese. Each printing has its own id, number (`LOB-FR001`), rarity and editions.
2. Card text in each language YGOJSON has, credited to Konami.
3. An `oracleId` on every card and printing.
4. A `uuid` on every record: set, card, print, printing, archetype and sealed product. It never changes and is never
   reused.
5. A short written plan for the Asian sets (Japanese, Korean, Chinese), to come after this ships.
6. A handoff for AutoMana, so it reads the new shape, stores ygjson's UUIDs as they are, and accepts them on its API.

## Non-goals

- The Asian sets themselves (see [Later: the Asian sets](#later-the-asian-sets)).
- The French Canadian printings (YGOJSON locale `fc`, 228 printings). They have their own numbers and a handful of
  sets. They can join later as `fr` printings or as a region.
- Prices for non-English printings. TCGplayer sells English singles only, so `tcgplayer` and `tcgplayerPrice` stay
  on English printings. Cardmarket, which pkmjson and rbjson carry, is a separate project.
- Sealed products per language (pkmjson's product releases). TCGplayer's sealed catalogue is English.
- Translated enum labels (pkmjson's `AllTranslations.json`).
- Matching the other projects' file names, key formats or field names.

## Anti-goals

- **An id already published stops resolving.** Every English print and printing id from 0.3.0 stays live and keeps its
  key. Nothing in this change retires an id.
- **Text credited to Konami that is not Konami's.** YGOJSON marks 371 English texts `official: false`: fan
  translations of cards never printed in English. They are not shipped.
- **AutoMana's import breaks.** AutoMana downloads `releases/latest`, and its importer refuses a printing whose
  language is not English. The first release with French printings must not be published before AutoMana accepts it
  (see [Order of work](#order-of-work)).

## What exists today

- `tools/import_ygojson.py` already matches our sets to YGOJSON sets (five rules, English locales only), our cards to
  YGOJSON cards, and, in `match_scans`, each YGOJSON English printing to one of our prints. It does this to attach
  Yugipedia scans.
- A YGOJSON set lists its `contents` per locale. A YGOJSON printing (`{"id", "card", "suffix", "rarity"}`) keeps the
  same `id` in every locale that prints it. Its number is the locale's `prefix` plus `suffix` (`LOB-FR` + `001`).
- Measured on the cached aggregate, for the five non-English Western locales (`fr`, `de`, `it`, `sp`, `pt`):
  - 180,231 YGOJSON printing slots share their YGOJSON printing id with an English printing of the same set.
  - 354 are a printing the set's English list lacks: a rarity or card only that language has (238 of them Portuguese).
  - 59 sit in sets that have no English locale at all.
  - Of the 180,231, the reviewer measured 163,765 that reach exactly one of our prints through today's English match.
    3,278 reach two or three, in the 14 oldest sets: YGOJSON gives `LOB-`, `LOB-E` and `LOB-EN` one printing id,
    where YGOPRODeck lists three prints. About 11,700 reach none: 4,369 colour rarities whose English print is a
    TCGplayer colour variant (`:blue`), about 3,400 in sets whose English locale has no prefix, 2,946 at a number we
    have no print of, 550 whose card is not matched, and 348 whose only prints are variants or from TCGplayer.
- **YGOJSON stopped on 2025-10-25.** Its aggregate branch has not moved since. 717 of our cards have no YGOJSON card,
  and no set released since then has a non-English printing in it.
- YGOJSON gives card text as `text.<language>.{name, effect, pendulumEffect, official}`. `effect` exists for 14,329 of
  14,342 cards in English and in up to ten languages.
- No two cards share an English name, and a reprint keeps its card's passcode. So a ygjson card is already one
  gameplay card.
- The ledger `ids/` gives prints a UUID. Printing ids are `<print uuid>:<language>:<edition>`. Cards, sets,
  archetypes and sealed products have ledger entries but readable ids only (passcode, slugs).

## Approaches

Picked in the conversation:

1. **Western languages only.** These are printings of the sets ygjson already has. Prices stay where they are.
2. Western and Asian at once. This adds about 1,464 sets sold only in Japanese, Korean or Chinese, with their own
   numbering, rarities and no TCGplayer data.
3. **Western now, and a plan for the Asian sets later.** Chosen. The Western languages fit what ygjson already
   models. The Asian sets are a second catalogue, easier to design once printings carry a language.

On names, the owner chose "same features, not necessarily the same names". ygjson keeps its ids and its
print/printing split, and adds what is missing. It does not copy pkmjson's keys.

## Design

### Prints and printings

The model stays: a **card** (gameplay card), a **print** (the card in one set, at one slot and rarity) and a
**printing** (a print in one language and edition).

- A print gains its other languages. For each language other than English, the print records its `number`
  (`LOB-FR001`), its `editions` in that language and its YGOJSON printing id. English stays where it is today, so no
  English print or printing changes.
- A non-English YGOJSON printing whose id is the YGOJSON id of one of our prints (through the English match that
  `match_scans` makes) becomes that print's printing in that language.
- A non-English YGOJSON printing with no English twin (the 354) becomes a new print with `source: ygojson`. Its key
  uses its own number: `<set>:<card>:LOB-PT001:super_rare`. It has printings in its languages only.
- When one YGOJSON id reaches several English prints (`LOB-001`, `LOB-E001`, `LOB-EN001`), the printing's region
  picks one. A two-letter region (`LOB-FR`, `IOC-DE`) goes on the `EN` print, the modern numbering it shares. A
  one-letter region (`LDD-F`, `LOB-G`, `PMT-I`) goes on the `E` print, the European release it was printed with, else
  on the print with no region. Anything still ambiguous goes to review.
- A colour rarity (`ultra-blue`) goes on the colour-variant print (`:blue`) of that number, whoever minted it: the print
  is the physical card, whatever its source.
- In a set whose English locale has no prefix, the suffix is the whole number. The match reads it so.
- A YGOJSON printing still not placed after these rules (no print of ours at that number, card not matched, only
  TCGplayer prints), or in a set with no English locale (the 59), goes to a review file, not to the data. The README
  states how many.
- A printing's rarity is its print's rarity. No YGOJSON printing id has two rarities across the Western locales (0 of
  48,315), so a language that prints the card at another rarity has its own YGOJSON id, and the rule above makes it
  its own print.
- A printing's number is its own locale's prefix plus suffix, never derived from the English number: 1,481 YGOJSON
  printings have another suffix in some language than in English.
- A printing's editions are the editions that locale's `contents` entry lists. An edition YGOJSON leaves empty
  falls back to the set's editions, as English does today.
- A printing in another language has the `scan` of its own locale's `cardImages`, as English printings do today.
- `language` takes `en`, `fr`, `de`, `it`, `es`, `pt`. YGOJSON's `sp` is `es`. Regional English printings (`LOB-E001`,
  Asian English) stay what they are today: English prints that YGOPRODeck states, with their `region`.
- Printing ids keep their form, `<print uuid>:<language>:<edition>`, and their key `<print key>:<language>:<edition>`.
  French printings come in as new ledger entries, added like any other new id.

### Set releases

A set gains a release per language, from YGOJSON's locales: `language`, `name` (YGOJSON's name in that language, else
the English name), `releaseDate`, `prefix` and key art. `releases[].language` widens to the six languages. English
stays the first release, so the code that reads `releases[0]` (eras, rename evidence) keeps reading English.

### Card text

- A card gains `text`: `{language: {"effect": ..., "pendulumEffect": ...}}`, for the ten languages `names` uses.
  English comes from YGOPRODeck (`desc`, and `pend_desc`/`monster_desc` on Pendulum monsters), which is current and
  covers every card. The other languages come from YGOJSON. `pendulumEffect` appears only on Pendulum monsters.
- A text marked `official: false` is not shipped, nor is an empty one.
- `NOTICE` says that card text is Konami's, reproduced as Konami published it, gathered by YGOPRODeck (English) and YGOJSON (the other languages). The line "No
  effect text ... is copied into the data" goes.
- The SQLite package gains the text, one row per card and language.

### Oracles

- Every card gets an `oracleId`, a UUID. Every printing carries its card's `oracleId`.
- An oracle is one gameplay card. Today each oracle holds exactly one card, because no two cards share a name and
  reprints share a passcode. The oracle is still its own record, so a later change (the Asian sets, a placeholder card
  replaced by its passcode) can put two card ids under one oracle without changing an `oracleId`.
- An oracle is minted from its first card: `uuid5(YGJSON_NAMESPACE, "oracle:<card id>")`. The ledger keeps it, and a
  card that succeeds another (the stable-ids rules) keeps its predecessor's oracle.

### UUIDs on every record

- Sets, cards, archetypes and sealed products gain a `uuid` in their ledger entry and in the release files, minted
  when first seen as `uuid5(YGJSON_NAMESPACE, "<kind>:<id>")` and kept by the ledger after that. A set or archetype
  renamed through the existing rename handling keeps its UUID.
- A printing gains `uuid`, `uuid5(YGJSON_NAMESPACE, "printing:<printing id>")`. Its id already rests on the print's
  UUID, so the printing's UUID is as stable as the print.
- A print's `id` is already a UUID. It stays as it is.
- `Ids.json` lists each record's UUID next to its readable id, so a reader holding either finds the other. This is
  what pkmjson's `AllUuids.json` gives.
- `meta.idsVersion` becomes `2`.

### Release files and size

The files keep their names. The five languages add about 180,000 print-and-language pairs, more printings than that
once editions are counted, against today's 89,730 printings. `AllPrintings.json` (47 MB today, 6 MB gzipped) and
`Ids.json` (36 MB) grow accordingly, and so does the SQLite package. That growth is accepted. GitHub's limit is 2 GB
per asset. A file committed to git is another matter: GitHub refuses one over 100 MB. `ids/printings.json` (20 MB
today) would reach 75 to 90 MB, so the ledger's printings are split (by language, or otherwise) so that no committed
file passes 50 MB.

### Checks

- Every non-English printing has a print and a number with that language's prefix.
- A print's languages name only `fr`, `de`, `it`, `es`, `pt`.
- A card's `text` names only the ten languages, and no text is unofficial.
- Every record has a `uuid`, no two records share one, and `ids.py --check-against` refuses a UUID or `oracleId` that
  changed.

## Order of work

ygjson's plan changes ygjson only. AutoMana's work is handed off as documents, for a session in AutoMana's repository.

1. **ygjson, additive.** UUIDs on every record, oracles, card text and set releases per language. AutoMana's
   importer loads these as they are (it ignores fields it does not know), so they can merge and the weekly refresh
   can release them. The first of these pull requests sets the version to 0.4.0.
2. **AutoMana, first handoff.** A short document: its importer skips a printing whose language is not English instead
   of failing (`ygjson_build.py:290` raises today). AutoMana reads `releases/latest`, so this must be deployed before
   step 3 merges.
3. **ygjson, the non-English printings.** The pull request stays open until the owner confirms step 2 is deployed.
   Once it merges, the weekly refresh releases it.
4. **AutoMana, second (the handoff).** ygjson writes a handoff document for AutoMana, its issues to file there:
   - **Importer.** Store ygjson's UUIDs as AutoMana's external ids instead of hashing ygjson's id strings into its own
     (`ygjson_build.py` does `uuid5` of `print:<id>` today). Import the non-English printings, the card text and the
     `oracleId`.
   - **API.** Accept a ygjson UUID (set, card, print, printing, oracle) as input to fetch AutoMana's data.
   - **The underlying view.** `yugioh_catalog.card_search` already has one row per printing (a print in one
     language and edition), and its text falls back to the printing's language. Three things change:
     - It needs the printing's language as a column to filter on.
     - Its grid tile (`rep`) is per card with an English name. It has to choose English first, the way
       `riftbound_catalog.card_search` does, or become per card and language, the way One Piece's does.
     - `card_catalog.v_printing_lang` marks every Yu-Gi-Oh! printing `is_default_lang = true`. That has to compare
       the printing's language with the default instead.
   - **UI.** Display a printing's language, and filter the card grid, the search and a card page's print table by
     language.
5. **The Asian plan**, written once 0.4.0 is out.

## Later: the Asian sets

A separate design, after 0.4.0. What is known now:

- YGOJSON has 1,464 sets sold only in Asian languages: 26,238 Japanese, 18,183 Korean, 8,147 Simplified Chinese and
  556 Traditional Chinese printings. Most Asian sets are OCG products that YGOPRODeck, ygjson's spine, does not list.
- Their cards are the same gameplay cards (same passcodes), so they join existing cards and oracles. OCG-only cards
  that YGOPRODeck lacks would be new cards.
- They need their own set ids, numbers (`LOB-JP001`), and the OCG rarities `rarities.py` does not know yet.
- pkmjson keeps two trees, `international` and `asia`. Whether ygjson needs that, or only a language on each set, is
  that design's first question.

## Left to the builder

- The data-file shape of a print's other languages, provided English stays where it is.
- How `match_scans`' English match is shared with the new language step, and the name of the review file.
- How the SQLite package lays out printings per language and the text.
- README wording and the order of the commits within step 2.

## My calls (for the owner to check)

- Non-English printings with no English twin become their own prints. The alternative was leaving them out, which
  loses 354 printings.
- Unofficial (fan-translated) texts are left out, so nothing not Konami's is credited to Konami.
- `oracleId` is its own record even though it maps one-to-one onto cards today.
- French Canadian printings are left out for now.
- The non-English printings wait for AutoMana by holding their pull request, not by pausing the refresh.
- Old-set printings follow their region (two letters to `EN`, one letter to `E`), and colour rarities go on colour
  variants, even ones TCGplayer minted.
- Sets get a release per language, and non-English printings get their scans.
- English text comes from YGOPRODeck, not YGOJSON, because YGOJSON stopped in October 2025.
