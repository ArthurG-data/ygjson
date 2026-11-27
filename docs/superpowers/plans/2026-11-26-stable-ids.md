# Stable ids Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every id ygjson has published resolves forever: prints get permanent UUIDs kept in a committed, append-only
ledger, and sets, archetypes and sealed products keep frozen slugs.

**Architecture:** The importers are not changed in how they find prints: inside `data/`, a print's `id` stays today's
readable key. A new pure module `tools/reconcile.py` decides, after the whole pipeline, which ledger id each current
record carries; `tools/ids.py` loads and saves the ledger in `ids/`, runs reconcile, checks the ledger and seeds it from
git history. `ygjson.flatten` swaps keys for UUIDs when building the release, so readers see UUIDs and `key`, and
`Ids.json` ships the whole ledger.

**Tech Stack:** Python 3.11, standard library (`uuid`, `subprocess` for git), `jsonschema`, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-11-26-stable-ids-design.md`. Read it before any task; rule numbers below are
the spec's.

## Global Constraints

- Work on a new branch `feat/stable-ids` cut from `origin/main` (local `main` and `fix/one-product-per-edition` are
  behind it), in a worktree.
- `YGJSON_NAMESPACE = uuid.UUID("7d674373-b170-5fd8-ab33-29bacad29ffa")` (= `uuid5(NAMESPACE_URL, "https://github.com/ArthurG-data/ygjson")`).
- A print id is `str(uuid5(YGJSON_NAMESPACE, birth_key))`; on collision with any id in the ledger, hash `f"{birth_key}#2"`, `#3`, …
- A printing id is `f"{print_uuid}:{language}:{edition}"`.
- Reconcile reads only `data/`, `sets/`, `ids/` and `mappings/`; no network. Same inputs give byte-identical outputs;
  ties are broken by sorted key, never dict order.
- The ledger only grows: no entry removed, no `id` changed, `formerKeys`/`formerIds`/`names` never shortened.
- Ledger files are written with `ygjson.save_json`, entries sorted by id (slug for archetypes).
- Standard library only; follow the existing tool style (module docstring with usage line, `main()` with argparse).
- Inside `data/` a print's `id` stays the readable key (`ygjson.print_id`). Only release files carry UUIDs.

## Review Focus

1. A print key with an empty number (`mattel-action-figure-promotional-cards-series-3:98585345::normal_parallel_rare`)
   or a joined variant (`…:a-alternate-art`) must parse and round-trip — pinned in Task 2.
2. Reconcile run twice on unchanged data must leave every `ids/` file byte-identical — pinned in Task 8.
3. One orphan, two newcomers, and only one newcomer holds the orphan's product: that one inherits, the other is new
   (not retired, not ambiguous) — pinned in Task 3.
4. A key retired, then reappearing a release later, revives the same id; a new print whose birth key hashes to a live
   id gets the `#2` id — pinned in Tasks 2 and 3.
5. A placeholder card replaced by its passcode: its prints' ids carry over under the passcode key — pinned in Task 4.

---

### Task 1: Branch, ledger files and minting

**Files:**
- Create: `tools/ids.py`, `schema/ids.schema.json`, `tests/test_ids.py`
- Add (copied from `fix/one-product-per-edition`): `docs/superpowers/specs/2026-11-26-stable-ids-design.md`, this plan

**Interfaces:**
- Produces:
  - `ids.IDS: Path` (= `ygjson.ROOT / "ids"`), `ids.KINDS = ("prints", "printings", "cards", "sets", "archetypes", "sealed")`
  - `ids.YGJSON_NAMESPACE: uuid.UUID`
  - `ids.mint(birth_key: str, taken: Container[str]) -> str`
  - `ids.load_ledger(path: Path = IDS) -> dict[str, dict[str, dict]]` — `{kind: {id: entry}}`; missing files load empty.
  - `ids.save_ledger(ledger: dict[str, dict[str, dict]], path: Path = IDS) -> None` — one file per kind, `{"<kind>": [entries sorted by id]}`.
  - Entry shapes (spec, "The ledger"): print `{id, key, formerKeys, status, successors, products}`; printing
    `{id, key, formerIds, status, successors}`; card `{id, name, konamiId?, status, successors}`; set
    `{id, names, status, successors}`; archetype `{id, names, status, successors}`; sealed
    `{id, tcgplayerProductId, status, successors}`. `status` ∈ `live`/`retired`.

- [ ] **Step 1: Create the worktree** — `git worktree add .worktrees/stable-ids -b feat/stable-ids origin/main`;
  copy the spec and this plan in; `uv sync --group dev`; `uv run pytest -q` → all pass.
- [ ] **Step 2: Write failing tests** in `tests/test_ids.py`:

```python
def test_mint_is_uuid5_of_the_birth_key():
    assert ids.mint("lob:89631139:LOB-001:ultra_rare", set()) == str(uuid.uuid5(ids.YGJSON_NAMESPACE, "lob:89631139:LOB-001:ultra_rare"))

def test_mint_skips_a_taken_id():
    first = ids.mint("k", set())
    assert ids.mint("k", {first}) == str(uuid.uuid5(ids.YGJSON_NAMESPACE, "k#2"))

def test_ledger_round_trips_sorted(tmp_path):
    ledger = {k: {} for k in ids.KINDS}
    ledger["prints"] = {"b": {"id": "b", "key": "x", "formerKeys": [], "status": "live", "successors": [], "products": []},
                        "a": {"id": "a", "key": "y", "formerKeys": [], "status": "live", "successors": [], "products": []}}
    ids.save_ledger(ledger, tmp_path)
    assert [e["id"] for e in json.loads((tmp_path / "prints.json").read_text())["prints"]] == ["a", "b"]
    assert ids.load_ledger(tmp_path) == ledger

def test_missing_ledger_loads_empty(tmp_path):
    assert ids.load_ledger(tmp_path) == {k: {} for k in ids.KINDS}

def test_ledger_entries_match_the_schema(tmp_path): ...  # a valid entry of each kind passes; a print entry with status "gone" fails
```

- [ ] **Step 3: Run** `uv run pytest -q tests/test_ids.py` → FAIL (`No module named 'ids'`).
- [ ] **Step 4: Implement** `tools/ids.py` (module docstring, the constants and three functions) and
  `schema/ids.schema.json` (draft 2020-12, one `$defs` entry per kind, `additionalProperties: false`, `status` enum,
  print `id` format `uuid`, printing id pattern `^<uuid>:[a-z]{2}(-[A-Za-z]+)?:(first|unlimited|limited)$`).
- [ ] **Step 5: Run** the tests → PASS. `uv run pytest -q` → all pass.
- [ ] **Step 6: Commit** — `git add docs tools/ids.py schema/ids.schema.json tests/test_ids.py && git commit -m "Ledger files and minting for permanent ids"`

### Task 2: Print keys and facts

**Files:**
- Create: `tools/reconcile.py`, `tests/test_reconcile.py`

**Interfaces:**
- Consumes: `ygjson.print_id`
- Produces:
  - `@dataclass(frozen=True) class PrintFacts: key: str; set: str; card: str; number: str; rarity: str; variant: str | None; products: frozenset[int]`
  - `reconcile.parse_key(key: str, products: Iterable[int] = ()) -> PrintFacts` — splits on `:` into at most 5 parts
    (`set:card:number:rarity[:variant]`); `number` may be `""`.
  - `reconcile.current_prints(files: dict[str, dict]) -> list[PrintFacts]` — from `data/cards` bodies, products from
    `identifiers.tcgplayerProductIds`, sorted by key.
  - `reconcile.rekey_card(key: str, card_successor: Mapping[str, str]) -> str` — replaces the card part when it is a
    retired card with one successor.

- [ ] **Step 1: Failing tests:**

```python
def test_parse_key_with_empty_number():
    f = reconcile.parse_key("mattel-action-figure-promotional-cards-series-3:98585345::normal_parallel_rare")
    assert (f.set, f.card, f.number, f.rarity, f.variant) == ("mattel-action-figure-promotional-cards-series-3", "98585345", "", "normal_parallel_rare", None)

def test_parse_key_round_trips_a_joined_variant():
    key = "quarter-century-bonanza:24094653:RA03-EN051:collectors_rare:a-alternate-art"
    f = reconcile.parse_key(key)
    assert f.variant == "a-alternate-art"
    assert ygjson.print_id(f.set, f.card, f.number, f.rarity, f.variant) == key

def test_rekey_card_swaps_a_placeholder_for_its_passcode():
    assert reconcile.rekey_card("s:101403001:X-EN001:rare", {"101403001": "82951145"}) == "s:82951145:X-EN001:rare"
    assert reconcile.rekey_card("s:5:X-EN001:rare", {}) == "s:5:X-EN001:rare"

def test_current_prints_reads_products_and_sorts(): ...  # two prints in a body, out of order → sorted, products as frozenset
```

- [ ] **Step 2: Run** `uv run pytest -q tests/test_reconcile.py` → FAIL.
- [ ] **Step 3: Implement** the dataclass and three functions in `tools/reconcile.py` (pure: no file IO).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "Parse print keys into the facts reconcile matches on"`

### Task 3: Reconcile prints (rules 1–6, retirement)

**Files:**
- Modify: `tools/reconcile.py`, `tests/test_reconcile.py`

**Interfaces:**
- Consumes: Task 1 `ids.mint`, Task 2 `PrintFacts`, `parse_key`, `rekey_card`
- Produces:
  - `reconcile.reconcile_prints(entries: dict[str, dict], current: list[PrintFacts], card_successor: Mapping[str, str] = {}, hand: Mapping[str, str] = {}) -> tuple[dict[str, dict], dict[str, str], list[dict]]`
    returning (new print entries, `{current key: id}`, review rows `{"id", "key", "reason", "successors"}`).
  - `hand` is `{newcomer key: retired id}` (rule 5, from Task 7).

**Algorithm (not determined by the signature):**
1. Orphans = live entries whose key, after `rekey_card`, no current print has. Newcomers = current prints whose key no
   live entry has. A live entry whose key was rewritten by `rekey_card` and now matches a current print is that print
   (old key appended to `formerKeys`).
2. Run the rules as **passes**, each over the newcomers and orphans still unmatched, newcomers in sorted key order; a
   pass's "exactly one" counts are taken over what is unmatched at the start of that pass:
   rule 1 (key is the `key` or in `formerKeys` of a **retired** entry → revive), rule 2 (product held by exactly one
   orphan and by no other newcomer), rule 3 (exactly one orphan and one newcomer at `(set, card, number)`), rule 4
   (exactly one orphan and one newcomer at `(card, number, rarity, variant)`, sets differ), rule 5 (`hand`), rule 6
   (`mint(key, every id in entries)`).
3. A matched entry: `formerKeys += [old key]` if the key changed, `key = new key`, `status = "live"`, `successors = []`.
4. Every current print's entry gets `products = sorted(products)`.
5. Each orphan left: `status = "retired"`, `successors` = ids of current prints at `(set, card, number)`, else
   `(card, number)`, else `(set, card, rarity, variant)`, sorted; one review row per retirement.

- [ ] **Step 1: Failing tests** (fixtures built with `parse_key` and a helper `live(key, id, products=())`):

```python
def test_first_run_mints_every_print():  # empty ledger, two prints → two live entries, ids == mint(key)
def test_unchanged_print_keeps_its_id_and_entry():
def test_rarity_correction_keeps_the_id():  # L5DD-ENA12:unknown → :common, id same, formerKeys == [old key]
def test_variant_split_follows_the_product():
    # orphan "...:RA04-EN109:platinum_secret_rare" held 100; newcomers ":4th-art" holds 100, ":7th-art" holds 101
    # → ":4th-art" has the orphan's id; ":7th-art" is minted; no retirement
def test_split_without_evidence_retires_with_both_successors():
    # CH02-EN003:unknown → :secret_rare and :starlight_rare, no products → old id retired, successors == both new ids, one review row
def test_letter_becoming_the_base_print_keeps_the_id():  # ":collectors_rare:a" → ":collectors_rare" while ":b" stays
def test_same_card_in_another_set_keeps_the_id():  # wcs-2025-limited-pack:33396948:25LP-EN000:secret_rare → limited-pack-world-championship-2025:…
def test_number_change_retires_with_the_new_print_as_successor():  # s:1:X-EN001:rare → s:1:X-EN002:rare
def test_flip_back_revives_the_retired_id():  # run A→B retires nothing (rule 3) ... use: retired entry with key K; K reappears → same id, live
def test_former_key_of_a_live_print_does_not_revive():  # live entry key K2 formerKeys [K1]; newcomer K1 → minted with "#2", not the live id
def test_hand_decision_revives_a_retired_id():
def test_placeholder_card_prints_follow_the_passcode():  # entry key "s:101403001:X:rare", current "s:82951145:X:rare", card_successor → same id, formerKeys has the placeholder key
def test_reconcile_is_deterministic():  # shuffle `current` → identical output
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `reconcile_prints` per the algorithm.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "Carry print ids across a rebuild, and retire what no rule settles"`

### Task 4: Cards — retire placeholders, drop retired cards from data

**Files:**
- Modify: `tools/reconcile.py`, `tools/import_ygoprodeck.py` (`build_cards`, the "A card another tool added" block),
  `tests/test_reconcile.py`, `tests/test_import_ygoprodeck.py`

**Interfaces:**
- Produces: `reconcile.reconcile_cards(entries: dict[str, dict], cards: list[dict]) -> tuple[dict[str, dict], dict[str, str], list[dict]]`
  returning (new card entries, `{retired card id: successor id}` for retired ids with exactly one successor, review rows).
  A live card's entry stores `name` and `konamiId` (from `identifiers.konamiId`, omitted when absent). A card no longer
  in `cards`: retired; successor = the one current card whose `name` equals the entry's `name`, else the one with the
  same `konamiId`; zero or several → no successor, review row.

- [ ] **Step 1: Failing tests:**

```python
def test_placeholder_card_retires_to_its_passcode():
    entries = {"101403001": {"id": "101403001", "name": "Helpoemer, Chanter of the Sun God", "status": "live", "successors": []}}
    new, succ, review = reconcile.reconcile_cards(entries, [{"id": "82951145", "name": "Helpoemer, Chanter of the Sun God", "identifiers": {}}])
    assert new["101403001"]["status"] == "retired" and new["101403001"]["successors"] == ["82951145"]
    assert succ == {"101403001": "82951145"} and review == []

def test_retired_card_with_two_namesakes_has_no_successor_and_goes_to_review(): ...
def test_card_entry_records_name_and_konami_id(): ...

# tests/test_import_ygoprodeck.py
def test_a_card_ygoprodeck_dropped_leaves_the_data():  # existing holds card 101403001 with no prints; card_list lacks it → not in bodies
def test_a_dropped_card_holding_a_tcgplayer_print_stays():  # existing card with a print source "tcgplayer" → kept
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `reconcile_cards`; in `build_cards`, keep a card YGOPRODeck lacks only when one of its
  prints has `source == "tcgplayer"`, and fix the comment to say so.
- [ ] **Step 4: Run** → PASS; `uv run pytest -q` → all pass.
- [ ] **Step 5: Commit** — `git commit -m "Retire card ids YGOPRODeck replaced, and stop keeping dropped cards"`

### Task 5: Printings

**Files:**
- Modify: `tools/reconcile.py`, `tests/test_reconcile.py`

**Interfaces:**
- Consumes: Task 3's `{print key: print id}` and print entries.
- Produces: `reconcile.reconcile_printings(entries: dict[str, dict], printings: list[tuple[str, str, str]], print_ids: Mapping[str, str], print_entries: Mapping[str, dict]) -> dict[str, dict]`
  where `printings` is `(print key, language, edition)` for every printing `flatten` would emit. Live entry:
  `id = f"{print_ids[key]}:{language}:{edition}"`, `key = ygjson.printing_id(print key, language, edition)`; when
  `key` changes, the old key goes to `formerIds`. A previously live printing not emitted now: retired; successors =
  same language and edition on the print's successors (print retired), or the print's remaining live printings
  (edition dropped). A retired printing emitted again: live, same id.
- Also produces: `reconcile.printings_of(sets: list[dict], files: dict[str, dict]) -> list[tuple[str, str, str]]`, the
  same edition rule as `ygjson.flatten` (a print's `editions`, else its set's), language `"en"`.

- [ ] **Step 1: Failing tests:** `test_printing_id_is_print_uuid_language_edition`,
  `test_dropped_edition_retires_with_the_remaining_printings_as_successors`,
  `test_restored_edition_revives_the_printing`, `test_printing_of_a_retired_print_points_at_the_successor_print`,
  `test_printing_key_change_records_the_former_readable_id` (assert `formerIds == ["<old print key>:en:first"]`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "Printing ids follow their print and never disappear"`

### Task 6: Frozen slugs for sets, archetypes and sealed products

**Files:**
- Modify: `tools/ygjson.py` (`dedupe_slugs`), `tools/import_ygoprodeck.py` (`build_sets`, `build_archetypes`, `main`),
  `tools/import_tcgcsv.py` (`_free_id` callers at about lines 214 and 590), `tools/import_sealed.py` (`assign_ids`,
  `main`), `tools/reconcile.py`, matching tests.

**Interfaces:**
- Consumes: Task 1 `ids.load_ledger`.
- Produces:
  - `ygjson.dedupe_slugs(names: Iterable[str], held: Mapping[str, str] | None = None, reserved: Container[str] = frozenset()) -> dict[str, str]`
    — a name in `held` gets its held slug; other names as today, but never a slug in `held.values()` or `reserved`.
  - `ids.held_names(ledger, kind: str) -> dict[str, str]` — `{name: slug}` over every name in every entry's `names`
    (live or retired); `ids.reserved(ledger, kind) -> set[str]` — every slug in the ledger.
  - `import_sealed.assign_ids(records, held: Mapping[int, str] = {}, reserved: Container[str] = frozenset())` — a record
    whose `productId` is in `held` gets that slug.
  - `reconcile.reconcile_slugs(entries: dict[str, dict], current: list[dict], name_field: str, identity: Callable[[dict], set[str]], merges: Mapping[str, str] = {}) -> tuple[dict[str, dict], list[dict]]`
    — for sets (`name_field="name"`, `identity` = `{f"ygojson:{…}", f"yugipedia:{…}", f"konami:{…}" …}` from
    `identifiers`), archetypes (`name`, identity = `{f"ygojson:{identifiers.ygojsonId}"}`). Returns (new entries,
    rename rows). A live slug absent from `current`: if it is a key of `merges` → retired, successor = the merge target;
    else if exactly one new slug shares an identity → a **rename row** `{"from", "to", "name"}` (the old entry gains the
    new name in `names`; the new slug is not added) ; else retired, successors = the one new set with the same `code`
    and release date, if exactly one. New slugs: live entries with `names = [name]`.
  - `reconcile.reconcile_sealed(entries, products: list[dict]) -> dict[str, dict]` — keyed by slug, `tcgplayerProductId`
    from `identifiers.tcgplayerProductIds[0]`; absent slug → retired, no successor.

- [ ] **Step 1: Failing tests:**

```python
def test_dedupe_keeps_held_slugs_when_an_earlier_name_arrives():
    assert ygjson.dedupe_slugs(["Roid", "ROID"], held={"Roid": "roid"}) == {"Roid": "roid", "ROID": "roid-2"}

def test_dedupe_never_reuses_a_reserved_slug():
    assert ygjson.dedupe_slugs(["Foo"], reserved={"foo"}) == {"Foo": "foo-2"}

def test_build_sets_gives_a_ledger_name_its_slug_after_a_rename():  # held {"Old Name": "x", "New Name": "x"}, YGOPRODeck lists "New Name" → set id "x"
def test_rename_is_found_by_a_shared_yugipedia_id():  # reconcile_slugs → one rename row, entry names gain the new name
def test_alias_merge_retires_with_the_target():  # merges {"wcs-2025-limited-pack": "limited-pack-world-championship-2025"}
def test_sealed_slug_follows_the_tcgplayer_product_through_a_rename():  # assign_ids held {42: "old-slug"} → record 42 keeps "old-slug"
def test_minted_tcgplayer_set_avoids_a_retired_slug():  # import_tcgcsv taken set includes ids.reserved(ledger, "sets")
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Each importer `main` loads the ledger once with `ids.load_ledger()` and passes
  `held_names`/`reserved` (sealed: `{entry["tcgplayerProductId"]: slug}`). `merges` comes from
  `mappings/ygoprodeck_set_aliases.json` (`{alias: entry["set"]}`).
- [ ] **Step 4: Run** → PASS; `uv run pytest -q` → all pass.
- [ ] **Step 5: Commit** — `git commit -m "Freeze set, archetype and sealed slugs in the ledger"`

### Task 7: Hand decisions and the review file

**Files:**
- Create: `mappings/ids.json` (`{"_comment": "...", "prints": {}, "successors": {}}`)
- Modify: `tools/ids.py`, `tests/test_ids.py`

**Interfaces:**
- Produces:
  - `ids.load_hand(path: Path = ygjson.ROOT / "mappings" / "ids.json") -> tuple[dict[str, str], dict[str, list[str]]]` —
    (`{newcomer key: retired print id}`, `{retired id: successor ids}`); every entry carries `"why"`, else `ValueError`.
  - `ids.hand_errors(ledger, hand) -> list[str]` — an entry that names a `live` id, or an id not in the ledger.
  - Review file `review/ids.json`: `{"prints": [...], "cards": [...], "renames": [...]}` from the reconcile rows,
    sorted.

- [ ] **Step 1: Failing tests:** `test_hand_entry_without_why_is_refused`,
  `test_hand_may_not_give_a_live_id_to_a_second_print`, `test_hand_successors_override_the_computed_ones`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (successor overrides are applied after `reconcile_prints`).
  **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "Let a person settle what reconcile retires"`

### Task 8: The `ids.py` command, checks, CI

**Files:**
- Modify: `tools/ids.py`, `tools/validate.py`, `tools/build.py`, `.github/workflows/ci.yml`, `tests/test_ids.py`

**Interfaces:**
- Produces:
  - `ids.run(ledger, sets, files, archetypes, sealed, hand, merges) -> tuple[ledger, review: dict, renames: list[dict]]`
    — cards first (Task 4), then prints with `card_successor`, then printings, sets, archetypes, sealed.
  - `ids.check(ledger, sets, files, archetypes, sealed) -> list[str]` — every print key/set/archetype/sealed slug in
    the data has a live entry and the reverse; successors exist in the ledger; no UUID twice; plus `hand_errors`.
  - `ids.diff_errors(before: ledger, after: ledger) -> list[str]` — an entry removed, an `id`/birth changed, a
    `formerKeys`/`formerIds`/`names` list shortened.
  - CLI: `uv run python tools/ids.py` (reconcile, write `ids/` and `review/ids.json`; exit 3 with the rename rows
    printed when any rename was found: "rerun the pipeline"); `--check-against REV` (load the ledger at git `REV` via
    `git show`, print `diff_errors`, exit 1 on any).
- `validate.py` and `build.py` call `ids.check` after `ygjson.validate` and fail on its errors.
- CI: after `uv run pytest -q`, add `uv run python tools/ids.py --check-against origin/${{ github.base_ref || 'main' }}`
  (`actions/checkout` with `fetch-depth: 0`).

- [ ] **Step 1: Failing tests:** `test_run_twice_leaves_the_ledger_byte_identical` (save after each run into two
  tmp dirs, compare bytes), `test_check_reports_a_print_with_no_ledger_entry`,
  `test_diff_errors_reports_a_removed_entry`, `test_diff_errors_reports_a_shortened_former_keys`,
  `test_rename_exits_3`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS; `uv run pytest -q` → all pass.
- [ ] **Step 5: Commit** — `git commit -m "Reconcile, check and guard the ledger in CI"`

### Task 9: Seed from history and releases

**Files:**
- Create: `tools/seed_ids.py`, `tests/test_seed_ids.py`

**Interfaces:**
- Consumes: `ids.run`, `reconcile.*`, `ids.save_ledger`.
- Produces:
  - `seed_ids.commits(rev: str = "origin/main") -> list[str]` — `git rev-list --first-parent --reverse REV`.
  - `seed_ids.snapshot(commit: str) -> tuple[sets, files, archetypes, sealed]` — via `git show COMMIT:path`; a file
    missing at that commit loads empty.
  - `seed_ids.seed(commits: list[str], releases: dict[str, Path]) -> ledger` — empty ledger; `ids.run` on each
    snapshot in order with an empty hand, ignoring rename exits (record them in the result's review); then, for each
    release `AllPrintings.json` (`{"data": {printing id: record}}`), add every published printing id to the
    `formerIds` of the printing entry whose `key` or `formerIds` equals it, else of the entry that its `print` key's
    print id now owns.
  - CLI: `uv run python tools/seed_ids.py --rev origin/main --release v0.1.0=DIR --release v0.2.0=DIR`, refuses when
    `ids/` already holds entries.

- [ ] **Step 1: Failing tests** on a throwaway git repo built in `tmp_path` with two commits
  (`git init`, write data, commit, change a rarity, commit): `test_seed_carries_the_id_across_a_rarity_fix`,
  `test_seed_records_release_printing_ids_as_former_ids`, `test_seed_refuses_a_non_empty_ledger`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "Seed the ledger from main's history and the published releases"`

### Task 10: Release files use permanent ids

**Files:**
- Modify: `tools/ygjson.py` (`flatten`), `tools/build.py`, `tests/test_build.py`, `tests/test_ygjson.py`, `README.md`

**Interfaces:**
- Changes: `ygjson.flatten(sets, files, archetypes, sealed=None, ledger=None)` — with a ledger, `AllCards[...].prints`
  are print UUIDs; every printing record has `id` (UUID form), `key` (readable), `print` (UUID), `printKey`; sealed
  `contents.cards[].print` are UUIDs. Without a ledger (old callers/tests), output is unchanged.
- `build.build` loads the ledger, adds `"Ids": ledger` as a seventh file `Ids.json`, and `meta.idsVersion = 1`.
  `ci.yml` release step attaches `dist/Ids.json`.

- [ ] **Step 1: Failing tests:** `test_release_printings_are_keyed_by_uuid` (key matches the printing id pattern;
  `key` equals the old readable id), `test_ids_json_ships_the_whole_ledger`, `test_meta_carries_ids_version`,
  `test_sealed_contents_point_at_print_uuids`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: README:** a new "Ids" section replacing the print/printing id bullets — `id` is permanent, `key` is
  readable and may change, how to look up an old id in `Ids.json` (`key`, `formerKeys`, `formerIds`, `successors`),
  the reconcile step in the build order (after `import_sealed.py`), `review/ids.json`, `mappings/ids.json`. Remove
  "A rebuild from the same sources gives the same ids."
- [ ] **Step 6: Commit** — `git commit -m "Ship permanent ids and the ledger in the release"`

### Task 11: Seed the real ledger

**Files:**
- Create: `ids/*.json`, `review/ids.json`

- [ ] **Step 1:** `gh release download v0.1.0 -p AllPrintings.json -D <scratch>/v0.1.0` and the same for `v0.2.0`.
- [ ] **Step 2:** `uv run python tools/seed_ids.py --rev origin/main --release v0.1.0=<scratch>/v0.1.0 --release v0.2.0=<scratch>/v0.2.0`.
- [ ] **Step 3:** Run the pipeline's last step on the current data: `uv run python tools/ids.py` → exit 0.
- [ ] **Step 4: Verify the promise.** A scratch script lists every print key in every first-parent commit of
  `origin/main` and every printing id in both releases, and asserts each is found in the ledger as a `key`,
  `formerKeys` or `formerIds` entry. Expected: 0 missing. Report: how many entries are live, retired with one
  successor, retired with several, retired with none.
- [ ] **Step 5:** `uv run pytest -q`, `uv run python tools/validate.py`, `uv run python tools/build.py --version 0.3.0-dev` → all succeed.
- [ ] **Step 6: Commit** — `git add ids review/ids.json && git commit -m "Seed the id ledger from history"`
