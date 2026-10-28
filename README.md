# ygjson

An open dataset of Yu-Gi-Oh! TCG sets, cards, printings, archetypes, sealed products and Forbidden & Limited
history, in English. Every print carries the TCGplayer product ids that sell it. YGOPRODeck leads the data: it
decides which sets, cards and prints exist and gives their facts. YGOJSON adds editions, database ids, card names in
other languages and archetype names. Yugipedia's set infobox gives each set its type, series, parent and Konami
database ids. TCGCSV, a mirror of TCGplayer's catalogue, gives the product ids, the editions each product is priced
in, and the sealed products. Nothing is matched by name order, and a product that no rule can settle goes to a review
file instead of into a guess.

Release 0.1.0 holds 1,046 sets, 14,645 cards, 46,082 prints, 60,688 printings, 910 archetypes, 1,144 sealed products
and 3,079 legality events. 44,322 prints have a TCGplayer product.

## Using the data

Each tagged release attaches six files to a GitHub release:

```
https://github.com/ArthurG-data/ygjson/releases/latest/download/AllSets.json
https://github.com/ArthurG-data/ygjson/releases/latest/download/AllCards.json
https://github.com/ArthurG-data/ygjson/releases/latest/download/AllPrintings.json
https://github.com/ArthurG-data/ygjson/releases/latest/download/AllArchetypes.json
https://github.com/ArthurG-data/ygjson/releases/latest/download/AllProducts.json
https://github.com/ArthurG-data/ygjson/releases/latest/download/Legality.json
```

Every file is `{"meta": {"version": "0.1.0", "date": "2026-10-28", "sources": {...}}, "data": {...}}`. All six come
from one build, so a reader that downloads them separately can check that the versions agree. `meta.sources` names the
snapshot each source was last imported from: YGOPRODeck's `database_version`, YGOJSON's `increment` and the latest
`modifiedOn` among TCGCSV's groups. A build made without the caches leaves `sources` out.

| File | Keyed by | Holds |
|---|---|---|
| `AllSets.json` | set id (`legend-of-blue-eyes-white-dragon`) | name, code, type, series, parent, era, editions, TCGplayer group ids, identifiers, and the release with its date and key art |
| `AllCards.json` | card id (`89631139`) | the facts every print of the card shares, its name in each language, and the ids of its prints |
| `AllPrintings.json` | printing id (`legend-of-blue-eyes-white-dragon:89631139:LOB-001:ultra_rare:en:first`) | set, number, region, rarity and its tier, edition, finish, TCGplayer product ids |
| `AllArchetypes.json` | archetype slug (`blue-eyes`) | name, names by language, whether Konami calls it an archetype, and the ids of its member cards |
| `AllProducts.json` | sealed product id (`legend-of-blue-eyes-white-dragon-booster-box`) | category, set, TCGplayer product id, release date, contents and the sources that state them |
| `Legality.json` | `formats`, `events` | the four formats and every change of a card's status in them |

## Layout

- `sets/sets.json` lists every set, sorted by id. A set has a `type`, and may have a `series`, a `parent` and an
  `era`. It lists the `editions` it was printed in, the TCGplayer groups that sell it (`tcgplayerGroupIds`), and
  `identifiers` for YGOJSON, Yugipedia and Konami's card database. `source` is `ygoprodeck` for a set YGOPRODeck lists
  (1,036 sets) and `tcgplayer` for a set minted for a TCGplayer group YGOPRODeck lacks (10 sets).
- `sets/eras.json` holds the seven eras and their date windows.
- `data/cards/<bucket>.json` holds the cards, bucketed by the millions of the card id (`89631139` lives in
  `089.json`). A card holds its facts and its `prints`.
- `data/archetypes.json` lists the archetypes, sorted by slug.
- `data/sealed/<set>.json` holds the sealed products of a set.
- `legality/` holds `formats.json` and `bans.json`.
- `mappings/` holds hand-kept inputs to the tools. `set_types.json` maps the type and series on a Yugipedia set
  infobox to a set type. `tcgplayer_groups.json` ties a TCGplayer group to a set where the automatic match fails. Each
  entry cites its evidence.
- `review/` lists what the tools could not decide, file by file (see [Review files](#review-files)).
- `schema/` holds a JSON Schema (draft 2020-12) for sets, eras, cards, archetypes, sealed products and legality events.
  None allows a property it does not name.

### Ids

- **Set id.** The slug of the YGOPRODeck set name: lower case, every run of characters outside `a-z0-9` becomes one
  hyphen. Names that slug alike are sorted, the first keeps the slug and the others get `-2`, `-3`. The one collision
  today is `Yu-Gi-Oh! 5D's Tag Force 5 Promotional Cards` (`yu-gi-oh-5d-s-tag-force-5-promotional-cards`) and
  `Yu-Gi-Oh! 5D's Tag Force 5 promotional cards` (`...-promotional-cards-2`). A set minted from a TCGplayer group gets
  its parent's id plus `-2020-reprint` or `-25th-anniversary-edition`. `code` is the prefix (`LOB`) and is not
  unique: 151 prefixes belong to more than one set.
- **Card id.** YGOPRODeck's card id, as a string. `passcode` is the same number when it is below 100,000,000, which is
  the 8-digit number printed on the card. YGOPRODeck gives cards that have no passcode an id above that line, and
  those cards have no `passcode`.
- **Print id.** `<set id>:<card id>:<set number or empty>:<rarity code>`. The same card in the same set at another
  rarity is another print. `legend-of-blue-eyes-white-dragon:89631139:LOB-001:ultra_rare` is the Ultra Rare Blue-Eyes
  White Dragon in Legend of Blue Eyes White Dragon.
- **Printing id.** `<print id>:<language>:<edition>`, where the edition is `first`, `unlimited` or `limited`. The
  printing above in first edition is `legend-of-blue-eyes-white-dragon:89631139:LOB-001:ultra_rare:en:first`.
  Printings are built from prints, never stored in the data files.
- **Archetype slug.** The slug of the name, deduplicated the same way as sets. Five pairs differ only in case or
  punctuation: `D.D.` (`d-d`) and `D/D` (`d-d-2`), `Roid` and `roid` (`roid-2`), `Sphinx` and `sphinx`
  (`sphinx-2`), `Tellarknight` and `tellarknight` (`tellarknight-2`), and `/Assault Mode` (`assault-mode`) and
  `Assault Mode` (`assault-mode-2`).
- **Sealed product id.** The slug of the TCGplayer product name without its edition tag, with `-2`, `-3` on a
  collision. The 1st Edition and Unlimited products of one box share a slug, so the first edition keeps it.

A rebuild from the same sources gives the same ids.

## Sets

`type` is the set's product line. YGOPRODeck states none, so `import_ygoprodeck.py` guesses it from the name and
`import_yugipedia.py` replaces the guess with the set infobox's type, through `mappings/set_types.json`. Today:

| type | Sets | AutoMana / MTG set type |
|---|---|---|
| booster | 267 | expansion |
| structure_deck | 63 | structure_deck |
| starter_deck | 31 | starter |
| tin | 43 | tin |
| special_edition | 75 | special_edition |
| sneak_peek | 61 | sneak_peek |
| duel_terminal | 15 | duel_terminal |
| speed_duel | 26 | speed_duel |
| promo | 403 | promo |
| box_set | 62 | box |

The schema also allows `other` for a set no rule places. No set has it today. `series` is Yugipedia's series for the
set (`Core Booster`, `Duelist Pack`, `Battles of Legend`), and 463 sets have one.

**Parents.** A sneak peek, a special edition or a promo that reprints a booster names it in `parent`. The Yugipedia
importer picks the one booster that shares the child's code, whose name the child's name starts with, or that the
two infoboxes' `other_sets` name. If two or more boosters qualify, nothing is set and the set goes to review. 138
sets have a parent: all 61 sneak peeks, 59 of the 75 special editions, and a few others.

- `absolute-powerforce-sneak-peek-participation-card` has parent `absolute-powerforce`.
- `absolute-powerforce-special-edition` has parent `absolute-powerforce`.
- `rise-of-the-duelist-premiere-promotional-card` has parent `rise-of-the-duelist`.
- `retro-pack-2020-reprint` has parent `retro-pack`.

**Eras.** A set's `era` is the era whose window holds its release date. A set with no date takes its parent's.
All sets but `summoned-skull-sample-promotional-card` have one.

| era | Name | Mechanic | From | To | Sets |
|---|---|---|---|---|---|
| `dm` | Duel Monsters | Fusion | 2002-03-08 | 2005-05-31 | 77 |
| `gx` | GX | Fusion | 2005-06-01 | 2008-09-01 | 185 |
| `5ds` | 5D's | Synchro | 2008-09-02 | 2011-08-15 | 148 |
| `zexal` | ZEXAL | Xyz | 2011-08-16 | 2014-08-14 | 136 |
| `arc_v` | ARC-V | Pendulum | 2014-08-15 | 2017-08-03 | 128 |
| `vrains` | VRAINS | Link | 2017-08-04 | 2020-08-06 | 169 |
| `sevens` | SEVENS and beyond | None | 2020-08-07 | | 202 |

**Editions.** A set lists the editions it was printed in: `first`, `unlimited` and `limited`. They come from three
places, in this order. YGOPRODeck states none, so the first import guesses `limited` for a name that holds "Limited
Edition" and `unlimited` for the rest. YGOJSON states the editions of a set it matches (`1st`, `unlimited`,
`limited`), which replace the guess. TCGCSV then adds every edition its prices show for the set's singles, where
TCGplayer names the subtypes `1st Edition`, `Unlimited` and `Limited`. A print lists its own `editions` only when its products are
priced in fewer editions than its set: 8,089 prints do.

**Key art.** `releases[0].keyArt` links to YGOPRODeck's set image (910 sets), else to the pack art YGOJSON gives from
Yugipedia (126 sets). The `source` is the page the image is on. The images are links and are never copied. No source
hosts set logos: Konami's product pages show pack mockups and Yugipedia has no logo file for a set. So ygjson has key
art and no logos.

## Cards and prints

A card has an `id`, an optional `passcode`, a `name` that equals `names.en`, and `names` in ten languages (`en`, `fr`,
`de`, `it`, `pt`, `es`, `ja`, `ko`, `zh-CN`, `zh-TW`) where YGOJSON has them. YGOJSON's romanisations (`ja_romaji`,
`ko_rr`) are not names and are left out. The other fields are:

- `kind`: monster, spell, trap, token or skill. 9,416 cards are monsters.
- `frame`: YGOPRODeck's `frameType`.
- `attribute` (lower case), `monsterType` (YGOPRODeck's `race`: the monster type, or the spell or trap subtype),
  `level`, `rank`, `linkRating`, `linkArrows`, `scale`, `atk` and `def`. `rank` is the level of a Xyz monster,
  which YGOPRODeck reports as `level`. A card that prints `?` has no `atk` or `def`, and a Link monster has no `def`.
- `hasEffect`, `isTuner` and `typeline`, the tokens of the type line in order (`Cyberse`, `Link`, `Effect`).
- `archetypes`: archetype slugs.
- `tcgDate` and `ocgDate`: the card's first release in each, per YGOPRODeck.
- `images`: links to YGOPRODeck's full image, small image and cropped art, one entry per artwork.
- `identifiers`: `ygoprodeckId`, and `konamiId` (14,415 cards), `ygojsonId` (13,984) and `yugipediaIds` where known.
- `prints`: every print of the card.

A print has `id`, `set`, `number` (`LOB-001`), `region`, `rarity`, `editions` where they differ from the set's,
`identifiers.tcgplayerProductIds` and `tcgplayer`. `region` is the letters between the set prefix and the digits of the
number: `LOB-EN001` has `EN`, `LOB-001` has none, and `LAVD-ENS05` has `EN` because the letter after the region is a
slot. The commonest regions are `EN` (42,785 prints), `E` (732) and `PT` (456).

**Rarity.** A print's `rarity` is a code from `tools/rarities.py`, which maps YGOPRODeck's and TCGplayer's free text
onto 41 codes (`common`, `rare`, `super_rare`, `ultra_rare`, `secret_rare`, `qc_secret_rare`, `starlight_rare`,
`dt_normal_parallel` and so on). Text the table does not know becomes `unknown`, and the print keeps the source's
string as `rawRarity`. 30 prints are `unknown`; `review/rarities.json` counts each raw string. The table is the one
place that decides a rarity, its finish and its tier.

**Finish.** A printing is `nonfoil` for four rarities, `common`, `short_print`, `super_short_print` and `rare`.
Every other code is `foil`. An `unknown` rarity gives `null`: 58 printings have no finish. TCGplayer prices a single
by edition and not by finish, so the finish is a property of the rarity.

**Tier.** `rarityTier` is a value ladder from 1 to 5, with a parallel rarity ranking with its base. The printing has
no tier when its rarity is `unknown`.

| Tier | Rarities |
|---|---|
| 1 | `common`, `short_print`, `super_short_print` |
| 2 | `rare`, `normal_parallel_rare`, `dt_normal_parallel`, `dt_rare_parallel` |
| 3 | `super_rare`, `super_parallel_rare`, `dt_super_parallel` |
| 4 | `ultra_rare`, `ultimate_rare`, `ultra_parallel_rare`, `dt_ultra_parallel`, `gold_rare`, `premium_gold_rare`, `platinum_rare`, `starfoil_rare`, `mosaic_rare`, `shatterfoil_rare`, and the Millennium rare, super and ultra |
| 5 | every other code: the secret families, ghost, starlight, collector's, grand master, Pharaoh's, Millennium secret and gold |

**Child sets.** TCGplayer sells some reprints under a group of their own. A group named `<set> (2020 Date Reprint)`
or `(2020 Reprint)` becomes a set `<parent id>-2020-reprint`, with the parent's code, type, era and editions and the
parent set as its `parent`. Its prints are copies of the parent's prints that the group's products name. Nine such
sets exist. The group `Invasion of Chaos (25th Anniversary Edition)` becomes `invasion-of-chaos-25th-anniversary-edition`
the same way. YGOPRODeck lists the other 25th Anniversary Edition sets itself, so they are ordinary sets.

**TCGplayer products.** A TCGCSV single is a product with a card number or a rarity. It is tied to a print in three
passes, so a loose match never takes a print an exact one wants. The first pass ties the number and the canonical
rarity within the group's set. The second takes the group's set and the number alone. The third looks for the number in
the other sets, for a set TCGplayer names differently. A product lands on one print only. A print holds several
products only when they are the same card at the same rarity, like the Red and Blue tin promos. Each print's
`tcgplayer.match` names the rule that tied it:

| `match` | Prints | Evidence |
|---|---|---|
| `number+rarity` | 40,985 | the group's set has a print with this number and this rarity |
| `number+rarity-from-tcgplayer` | 187 | one print of the number had an `unknown` rarity, which takes TCGplayer's rarity and a new id |
| `number` | 443 | the group's set has exactly one print of this number |
| `number-other-set` | 2,707 | the group's set lacks the number, and exactly one other set has it |

1,760 prints have no product. A single no rule settles goes to `review/tcgplayer-2.json`: `unmatched` has the product
and the reason, and `conflicts` lists a product that would share a print with another card or rarity.
`tools/coverage.py` accounts for every product in category 2.

**No effect text.** ygjson records facts. It copies no card effect text, product description or card art, and its image
fields are links. A reader that needs the text reads it from TCGCSV or YGOPRODeck at load time. See `NOTICE`.

## Archetypes

`data/archetypes.json` holds the archetypes YGOPRODeck names (667) plus the YGOJSON series that Konami calls an
archetype and YGOPRODeck lacks (243). `source` says which. A YGOJSON series that matches one of ours by English name
adds `names` in ten languages, `isArchetype` and its YGOJSON id. `isArchetype` is false for a series Konami does not
call an archetype (106 today). A card's `archetypes` lists slugs, and `AllArchetypes.json` derives `members`, the card
ids of the archetype in numeric order, at build time. 131 archetypes have no member card yet.

## Sealed products

A sealed product is a TCGCSV product with neither a card number nor a rarity, in a group matched to a set. It lives
in `data/sealed/<set id>.json`. 1,144 are listed.

`category` is one of booster_pack (383), booster_box (284), display (112), structure_deck (79), special_edition (63),
tin (43), collectors_set (42), starter_deck (37), deck (22), mega_tin (15), case (15), bundle (6), promo_pack (5) or
other (38). The category comes from ordered name rules, first match wins. A product that is an accessory, such as a
binder or a card box for a field center, is skipped and appears in no file. 70 products in groups
with no set go to `review/sealed.json` under `noSet`.

`contents` lists only what a rule or a source states:

- a booster box holds 24 of the group's one booster pack with the same edition tag (`complete`). A mini box lists the
  pack without a count (`partial`);
- a case holds 12 of the group's one booster box (`complete`);
- a display lists the group's one pack, structure deck or starter deck without a count (`partial`);
- a booster pack has a `pool` of its set, with the edition from its tag (`partial`);
- a structure deck, starter deck, deck, tin, mega tin or special edition lists the prints of its set, without counts
  (`partial`), only when the set holds just that product's cards;
- anything else has no contents.

**YGOJSON.** A product YGOJSON names the same (normalised English name) gains `identifiers.ygojsonId` and the packs
YGOJSON lists for it: 199 products. A pack of one of our sets becomes a `sealed` entry for that set's booster pack with
YGOJSON's quantity. A pack that names a card becomes a `cards` entry for that card's print. Contents YGOJSON states
replace the rule-written `cards`, and the product is `complete` when every pack resolved with a quantity.

`contentsStatus` is `complete` when every item and count is stated (234 products), `partial` when what is listed is
right but items or counts are missing (673), and `unknown` when nothing is stated (237). Each product's `sources` cite
TCGplayer's product page and the YGOJSON record.

## Legality

`legality/formats.json` lists four formats: `tcg`, `ocg`, `speed_duel` and `goat`. `legality/bans.json` holds events,
sorted by card id, format and date. An event says a card's status in a format changed. A status is copies allowed:
`banned` 0, `limited` 1, `semi_limited` 2 and `legal` 3. The status in force on a date is the card's last event on or
before it, and before its first event the card is legal.

An event has `effective`, the date a source states, or `inForceBy`, the date the tool first saw the status. An
`inForceBy` date is a latest date: the change may have started earlier, and no source says when.

- **History.** YGOJSON dates every change in a card's `tcg`, `ocg` and `speed` history. Each dated entry is an event
  with source `ygojson` (2,847 events). YGOJSON's `forbidden`, `limited`, `semilimited` and `unlimited` are `banned`,
  `limited`, `semi_limited` and `legal`. Speed Duel also uses `limit1`, `limit2` and `limit3`, which are `limited`,
  `semi_limited` and `legal`. `unreleased` is not a status and makes no event.
- **Current status.** YGOPRODeck's `banlist_info` leads for `tcg`, `ocg` and `goat`, and a card with no entry for a
  format is legal. YGOJSON leads for `speed_duel`. The lead source's current status becomes an event only when it
  differs from the card's last event, or from legal when there is none. That event has `inForceBy`, and the source
  is `ygoprodeck` or `ygojson` (232 events). YGOPRODeck has no history and YGOJSON has no GOAT list, so every GOAT
  event is of this kind.
- **Dates stick.** `tools/legality.py` loads `bans.json` first and never rewrites or removes an event in it. A date it
  wrote once stays across releases.

The file holds 3,079 events: 1,553 in `ocg`, 1,388 in `tcg`, 73 in `goat` and 65 in `speed_duel`; 501 `banned`, 1,081
`limited`, 725 `semi_limited` and 772 `legal`.

`uv run python tools/legality.py --check` replays the events to today and compares each card and format with the lead
source's current status. It prints each difference and exits 1 if there is any. A difference means a ban list changed
since the last run: run `tools/legality.py` and commit `bans.json`. The check needs YGOPRODeck's card list and
downloads it into `.cache/ygoprodeck` when it is missing, so CI checks the committed events against the list as it is
today. `speed_duel` needs `.cache/ygojson` and is skipped without it.

## Review files

| File | Lists |
|---|---|
| `review/rarities.json` | rarity strings that mapped to `unknown`, with the number of prints, and the count of duplicate rows YGOPRODeck repeats |
| `review/ygojson.json` | YGOPRODeck sets with no YGOJSON match, YGOJSON English sets no set of ours claimed, sets matched by the weaker rules, cards with no match, skipped series |
| `review/yugipedia.json` | sets with no page or infobox, infobox types the mapping lacks, pages shared by several sets, ambiguous parents |
| `review/tcgplayer-2.json` | TCGplayer products no rule could tie to a print (`unmatched`), products that would share a print (`conflicts`), groups with no set (`groups`), and groups matched through an alias (`groupAliases`) |
| `review/sealed.json` | sealed products in a group with no set (`noSet`), products with category `other`, and YGOJSON products no TCGplayer product matched (`ygojsonUnmatched`) |

`uv run python tools/coverage.py` reports where every TCGplayer product in category 2 ended up: on a print, on a
sealed product, skipped as an accessory, in a group published after today, or in review. `--strict` exits 1 if any
product is unaccounted for.

## Building

```sh
uv sync --group dev
uv run python tools/import_ygoprodeck.py   # sets, cards, prints and archetypes; --refresh downloads YGOPRODeck again
uv run python tools/import_ygojson.py      # editions, ids, names and series
uv run python tools/import_yugipedia.py    # set types, series, parents and database ids
uv run python tools/import_tcgcsv.py       # TCGplayer groups and products
uv run python tools/import_sealed.py       # sealed products
uv run python tools/coverage.py [--strict] # where every TCGplayer product went
uv run python tools/legality.py            # ban list events
uv run python tools/validate.py [--online]
uv run python tools/build.py --version 0.1.0   # dist/AllSets, AllCards, AllPrintings, AllArchetypes, AllProducts, Legality
```

The order matters: each importer keeps what the earlier ones wrote and adds its own fields, so a rerun in order
changes nothing unless a source changed. The downloads are cached under `.cache/`, which is never committed. YGOPRODeck
is fetched on the first run. Yugipedia pages and TCGCSV files are fetched when they are not cached, at one request per
second and one every half second. YGOJSON has no downloader: put the files of its `v1/aggregate` branch (`cards.json`,
`sets.json`, `series.json`, `sealedProducts.json`, `meta.json`) in `.cache/ygojson`. To take a newer TCGCSV or
Yugipedia snapshot, move that cache aside and rebuild.

`validate.py` checks every file against its schema, then every id and reference: print ids follow the rule, a print's
set exists, no parent loops, no TCGplayer product or group sits on two prints or sets, archetype slugs exist, and a
legality event names a card and a format that exist. `--online` also asks TCGCSV whether every TCGplayer product id on
a print or a sealed product still exists in category 2. It downloads the catalogue into a temporary directory, about
660 requests.

`build.py` runs the same checks and refuses to write anything if one fails. It needs nothing from `.cache/`: with no
caches it leaves `meta.sources` out.

## Development

```sh
uv sync --group dev
uv run pytest
uv run python tools/validate.py --online
uv run python tools/legality.py --check
```

CI runs those checks on every pull request and on every push to `main`. A `v*` tag also builds the release files with
the tag's version and attaches them to a GitHub release.

## Licence

The tools and tests are MIT (`LICENSE`). The data and schemas are CC BY 4.0 (`LICENSE-DATA`). See `NOTICE` for what is
and is not copied from the sources. Yu-Gi-Oh! and its marks belong to Kazuki Takahashi/Shueisha and Konami. ygjson is
not affiliated with them, YGOPRODeck, Yugipedia or TCGplayer.
