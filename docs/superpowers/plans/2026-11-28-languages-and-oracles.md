# Printings in every Western language, card text, oracles and UUIDs: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** give ygjson what pkmjson and rbjson have: a printing per Western language, card text, an `oracleId`, and a
UUID on every record. Hand AutoMana what it needs to read them.

**Architecture:** the importers write per-language facts into the committed data, the ledger (`ids/`) mints and keeps
every UUID, and `ygjson.flatten` lays them out in the release files.

- **YGOJSON** gives what it has: the printings and texts up to its last update on 2025-10-25.
- **Yugipedia** fills what YGOJSON lacks. A new pipeline stage reads its per-language set card lists and its card
  pages through the existing `tools/yugipedia.py` client.
- **The pull requests come in two groups:**
  - Group A (Tasks 2–7) is additive. AutoMana loads it as it is.
  - Group B (Tasks 8–11) adds the non-English printings. Its pull request waits until AutoMana skips non-English
    printings.

**Tech Stack:** Python 3.11 under `tools/`, uv, pytest (`pythonpath = ["tools"]`), ruff, mypy, jsonschema (Draft
2020-12), SQLite.

**Spec:** `docs/superpowers/specs/2026-11-28-languages-and-oracles-design.md`

## Global Constraints

- **Languages:** a printing's `language` is one of `en`, `fr`, `de`, `it`, `es`, `pt`. YGOJSON's `sp` and Yugipedia's
  `SP` are `es`. A card's `text` uses the ten languages `names` uses: `en`, `fr`, `de`, `it`, `pt`, `es`, `ja`, `ko`,
  `zh-CN` and `zh-TW`.
- **English stays fixed:** no English print or printing id or key changes. Every id live in v0.3.0's `Ids.json` stays
  live.
- **UUIDs:**
  - A set, card, archetype or sealed product's `uuid` is `uuid5(YGJSON_NAMESPACE, "<kind>:<id>")`, with the kind
    `set`, `card`, `archetype` or `sealed`. It is minted once and then kept by the ledger.
  - A printing's `uuid` is `uuid5(YGJSON_NAMESPACE, "printing:<printing id>")`.
  - An oracle is first minted as `uuid5(YGJSON_NAMESPACE, "oracle:<card id>")`.
  - `YGJSON_NAMESPACE` is `ids.YGJSON_NAMESPACE`.
- **`meta.idsVersion`** becomes `2`.
- **Text:**
  - English text comes from YGOPRODeck (`desc`, and `monster_desc`/`pend_desc` on Pendulum monsters).
  - A text YGOJSON marks `official: false` is never shipped, nor is an empty text, nor Yugipedia's `translated_text`.
  - Card text is credited to Konami in `NOTICE`.
- **File size:** no committed file passes 50 MB.
- **Prices:** `tcgplayer` and `tcgplayerPrice` appear on English printings only.
- **Order of merging:** Group B's pull request does not merge until the owner confirms that AutoMana skips non-English
  printings.
- **Versions:** Group A sets the version to `0.4.0`, and Group B sets it to `0.5.0`.
- **Checks before every commit:** `uv run ruff check`, `uv run mypy` and `uv run pytest -q` pass. No secrets, and no
  `.env`.
- **Commit trailer:** every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Pull requests:** every pull request body ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

## Review Focus

1. **v0.3.0's ids stay live.** Every id live in v0.3.0's `Ids.json` is live after the full pipeline, with its key
   unchanged. The last task of each group checks it against the v0.3.0 release asset.
2. **The ledger split reads both layouts.** `ids.py --check-against origin/main`, run right after the printings ledger
   is split, must read the old single `ids/printings.json` at `origin/main`. Task 2 tests `ledger_at` on both layouts.
3. **One YGOJSON id, several English prints.** An id that reaches `LOB-001`, `LOB-E001` and `LOB-EN001` places a
   `LOB-FR` printing on the EN print and an `LDD-F` printing on the E print. With neither, it goes to review. Task 8
   tests each case.
4. **No text that is not Konami's.** Neither `official: false`, an empty string nor `translated_text` reaches the
   data. Tasks 5 and 10 test each.
5. **Rows that place nowhere.** A Yugipedia row whose card name we lack, a colour rarity whose colour-variant print
   doesn't exist, and a set card list page that doesn't exist each go to review, or to nothing for the missing page,
   and never raise. Tasks 8 and 9 test them.

## Data shapes the tasks share

These are the only cross-task shapes. Each task's Interfaces block refers to them.

- **Print, in `data/cards/*.json`:** a print gains `languages`, and English stays in the print's own fields:

  ```json
  "languages": {"fr": {"number": "LOB-FR001", "editions": ["unlimited"], "ygojsonId": "a3632bfd-…",
                       "scans": {"unlimited": "https://…"}, "source": "ygojson"}}
  ```

  `source` is `ygojson` or `yugipedia`. `editions`, `ygojsonId` and `scans` are optional. With no `editions`, the
  set's editions apply.
- **A print with no English printing:** its `source` is `ygojson` or `yugipedia`, and its `number` is the number of its
  first language, in the order `de`, `es`, `fr`, `it`, `pt`. Its key is `ygjson.print_id(set, card, number, rarity)`.
  It has printings in its `languages` only.
- **Card, in `data/cards/*.json`:** a card gains
  `"text": {"en": {"effect": "…", "pendulumEffect": "…"}, "fr": {…}}`. Each language holds `effect` and/or
  `pendulumEffect`, never empty. A language entry may carry `"source": "yugipedia"`.
- **Set, in `sets/sets.json`:** `releases` lists English first, then one release per other language:
  `{"language", "name", "releaseDate"?, "prefix"?, "keyArt"?}`.
- **Ledger, `ids/`:**
  - Entries in `cards.json`, `sets.json`, `archetypes.json` and `sealed.json` gain `uuid`.
  - A new `oracles.json` holds `{"oracles": [{"id": <uuid>, "cards": [card ids], "status", "successors"}]}`.
  - The printings move to `ids/printings/<language>.json`, each `{"printings": [...]}` sorted by id.

---

### Task 1: Handoff to AutoMana, part one: skip non-English printings

**Files:**
- Create: `docs/handoff/2026-11-28-automana-skip-non-english-printings.md`

**Interfaces:** none. This is a document for a session in AutoMana's repository.

- [ ] **Step 1: Write the handoff.** It states:
  - **Why:** ygjson 0.5.0 adds printings in `fr`, `de`, `it`, `es` and `pt`, and AutoMana reads `releases/latest`.
  - **The change:** `src/automana/core/services/yugioh_catalog/ygjson_build.py:290` raises on a printing whose
    `language` isn't `en`. It must skip such a printing instead, and count the skipped printings in the build's log.
  - **The fields 0.4.0 adds,** which the importer may ignore: `uuid` on every record, `oracleId` on cards and
    printings, `text` on cards, and set `releases` in other languages. The importer already writes one set
    translation per release language, so the new releases land as set translations.
  - **The test to add:** an `AllPrintings` holding one `fr` printing builds without error and writes no printing row
    for it.
  - **What "done" means:** the change is deployed, and the owner tells the ygjson session so.

- [ ] **Step 2: Commit.**

```bash
git add docs/handoff/2026-11-28-automana-skip-non-english-printings.md
git commit -m "Hand AutoMana the change that skips non-English printings"
```

- [ ] **Step 3: Ask the owner whether to file it as an issue in AutoMana's repository.** Filing it is outward-facing,
  so file it only on a yes, and give the owner the link.

---

### Task 2: Split the printings ledger by language

**Files:**
- Modify: `tools/ids.py` (`load_ledger`, `save_ledger`, `ledger_at`)
- Modify: `.github/workflows/refresh.yml`, if it names `ids/printings.json` (it adds `ids` as a directory, so check)
- Test: `tests/test_ids.py`

**Interfaces:**
- Produces: `ids.printing_files(entries: Mapping[str, dict]) -> dict[str, list[dict]]`. This is
  `{language: entries sorted by id}`, and a printing's language is the second `:` field of its id.
- `load_ledger` and `ledger_at` read `ids/printings/*.json` and also a legacy `ids/printings.json`.
  `save_ledger` writes the split layout and deletes a legacy `ids/printings.json`.

- [ ] **Step 1: Write the failing tests.**
  - `test_save_ledger_splits_printings_by_language`: a ledger with printings `u:en:first` and `u:fr:first` saves
    `ids/printings/en.json` and `ids/printings/fr.json` and no `ids/printings.json`. `load_ledger` gives the same
    ledger back.
  - `test_load_ledger_reads_the_legacy_printings_file`: a tmp dir with only `ids/printings.json` loads its entries.
  - `test_ledger_at_reads_both_layouts`: build a temporary git repo. Commit `ids/printings.json`, tag it `old`, then
    save the split layout, commit it and tag it `new`. `ledger_at("old")` and `ledger_at("new")` give the same
    printings.
  - `test_a_printing_in_both_layouts_is_refused`: the same id in the legacy file and in `ids/printings/en.json`
    raises `ValueError`, as `_by_id` does.

- [ ] **Step 2: Run them.** `uv run pytest -q tests/test_ids.py -k "printings or layouts"`. Expected: they FAIL.

- [ ] **Step 3: Implement `printing_files`, and the split in `load_ledger`, `save_ledger` and `ledger_at`.**
  `ledger_at` lists `ids/` recursively (`git ls-tree -r --name-only`) and shows each `ids/printings/*.json`.

- [ ] **Step 4: Run them.** Expected: PASS. Then run `uv run pytest -q`. Expected: all pass.

- [ ] **Step 5: Migrate the committed ledger.** Run `uv run python tools/ids.py`, then
  `uv run python tools/ids.py --check-against origin/main`. Expected: exit 0. `ids/printings/en.json` exists and
  `ids/printings.json` is gone.

- [ ] **Step 6: Commit.** Stage `tools/ids.py`, `tests/test_ids.py` and `ids/`, with the message "Split the printings
  ledger by language".

---

### Task 3: A UUID on every record, and oracles

**Files:**
- Modify: `tools/ids.py` (`KINDS`, `run`, `check`, `diff_errors`)
- Modify: `tools/reconcile.py` (new `reconcile_oracles`, and `stamp_uuids`)
- Modify: `schema/ids.schema.json` (`uuid` on the card, set, archetype and sealed entries; a new `oracles` kind)
- Test: `tests/test_reconcile.py`, `tests/test_ids.py`

**Interfaces:**
- Produces:
  - `reconcile.stamp_uuids(kind: str, entries: dict[str, dict]) -> dict[str, dict]`. Every entry without a `uuid`
    gets `str(uuid5(YGJSON_NAMESPACE, f"{kind}:{id}"))`, and an existing `uuid` is never changed. `kind` is
    `card`, `set`, `archetype` or `sealed`.
  - `reconcile.reconcile_oracles(entries: dict[str, dict], card_entries: Mapping[str, dict]) -> dict[str, dict]`.
    It is keyed by oracle UUID, with entries `{"id", "cards", "status", "successors"}`.
- `ids.KINDS` gains `"oracles"`. `run` reconciles oracles after cards.

- [ ] **Step 1: Write the failing tests.**
  - `test_stamp_uuids_mints_from_kind_and_id`: `stamp_uuids("card", {"89631139": {...}})["89631139"]["uuid"]` equals
    `str(uuid.uuid5(ids.YGJSON_NAMESPACE, "card:89631139"))`.
  - `test_stamp_uuids_keeps_an_existing_uuid`: an entry with `uuid` `"x"` keeps `"x"`.
  - `test_a_new_card_gets_its_own_oracle`: given no oracles and a live card `1`, the result holds one live oracle
    `uuid5(NS, "oracle:1")` with `cards == ["1"]`.
  - `test_a_successor_card_joins_its_predecessors_oracle`: card `101403001` is retired with successor `82951145`, and
    its oracle `O` lists `["101403001"]`. Then `O`'s cards are `["101403001", "82951145"]`, `O` stays live, and no
    other oracle is minted.
  - `test_an_oracle_whose_cards_are_all_retired_without_successor_is_retired`: it gets status `retired` and empty
    `successors`.
  - `test_check_refuses_a_live_card_in_no_oracle_or_in_two`.
  - `test_check_refuses_two_records_sharing_a_uuid`: two cards with the same `uuid`.
  - `test_diff_errors_refuses_a_changed_uuid_and_an_oracle_losing_a_card`.

- [ ] **Step 2: Run them.** `uv run pytest -q tests/test_reconcile.py tests/test_ids.py`. Expected: the new tests
  FAIL.

- [ ] **Step 3: Implement.** Wire both into `ids.run`. Extend `check` and `diff_errors`: a `uuid` is never changed
  or dropped, and an oracle's `cards` only grows. Update `schema/ids.schema.json`.

- [ ] **Step 4: Run them.** Expected: PASS. Then run `uv run pytest -q`. Expected: all pass.

- [ ] **Step 5: Stamp the committed ledger.** Run `uv run python tools/ids.py`, then
  `uv run python tools/ids.py --check-against origin/main`. Expected: exit 0. `ids/oracles.json` holds one live oracle
  per live card. Today that is 14,708 cards, and the count should match the card count.

- [ ] **Step 6: Commit.** Stage `tools/`, `schema/ids.schema.json`, `tests/` and `ids/`, with the message "Give every
  record a UUID, and every card an oracle".

---

### Task 4: UUIDs and oracle ids in the release files

**Files:**
- Modify: `tools/ygjson.py` (`flatten`)
- Modify: `tools/build.py` (`IDS_VERSION = 2`)
- Modify: `tools/package.py` (a `uuid` column on `sets`, `cards`, `printings`, `archetypes` and `products`; an
  `oracle_id` column on `cards` and `printings`; an `oracles` table `(id, card)`)
- Modify: the JSON schemas the release files are checked against, if `flatten`'s output is validated
- Modify: `README.md`, the "Permanent ids" section
- Test: `tests/test_ygjson.py`, `tests/test_build.py`, `tests/test_package.py`

**Interfaces:**
- Consumes: the ledger kinds from Task 3.
- Produces, with a ledger:
  - `flatten` gives every set, card, archetype and product its ledger `uuid`.
  - Every card and printing gets `oracleId`, the oracle whose `cards` holds the card.
  - Every printing gets `uuid = uuid5(YGJSON_NAMESPACE, "printing:" + <printing id>)`.
  - Without a ledger, nothing changes.

- [ ] **Step 1: Write the failing tests.**
  - `test_flatten_puts_uuids_and_oracle_ids_on_every_record`: on a one-set, one-card fixture with a ledger, the card's
    `uuid` and `oracleId` are the ledger's, the printing's `uuid` is the formula's, and the set's `uuid` is the ledger's.
  - `test_build_meta_ids_version_is_2`.
  - `test_package_writes_uuid_and_oracle_columns`.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement,** and update the README's "Permanent ids" section.
  - **How to find a record:** every record has a `uuid`, and `Ids.json` lists each UUID next to its readable id.
  - **What an oracle is:** `oracleId` groups a card and its reprints. Today one oracle holds one card.
  - **The version:** `idsVersion` is `2`.

- [ ] **Step 4: Run.** `uv run pytest -q`. Expected: all pass. Then run
  `uv run python tools/build.py --version 0.0.0-dev`. Expected: it writes `dist/` and `AllPrintings.json` entries carry
  `uuid`.

- [ ] **Step 5: Commit.** "Put the UUIDs and oracle ids in the release files"

---

### Task 5: Card text

**Files:**
- Modify: `tools/import_ygoprodeck.py` (`card_entry`)
- Modify: `tools/import_ygojson.py` (`apply_card`)
- Modify: `schema/cards.schema.json` (`text`)
- Modify: `tools/package.py` (a `card_texts (card, language, effect, pendulum_effect)` table)
- Modify: `NOTICE`, and the README's cards section
- Test: `tests/test_import_ygoprodeck.py`, `tests/test_import_ygojson.py`, `tests/test_package.py`

**Interfaces:**
- Produces: the card `text` shape (see *Data shapes*).
  - `card_entry` writes `text.en`. A Pendulum frame (`frameType` ending in `_pendulum`) gets `effect` from
    `monster_desc` and `pendulumEffect` from `pend_desc`. Any other card gets `effect` from `desc`.
  - `apply_card` writes `text.<lang>` for every language but `en`, from YGOJSON's `effect`/`pendulumEffect`, skipping
    `official: false` and empty strings. YGOJSON's language keys pass through `languages()`.

- [ ] **Step 1: Write the failing tests.**
  - `test_card_entry_takes_english_text_from_desc`.
  - `test_card_entry_splits_a_pendulum_monsters_text`: given `monster_desc` and `pend_desc`, both land in `text.en`.
  - `test_card_entry_writes_no_text_when_desc_is_empty`.
  - `test_apply_card_writes_official_text_per_language`: YGOJSON `fr` `effect` lands in `card["text"]["fr"]["effect"]`.
  - `test_apply_card_never_writes_unofficial_or_empty_text`: an `en` text with `official: false`, and a `de` text
    whose `effect` is `""`, write nothing.
  - `test_apply_card_never_overwrites_english_text`: YGOJSON's `en` text is ignored.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.** In the schema, `text` maps the ten languages to objects with `effect`, `pendulumEffect`
  and `source` (`yugipedia`), and needs at least one of the first two.
  - `NOTICE` loses "No effect text". It says card text is Konami's, reproduced as Konami published it, gathered by
    YGOPRODeck (English), YGOJSON and Yugipedia (the other languages).

- [ ] **Step 4: Run.** `uv run pytest -q`. Expected: all pass.

- [ ] **Step 5: Commit.** "Ship card text, English from YGOPRODeck and the rest from YGOJSON"

---

### Task 6: Set releases in every language YGOJSON gives

**Files:**
- Modify: `tools/import_ygojson.py` (`apply_set`)
- Modify: `schema/sets.schema.json` (`releases[].language` takes the six languages; `prefix` is optional)
- Modify: `tools/ygjson.py` (`_check_sets`)
- Test: `tests/test_import_ygojson.py`, `tests/test_ygjson.py`

**Interfaces:**
- Produces: the set `releases` shape (see *Data shapes*). `apply_set` replaces every non-English release on each run
  with one per YGOJSON locale `fr`, `de`, `it`, `sp`→`es` and `pt` of the matched set. Each release takes:
  - `name`: YGOJSON's `name[<lang>]`, else the English name.
  - `releaseDate`, `prefix`, and `keyArt` (the locale's `image`, with the Yugipedia page as source).
- English stays `releases[0]` and is never touched by this step.

- [ ] **Step 1: Write the failing tests.**
  - `test_apply_set_adds_a_release_per_western_locale`: a YGOJSON set with `fr` (`prefix` `LOB-FR`, date `2023-04-20`)
    gives `releases[1] == {"language": "fr", "name": …, "releaseDate": "2023-04-20", "prefix": "LOB-FR", …}`.
  - `test_apply_set_maps_sp_to_es`.
  - `test_apply_set_keeps_english_first_and_untouched`.
  - `test_apply_set_drops_a_language_ygojson_no_longer_gives`.
  - `test_validate_refuses_a_set_whose_first_release_is_not_english`, and two releases in one language.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.** Check whether `import_ygoprodeck.build_sets` keeps existing releases. If it rebuilds
  `releases`, it must keep the non-English ones from the set on disk, as `merge_card` keeps names.

- [ ] **Step 4: Run.** `uv run pytest -q`. Expected: all pass.

- [ ] **Step 5: Commit.** "Give each set a release in every Western language YGOJSON lists"

---

### Task 7: Release Group A (0.4.0)

**Files:**
- Modify: `pyproject.toml` and `uv.lock` (version `0.4.0`, through `uv version 0.4.0`)
- Modify: `README.md` (stats, the files table, a "Migrating from 0.3.0" note: the new fields, nothing removed)

- [ ] **Step 1: Run the full pipeline offline,** then the checks:
  - `uv run python tools/pipeline.py --offline`
  - `uv run python tools/validate.py`
  - `uv run python tools/ids.py --check-against origin/main`

  Expected: every one exits 0.
- [ ] **Step 2: Check Review Focus 1.** Download v0.3.0's `Ids.json` with `gh release download v0.3.0 -p Ids.json`. A
  short script checks that every id live in it is live in `ids/`, with the same key. Expected: 0 missing.
- [ ] **Step 3: Update the README and its numbers.** Run `uv version 0.4.0`, then
  `uv run python tools/stats.py --write`, then `uv run python tools/stats.py`. Expected: all numbers match.
- [ ] **Step 4: Run every check.** `uv run ruff check && uv run mypy && uv run pytest -q`. Then build with
  `uv run python tools/build.py --version 0.4.0`. Expected: the build succeeds, and `Ids.json` is under 50 MB per
  committed file. The release asset may be larger.
- [ ] **Step 5: Commit, push, open the pull request and watch CI.** Ask the owner before merging. Once it's merged,
  the next refresh that finds a change releases 0.4.0. The owner may also run `release.yml` by hand.

---

### Task 8: Non-English printings from YGOJSON

**Files:**
- Modify: `tools/import_ygojson.py` (`place_english`, which absorbs `match_scans`' placement; a new
  `match_languages`; `main`)
- Modify: `tools/ygjson.py` (`flatten`, `_check_cards`)
- Modify: `tools/reconcile.py` (`printings_of`)
- Modify: `schema/cards.schema.json` (print `languages`; `source` adds `ygojson` and `yugipedia`)
- Create: `review/languages.json`, written by the importer
- Test: `tests/test_import_ygojson.py`, `tests/test_ygjson.py`, `tests/test_reconcile.py`

**Interfaces:**
- Produces:
  - `import_ygojson.place_english(found, card_found, cards) -> dict[str, list[dict]]`. This is
    `{YGOJSON printing id: [our prints it reaches]}`, from the English locales, with `match_scans`' rules.
    `match_scans` now uses it, and its output is unchanged. Two fixes widen it:
    - **No prefix:** a locale without `prefix` makes the suffix the whole number.
    - **Colour rarities:** a colour rarity (`ultra-blue`) reaches the print whose `variant` is that colour (`blue`)
      at that number, whatever its `source`.
  - `import_ygojson.match_languages(found, placed, card_found, cards) -> tuple[dict[str, dict], list[dict], list[dict]]`.
    It returns `({print id: {lang: language entry}}, new prints, review rows)`.
- Consumes: the print `languages` shape and the print-with-no-English rule (*Data shapes*).
- `reconcile.printings_of` emits `(key, lang, edition)` for each language of each print, and `en` only for a print
  whose `source` isn't `ygojson` or `yugipedia`.
- `flatten` emits a non-English printing like an English one, with these differences:
  - Its `number` and `region` come from the language entry, through `ygjson.region_of`, and so do its editions and its
    `scan`.
  - It has no `tcgplayer`, no `tcgplayerPrice` and no `identifiers.tcgplayerProductIds`.

**Rules,** from the spec:

- A YGOJSON printing in locale `fr`, `de`, `it`, `sp` or `pt` whose id reaches exactly one print becomes that print's
  language entry. Its number is the locale's `prefix` plus its `suffix`, its editions are those of its `contents`
  entry, and its `scans` are that locale's `cardImages` for the id, by edition.
- When the id reaches several prints, the printing's region picks one:
  - A two-letter region (`FR`, `DE`, `IT`, `SP`, `PT`) goes to the print whose region is `EN`.
  - A one-letter region (`F`, `G`, `I`, `S`, `P`, `C`), or a prefix of letters only, goes to the print whose region is
    `E`, else to the one print with no region.
  - Anything else goes to review.
- An id that reaches no print and that no English locale of the set lists becomes a new print (`source: ygojson`),
  given the card is matched and the rarity maps.
- Anything else goes to review with a reason: `no-print`, `card-unmatched`, `ambiguous`, `rarity-unknown` or
  `no-english-locale`.

- [ ] **Step 1: Write the failing tests.**
  - `test_place_english_reads_a_locale_without_prefix_as_the_whole_number`.
  - `test_place_english_places_a_colour_rarity_on_its_colour_variant`.
  - `test_match_scans_is_unchanged_by_place_english`: the current fixtures' scans are identical.
  - `test_a_twin_becomes_the_prints_language_entry`: number `LOB-FR001`, editions `["unlimited"]`, `ygojsonId`.
  - `test_a_two_letter_region_goes_to_the_en_print`.
  - `test_a_one_letter_region_goes_to_the_e_print_else_the_unregioned_one`.
  - `test_an_id_reaching_several_prints_with_no_rule_goes_to_review`.
  - `test_a_printing_only_one_language_has_becomes_its_own_print`: key `set:card:LOB-PT001:super_rare`, source
    `ygojson`, and no English printing.
  - `test_a_colour_rarity_with_no_colour_variant_print_goes_to_review`.
  - `test_printings_of_emits_each_language_and_no_english_for_a_ygojson_print`.
  - `test_flatten_gives_a_french_printing_no_tcgplayer_data_and_its_own_number`.
  - `test_validate_refuses_an_unknown_language_or_an_empty_number`.

- [ ] **Step 2: Run them.** Expected: FAIL. The current tests still pass.

- [ ] **Step 3: Implement.** `main` writes the languages afresh on every run, as it writes scans. That means it first
  drops every print's `languages`, every print with `source: ygojson`, and the `languages` entries whose source is
  `ygojson`. It keeps the entries whose source is `yugipedia`, which Task 9 owns. `review/languages.json` lists the
  review rows, and `decisions.review_counts` counts them.

- [ ] **Step 4: Run.** `uv run pytest -q`. Expected: all pass.

- [ ] **Step 5: Run the importer on the real cache.** Run
  `uv run python tools/pipeline.py --offline --from import_ygojson`, then `uv run python tools/validate.py`.
  - Expected: 160,000 or more language entries, and a review count of about 3,800 or fewer. Record the real numbers in
    the ledger.
  - No committed file passes 50 MB: `find ids data -size +50M` prints nothing.

- [ ] **Step 6: Commit.** "Add the printings YGOJSON lists in French, German, Italian, Spanish and Portuguese"

---

### Task 9: Newer sets' printings and releases, from Yugipedia's set card lists

**Files:**
- Modify: `tools/yugipedia.py` (a new `pages_by_title`, batched 50 titles per request, cached as `title_path`
  caches)
- Create: `tools/import_languages.py`, the new pipeline stage
- Modify: `tools/pipeline.py` (the stage `import_languages`, after `import_yugipedia`)
- Test: `tests/test_yugipedia.py`, `tests/test_import_languages.py`,
  `tests/fixtures/yugipedia/set-card-list-bpro-fr.json`

**Interfaces:**
- Produces:
  - `yugipedia.pages_by_title(titles: Iterable[str], cache: Path = DEFAULT_CACHE, refresh: Container[str] = ()) -> dict[str, dict | None]`.
    A title in `refresh` is fetched again. A missing page is cached as missing.
  - `import_languages.set_list_rows(wikitext: str) -> list[tuple[str, str, list[str]]]`, giving
    `(number, English name, rarities)`. A row without rarities takes the template's `rarities=` default.
    `// comments` and blank lines are skipped.
  - `import_languages.place_rows(set_id, lang, rows, cards, prints) -> tuple[dict[str, dict], list[dict]]`. Its first
    part is the language entries to merge (`source: yugipedia`), and its second the review rows. It uses the same
    region rules as Task 8.
- Consumes: the *Data shapes*; `rarities.canonical` for Yugipedia's rarity names.

**Rules:**

- **Which pages:** every set with `identifiers.yugipediaId` gets, for each of `fr`, `de`, `it`, `es` and `pt` it has
  no `ygojson` language entry in, the page `Set Card Lists:<the set's page title> (TCG-<FR|DE|IT|SP|PT>)`.
- **Row to print:**
  - A row's card is the card whose English name or alias equals the row's name, compared by
    `ygjson.normalise`.
  - Its print is our print in that set with that card, the same digits after the region (`BPRO-FR001` ↔
    `BPRO-EN001`) and that rarity.
  - A row with several rarities is one printing per rarity.
- **Editions:** a printing has the set's editions.
- **Release:** a set given a printing in a language gets a release in it, with these fields:
  - `name`: the set page's `<lang>_name` (`es_name` for `es`), else the English name.
  - `releaseDate`: `<lang>_release_date`, else `eu_release_date` for `fr`, `de`, `it` and `es`.
  - `prefix`: the region part of the rows' numbers.
- **Freshness:** a page of a set whose English release is less than 90 days old is fetched again on every run. Others
  come from the cache.

- [ ] **Step 1: Write the failing tests.** Use the fixture: the first 20 rows of `Set Card Lists:Burst Protocol
  (TCG-FR)` as fetched on 2026-11-28, in the shape `yugipedia._write` caches.
  - `test_set_list_rows_reads_number_name_and_rarities_with_the_default`: the row `BPRO-FR002; Hollowrokket Dragon` is
    `("BPRO-FR002", "Hollowrokket Dragon", ["Common"])`. The row `BPRO-FR001; Rokket Loader; Ultra Rare, Starlight Rare`
    has two rarities.
  - `test_place_rows_puts_a_row_on_the_english_print_of_its_number_and_rarity`.
  - `test_place_rows_sends_an_unknown_card_name_to_review`.
  - `test_a_missing_set_card_list_page_gives_no_printing_and_no_error`.
  - `test_pages_by_title_batches_and_caches_missing_pages`, with `_query` monkeypatched.
  - `test_a_recent_sets_page_is_fetched_again_and_an_old_ones_is_not`.
  - `test_a_set_with_a_yugipedia_printing_gets_a_release_in_that_language`.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.** The stage writes its language entries afresh on every run: it drops the
  `source: yugipedia` entries and prints, then adds them again from the cached pages. It appends its rows to
  `review/languages.json` under `yugipedia`, and `sources.record("yugipedia", …)` as `import_yugipedia` does.

- [ ] **Step 4: Run.** `uv run pytest -q`. Expected: all pass. Then run
  `uv run python tools/pipeline.py --from import_languages` online, once: it fetches the pages. Expected: Burst
  Protocol has French printings.

- [ ] **Step 5: Commit.** "Read newer sets' printings in each language from Yugipedia's set card lists"

---

### Task 10: Text and names YGOJSON lacks, from Yugipedia's card pages

**Files:**
- Modify: `tools/import_languages.py`
- Test: `tests/test_import_languages.py`, `tests/fixtures/yugipedia/card-ash-blossom.json`

**Interfaces:**
- Produces:
  - `import_languages.card_texts(wikitext: str) -> dict[str, dict]`, giving `{lang: {"effect"?, "pendulumEffect"?}}`
    from `<lang>_text` and `<lang>_pendulum_effect`. The codes map `sc`→`zh-CN` and `tc`→`zh-TW`. `translated_text` is
    never read, and English (`text`) is never read.
  - `import_languages.card_names(wikitext: str) -> dict[str, str]`, from `<lang>_name` with the same codes.
    `ko_rr_name`, `romaji_name` and `sc_pinyin_name` are not names.

**Rules:**

- **Which cards:** a card gets its Yugipedia page fetched when it has no YGOJSON card, or when it lacks text in one of
  `fr`, `de`, `it`, `es` and `pt`. That is about 2,800 cards today.
- **Finding the page:** by `identifiers.yugipediaIds[0]` through `pages_by_id`, else by its English name through
  `pages_by_title`.
- **What is written:** only the languages the card lacks, each marked `"source": "yugipedia"`.
- **Freshness:** a card whose `tcgDate` is less than 90 days old is fetched again on every run.

- [ ] **Step 1: Write the failing tests.** Use the fixture: Ash Blossom's page, trimmed to its CardTable fields.
  - `test_card_texts_reads_each_language_and_maps_sc_and_tc`.
  - `test_card_texts_never_reads_translated_text_or_english`.
  - `test_card_names_skips_romanisations`.
  - `test_a_card_with_ygojson_text_keeps_it_and_gains_only_missing_languages`.
  - `test_a_recent_cards_page_is_fetched_again`.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run.** `uv run pytest -q`. Expected: all pass. Then run
  `uv run python tools/pipeline.py --from import_languages`. Expected: the number of cards with no French text drops
  from 483 + 717 (measured 2026-11-28). Record the numbers in the ledger.

- [ ] **Step 5: Commit.** "Fill missing card text and names from Yugipedia's card pages"

---

### Task 11: Release Group B (0.5.0), held for AutoMana

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (`0.5.0`)
- Modify: `README.md` (languages, printings per language, the review counts, "Migrating from 0.4.0")
- Modify: `NOTICE` (Yugipedia's set card lists as a source of printings)

- [ ] **Step 1: Run the checks.** Run `uv run python tools/pipeline.py --offline`, then
  `uv run python tools/validate.py`, then `uv run python tools/ids.py --check-against origin/main`. Expected: exit 0.
- [ ] **Step 2: Check Review Focus 1** again, against v0.3.0's `Ids.json`. Expected: 0 missing.
- [ ] **Step 3: Update the version and numbers.** Run `uv version 0.5.0`, then `uv run python tools/stats.py --write`,
  then `uv run python tools/stats.py`. Expected: they match.
- [ ] **Step 4: Run every check and build.** `uv run ruff check && uv run mypy && uv run pytest -q`, then
  `uv run python tools/build.py --version 0.5.0` and `uv run python tools/package.py`. Expected: success. Record each
  asset's size in the pull request.
- [ ] **Step 5: Commit, push, open the pull request and watch CI.** The pull request body says it waits for AutoMana.
  Do not merge until the owner confirms Task 1's change is deployed.

---

### Task 12: Handoff to AutoMana, part two

**Files:**
- Create: `docs/handoff/2026-11-28-automana-ygjson-languages.md`

- [ ] **Step 1: Write the handoff,** with the spec's four parts: importer, API, the underlying view and the UI. Each
  part has what to change, the files (`ygjson_build.py`, `yugioh_catalog.card_search` in
  `V20261028185220__yugioh_catalogue_views.sql`, `card_catalog.v_printing_lang` in `V20261028003102__yugioh_views.sql`),
  and how to test it.
  - **Importer:** store ygjson's `uuid` as AutoMana's id for sets, cards, prints and printings, and keep the
    ledger's `formerKeys`/`formerIds` to migrate the ids AutoMana stored from 0.3.0.
  - **API:** look up a record by a ygjson UUID.
  - **View:** a `language_code` column, and `rep` English first, as `riftbound_catalog.card_search` does.
    `v_printing_lang` compares `language_id` with `default_language_id()` for Yu-Gi-Oh! printings.
  - **UI:** show a printing's language, and filter the card grid, the search and the card page's print table by
    language.
- [ ] **Step 2: Commit.**
- [ ] **Step 3: Ask the owner whether to file the four parts as AutoMana issues.** File them only on a yes.

---

## After this plan

The Asian sets' design is written once 0.5.0 is out. Its starting facts are in the spec's "Later: the Asian sets".
