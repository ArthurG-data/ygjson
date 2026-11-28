# ygjson

An open dataset of Yu-Gi-Oh! TCG sets, cards, printings, archetypes, sealed products and Forbidden & Limited
history, in English. Every print carries the TCGplayer product ids that sell it. YGOPRODeck leads the data: it
decides which sets, cards and prints exist and gives their facts. YGOJSON adds editions, database ids, card names in
other languages and archetype names. Yugipedia's set infobox gives each set its type, series, parent and Konami
database ids. TCGCSV, a mirror of TCGplayer's catalogue, gives the product ids, the editions each product is priced
in, and the sealed products. Nothing is matched by name order, and a product that no rule can settle goes to a review
file instead of into a guess.

Release <!--n:release.version-->0.2.0<!--/n--> holds <!--n:release.sets-->1,066<!--/n--> sets, <!--n:release.cards-->14,731<!--/n--> cards, <!--n:release.prints-->48,494<!--/n--> prints, <!--n:release.printings-->63,155<!--/n--> printings,
<!--n:release.archetypes-->910<!--/n--> archetypes, <!--n:release.sealed-->1,160<!--/n--> sealed products and <!--n:release.events-->3,105<!--/n--> legality events. <!--n:release.prints_with_product-->46,142<!--/n--> prints have a TCGplayer
product. The numbers below describe the data on `main`.

## Using the data

Each tagged release attaches seven files to a GitHub release:

```
https://github.com/ArthurG-data/ygjson/releases/latest/download/AllSets.json
https://github.com/ArthurG-data/ygjson/releases/latest/download/AllCards.json
https://github.com/ArthurG-data/ygjson/releases/latest/download/AllPrintings.json
https://github.com/ArthurG-data/ygjson/releases/latest/download/AllArchetypes.json
https://github.com/ArthurG-data/ygjson/releases/latest/download/AllProducts.json
https://github.com/ArthurG-data/ygjson/releases/latest/download/Legality.json
https://github.com/ArthurG-data/ygjson/releases/latest/download/Ids.json
```

Every file is `{"meta": {"version": "0.2.0", "date": "2026-11-07", "sources": {...}, "idsVersion": 1, "reviewCounts": {...}}, "data": {...}}`. All seven come
from one build, so a reader that downloads them separately can check that the versions agree. `meta.sources` is the
committed [`sources.json`](sources.json): the snapshot of each source the data was imported from (see
[Rebuilding a release](#rebuilding-a-release)).

| File | Keyed by | Holds |
|---|---|---|
| `AllSets.json` | set id (`legend-of-blue-eyes-white-dragon`) | name, code, type, series, parent, era, editions, TCGplayer group ids, identifiers, and the release with its date and key art |
| `AllCards.json` | card id (`89631139`) | the facts every print of the card shares, its name in each language, and the permanent ids of its prints |
| `AllPrintings.json` | printing id, `<print uuid>:<language>:<edition>` (`7fb2b3b7-22d1-5e78-8f11-31cfa734fbe9:en:first`) | its readable `key` (`legend-of-blue-eyes-white-dragon:89631139:LOB-001:ultra_rare:en:first`), `print` (the print's UUID), `printKey`, set, number, region, rarity and its tier, edition, finish, TCGplayer product ids, `tcgplayerPrice`: the product and price subtype of its edition, and `scan`: Yugipedia's picture of it |
| `AllArchetypes.json` | archetype slug (`blue-eyes`) | name, names by language, whether Konami calls it an archetype, and the ids of its member cards |
| `AllProducts.json` | sealed product id (`legend-of-blue-eyes-white-dragon-booster-box`) | category, set, TCGplayer product id, release date, contents and the sources that state them |
| `Ids.json` | kind (`prints`, `printings`, `cards`, `sets`, `archetypes`, `sealed`), then permanent id | the id ledger: each id's readable `key`, its `formerKeys` or `formerIds`, `successors` and `status` (see [Ids](#ids)) |
| `Legality.json` | `formats`, `events` | the four formats and every change of a card's status in them |

## Layout

- `sets/sets.json` lists every set, sorted by id. A set has a `type`, and may have a `series`, a `parent` and an
  `era`. It lists the `editions` it was printed in, the TCGplayer groups that sell it (`tcgplayerGroupIds`: each group
  is on the one set its latest TCGCSV import matched it to), and `identifiers` for YGOJSON, Yugipedia and Konami's
  card database. `source` is `ygoprodeck` for a set YGOPRODeck lists
  and `tcgplayer` for a set minted for a TCGplayer group YGOPRODeck lacks, such as `Speed Duel: Battle City Finals`.
- `sets/eras.json` holds the seven eras and their date windows.
- `data/cards/<bucket>.json` holds the cards, bucketed by the millions of the card id (`89631139` lives in
  `089.json`). A card holds its facts and its `prints`.
- `data/archetypes.json` lists the archetypes, sorted by slug.
- `data/sealed/<set>.json` holds the sealed products of a set.
- `legality/` holds `formats.json` and `bans.json`.
- `mappings/` holds hand-kept inputs to the tools. `set_types.json` maps the type and series on a Yugipedia set
  infobox to a set type. `tcgplayer_groups.json` ties a TCGplayer group to a set where the automatic match fails.
  `tcgplayer_products.json` names the card of a TCGplayer single whose number no print has and whose name is no
  card's (`Synch Realm` is `Synchronized Realm`), so its print is minted.
  `ygoprodeck_set_aliases.json` names a YGOPRODeck set that is another set under a second name: the alias is not
  written and its prints go to the owner (`WCS 2025 Limited Pack` is `Limited Pack World Championship 2025`). Each
  entry cites its evidence. `ids.json` holds the hand decisions on the id ledger (see [Ids](#ids)). `ignore.json`
  and `print_overrides.json` hold the review items accepted as they are and the print facts set by hand (see
  [Hand decisions](#hand-decisions)).
- `review/` lists what the tools could not decide, file by file (see [Review files](#review-files)).
- `schema/` holds a JSON Schema (draft 2020-12) for sets, eras, cards, archetypes, sealed products and legality events.
  None allows a property it does not name.

### Ids

- **Set id.** The slug of the YGOPRODeck set name: lower case, every run of characters outside `a-z0-9` becomes one
  hyphen. Names that slug alike are sorted, the first keeps the slug and the others get `-2`, `-3`. The one collision
  today is `Yu-Gi-Oh! 5D's Tag Force 5 Promotional Cards` (`yu-gi-oh-5d-s-tag-force-5-promotional-cards`) and
  `Yu-Gi-Oh! 5D's Tag Force 5 promotional cards` (`...-promotional-cards-2`). A set minted from a TCGplayer group gets
  its parent's id plus `-2020-reprint` or `-25th-anniversary-edition`. `code` is the prefix (`LOB`) and is not
  unique: <!--n:prefixes_shared-->150<!--/n--> prefixes belong to more than one set.
- **Card id.** YGOPRODeck's card id, as a string. `passcode` is the same number when it is below 100,000,000, which is
  the 8-digit number printed on the card. YGOPRODeck gives cards that have no passcode an id above that line, and
  those cards have no `passcode`.
- **Print key.** `<set id>:<card id>:<set number or empty>:<rarity code>[:<variant>]`. The same card in the same set at
  another rarity is another print. `legend-of-blue-eyes-white-dragon:89631139:LOB-001:ultra_rare` is the Ultra Rare
  Blue-Eyes White Dragon in Legend of Blue Eyes White Dragon. The data files use the key as the print's `id`.
- **Printing key.** `<print key>:<language>:<edition>`, where the edition is `first`, `unlimited` or `limited`.
  Printings are built from prints, never stored in the data files.
- **Archetype slug.** The slug of the name, deduplicated the same way as sets. Five pairs differ only in case or
  punctuation: `D.D.` (`d-d`) and `D/D` (`d-d-2`), `Roid` and `roid` (`roid-2`), `Sphinx` and `sphinx`
  (`sphinx-2`), `Tellarknight` and `tellarknight` (`tellarknight-2`), and `/Assault Mode` (`assault-mode`) and
  `Assault Mode` (`assault-mode-2`).
- **Sealed product id.** The slug of the TCGplayer product name without its edition tag, with `-2`, `-3` on a
  collision. The 1st Edition and Unlimited products of one box share a slug, so the first edition keeps it.

#### Permanent ids

A key is readable and may change: a rename of a set, a new rarity code or a corrected number moves it. The release
files name a print and a printing by a permanent id that never changes. `ids/` holds the ledger, one file per kind,
and `Ids.json` ships it.

- A print's `id` is a UUID. A printing's `id` is `<print id>:<language>:<edition>`, so it carries the print's UUID.
  `AllPrintings.json` is keyed by it. Each printing also holds `key` (its readable id), `print` (the print's UUID)
  and `printKey` (the print's readable key). `AllCards.json` lists a card's prints, and a sealed product's `cards`
  name prints, by UUID.
- An entry in `Ids.json` is `{"id", "key", "status", ...}`. `key` is the readable key the id has now. A print's
  `formerKeys` lists the keys it had before, and a printing's `formerIds` the readable ids it had.
- `status` is `live` for an id the data still has, and `retired` for one it no longer has. A retired id is never
  reused or removed. Its `successors` lists the ids that replaced it, and is empty when nothing did.
- To resolve a stored id or key, in `data.prints` (or `data.printings`):
  1. take the entry whose `id` is it, else the entry whose `key` is it, else the entries whose `formerKeys`
     (`formerIds` for a printing) hold it;
  2. of several, prefer the `live` one;
  3. if it is `retired`, follow its `successors`, through retired successors too, to the live ids. One live id is
     what it became. Several, or none, means the data cannot tell which print it was: ask the holder.
- Cards, sets, archetypes and sealed products keep their ids and have entries too, so `Ids.json` lists every id the
  data has ever used.
- `meta.idsVersion` is the version of this layout. It is `1`.

#### Migrating from 0.2.0

- `AllPrintings.json` is keyed by `<print uuid>:en:<edition>` instead of the readable printing id.
- A printing's `print` is the print's UUID. `printKey` holds the readable print key (what `print` held in 0.2.0) and
  `key` the readable printing id (what keyed it). Both are today's and may differ from the ones 0.2.0 published.
- Look each stored 0.2.0 id up in `Ids.json` as above (it is a `key` or a `formerKeys`/`formerIds` entry) and store
  the `id` it resolves to.

#### The ledger

`uv run python tools/ids.py` reconciles the data with the ledger after the imports. `mappings/ids.json` holds the
decisions a person makes where it cannot: which retired print a new key continues (`prints`) and which prints
replace a retired id (`successors`). Each cites its evidence. `review/ids.json` lists the retired prints and cards
whose successors lead to no live id (`dead-end`) or to several (`several`), and this run's set and archetype renames.
A set's `identity` holds its YGOJSON, Yugipedia and Konami ids and its TCGplayer groups (`tcgplayer:<groupId>`), and
a new slug sharing one with exactly one vanished slug is that set renamed. So a set `import_tcgcsv.py` minted for an
unclaimed group hands its slug to the later set that holds the group, instead of standing beside it under a `-2`.

To settle a review row:

1. Restore the ledger from the base branch, so the run that decides it starts from what was published:
   `git checkout origin/main -- ids/`.
2. Add the entry to `mappings/ids.json` (under `prints` or `successors`) with its `why`.
3. Run `uv run python tools/ids.py` again.

## Sets

`type` is the set's product line. YGOPRODeck states none, so `import_ygoprodeck.py` guesses it from the name and
`import_yugipedia.py` replaces the guess with the set infobox's type, through `mappings/set_types.json`. Today:

| type | Sets | AutoMana / MTG set type |
|---|---|---|
| booster | <!--n:type.booster-->273<!--/n--> | expansion |
| structure_deck | <!--n:type.structure_deck-->63<!--/n--> | structure_deck |
| starter_deck | <!--n:type.starter_deck-->31<!--/n--> | starter |
| tin | <!--n:type.tin-->43<!--/n--> | tin |
| special_edition | <!--n:type.special_edition-->75<!--/n--> | special_edition |
| sneak_peek | <!--n:type.sneak_peek-->61<!--/n--> | sneak_peek |
| duel_terminal | <!--n:type.duel_terminal-->15<!--/n--> | duel_terminal |
| speed_duel | <!--n:type.speed_duel-->29<!--/n--> | speed_duel |
| promo | <!--n:type.promo-->412<!--/n--> | promo |
| box_set | <!--n:type.box_set-->63<!--/n--> | box |

The schema also allows `other` for a set no rule places. No set has it today. `series` is Yugipedia's series for the
set (`Core Booster`, `Duelist Pack`, `Battles of Legend`), and <!--n:sets_with_series-->466<!--/n--> sets have one.

**Parents.** A sneak peek, a special edition or a promo that reprints a booster names it in `parent`. The Yugipedia
importer picks the one booster that shares the child's code, whose name the child's name starts with, or that the
two infoboxes' `other_sets` name. If two or more boosters qualify, nothing is set and the set goes to review.
<!--n:sets_with_parent-->138<!--/n--> sets have a parent: <!--n:type.sneak_peek.with_parent-->61<!--/n--> of the <!--n:type.sneak_peek-->61<!--/n--> sneak peeks, <!--n:type.special_edition.with_parent-->59<!--/n--> of the <!--n:type.special_edition-->75<!--/n--> special editions,
and a few others.

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
TCGplayer names the subtypes `1st Edition`, `Unlimited` and `Limited`.

A print lists its own `editions` only when they differ from its set's: <!--n:prints_own_editions-->10,364<!--/n--> prints do. A print holding products
has the editions they are priced in. That is mostly fewer than its set's, but a product of another group that lands in
a 2020 reprint set keeps the original's editions on its print. A print with no product has its set's editions, except
in a set that mixes `limited` with other editions. There Limited is usually a few special prints (the God cards of
Yugi's Legendary Decks) or all of them (a Duel Terminal set), so the print has the editions most of the set's priced
prints have, unless two lists tie. <!--n:prints_voted_editions-->109<!--/n--> prints get their editions this way.

**Key art.** `releases[0].keyArt` links to YGOPRODeck's set image (<!--n:keyart.ygoprodeck-->911<!--/n--> sets), else to the pack art YGOJSON gives from
Yugipedia (<!--n:keyart.ygojson-->127<!--/n--> sets). The `source` is the page the image is on. The images are links and are never copied. No source
hosts set logos: Konami's product pages show pack mockups and Yugipedia has no logo file for a set. So ygjson has key
art and no logos.

## Cards and prints

A card has an `id`, an optional `passcode`, a `name` that equals `names.en`, and `names` in ten languages (`en`, `fr`,
`de`, `it`, `pt`, `es`, `ja`, `ko`, `zh-CN`, `zh-TW`) where YGOJSON has them. YGOJSON's romanisations (`ja_romaji`,
`ko_rr`) are not names and are left out. The other fields are:

- `kind`: monster, spell, trap, token or skill. <!--n:cards_monster-->9,421<!--/n--> cards are monsters.
- `frame`: YGOPRODeck's `frameType`.
- `attribute` (lower case), `monsterType` (YGOPRODeck's `race`: the monster type, or the spell or trap subtype),
  `level`, `rank`, `linkRating`, `linkArrows`, `scale`, `atk` and `def`. `rank` is the level of a Xyz monster,
  which YGOPRODeck reports as `level`. A card that prints `?` has no `atk` or `def`, and a Link monster has no `def`.
- `hasEffect`, `isTuner` and `typeline`, the tokens of the type line in order (`Cyberse`, `Link`, `Effect`).
- `archetypes`: archetype slugs.
- `tcgDate` and `ocgDate`: the card's first release in each, per YGOPRODeck.
- `images`: links to YGOPRODeck's full image, small image and cropped art, one entry per artwork.
- `identifiers`: `ygoprodeckId`, and `konamiId` (<!--n:cards_konami-->14,495<!--/n--> cards), `ygojsonId` (<!--n:cards_ygojson-->13,991<!--/n-->) and `yugipediaIds` where known.
- `prints`: every print of the card.

A print has `id`, `set`, `number` (`LOB-001`), `region`, `rarity`, `editions` where they differ from the set's,
`identifiers.tcgplayerProductIds` and `tcgplayer`. `region` is the letters between the set prefix and the digits of the
number: `LOB-EN001` has `EN`, `LOB-001` has none, and `LAVD-ENS05` has `EN` because the letter after the region is a
slot, and `TDIL-ENSE3` has `EN` because `SE` marks a special edition. The commonest regions are `EN` (<!--n:region.EN-->45,491<!--/n--> prints), `E` (<!--n:region.E-->732<!--/n-->) and `PT` (<!--n:region.PT-->456<!--/n-->).

**Scans.** A print's `scans` links Yugipedia's picture of that print in each edition (`{"first": ..., "unlimited":
...}`), so it shows which of the card's artworks the print carries; a printing has the one of its edition as `scan`.
They come from YGOJSON, which lists each printing of a set's English locales with its scan: a printing is the locale's
prefix and its suffix (`LOB-EN` + `005`) for one card, and lands on the YGOPRODeck print of that set, card and number at
its rarity, or on the only print of that number when YGOJSON has only one printing of it. <!--n:prints_with_scan-->37,489<!--/n--> prints have
scans, and <!--n:printings_with_scan-->48,883<!--/n--> printings a `scan`. A print `import_tcgcsv` mints (a version, or a number YGOPRODeck lacks)
has none, since it is made afresh on each run; nor does a printing of another region (`AGOV-AE001`). A printing that
lands on no single print goes to `review/ygojson.json` `scansUnplaced`.

**Rarity.** A print's `rarity` is a code from `tools/rarities.py`, which maps YGOPRODeck's and TCGplayer's free text
onto <!--n:rarity_codes-->41<!--/n--> codes (`common`, `rare`, `super_rare`, `ultra_rare`, `secret_rare`, `qc_secret_rare`, `starlight_rare`,
`dt_normal_parallel` and so on). Text the table does not know becomes `unknown`, and the print keeps the source's
string as `rawRarity`, also once TCGplayer's rarity replaces `unknown` (`number+rarity-from-tcgplayer` below). <!--n:prints_unknown-->30<!--/n--> prints
are `unknown`; `review/rarities.json` counts each raw string. The table is the one
place that decides a rarity, its finish and its tier. TCGplayer's `Emblazoned Ultra Rare` and `Emblazoned Secret Rare`
are `ultra_rare` and `secret_rare`: Emblazoned is a treatment, and the product's `(EUR)` or `(ESR)` makes it a version
(see [Variants](#cards-and-prints)).

**Finish.** A printing is `nonfoil` for four rarities, `common`, `short_print`, `super_short_print` and `rare`.
Every other code is `foil`. An `unknown` rarity gives `null`: <!--n:printings_no_finish-->48<!--/n--> printings have no finish. TCGplayer prices a single
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
or `(2020 Reprint)` becomes a set `<parent id>-2020-reprint`, with the parent's code and type and the
parent set as its `parent`; its era follows its own release date. Its editions are the ones its own group's singles are priced in, or the parent's when
TCGplayer prices none. Its prints are copies of the parent's prints that the group's products name. Nine such
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
| `number+rarity` | <!--n:match.number+rarity-->41,618<!--/n--> | the group's set has a print with this number and this rarity |
| `number+rarity-from-tcgplayer` | <!--n:match.number+rarity-from-tcgplayer-->193<!--/n--> | one print of the number had an `unknown` rarity, which takes TCGplayer's rarity and a new id |
| `number` | <!--n:match.number-->436<!--/n--> | the group's set has exactly one print of this number |
| `number-other-set` | <!--n:match.number-other-set-->3,261<!--/n--> | the group's set lacks the number, and exactly one other set has it |
| `minted` | <!--n:match.minted-->675<!--/n--> | no print has the number, or the number is held at another rarity, and the product's name is one card: the print is created from the product |

**Prints from TCGplayer.** YGOPRODeck lags TCGplayer and omits whole sets. When no print anywhere has a product's number
and its name is exactly one card, `import_tcgcsv.py` creates the print with `source: "tcgplayer"`, in the group's set, or
in a set it creates for a group that matched none. The same card at a second rarity under one number gets its own print
too. A token product lands only on a token card: `Token: Grinder Golem` is not the card Grinder Golem. Each run drops
and creates these prints again.

**Variants.** A product whose name carries a foil colour (`Blue`, `Green`, `Purple`, `Red`, `Silver`, `Bronze`), an art
letter (`A` to `G`) or `Version <n>` has a price of its own: Zaborg the Thunder Monarch lists at 129.99 in Blue and 4.49 in
Green under one number and rarity. It lands on its own print, a copy of the base print with `variant` set (`blue`, `b`,
`version-2`) and that variant at the end of the print id. A base print whose products are all versions keeps no product
and stays if YGOPRODeck lists it, and its id does not change.

A treatment does the same when another product shares its number and rarity and would stay on the base print: a stamp
(`judge-stamp`), an art (`alternate-art`, `extended-art`, `7th-art`), `emblazoned`, a misprint or a reissue
(`25th-anniversary-edition`). Cyberse Code Magician is 0.29 plain and 8.80 in Extended Art under `MAMO-EN017`. Alone under
its number a treatment is the print: Ghost Reaper & Winter Cherries (Alternate Art) is `RA03-EN014`, and no plain card has
that number.

A colour or art with a treatment is one version, with the tags joined in the order the name gives them
(`alternate-art-silver`, `a-alternate-art`). A product naming two colours or two treatments goes to review.

A print has one price per edition, so it holds several products only when they price different editions: <!--n:prints_several_products-->10<!--/n--> prints hold an
original and its 2020 reprint, which is sold as another edition. When two products of one card, rarity and version price
the same edition, the print keeps the one pricing the most editions, then the oldest, and the other goes to review
`conflicts`. Such a print's `tcgplayer.editionProducts` names the product pricing each edition (`{"limited": 108330,
"unlimited": 616043}`).

**Prices.** A printing's `tcgplayerPrice` is `{"productId", "subTypeName"}`, the two fields a TCGCSV price row is
keyed by, so a price joins a printing without guessing: `first` is priced as `1st Edition`, `unlimited` as `Unlimited`
and `limited` as `Limited`, on the print's one product or the one `editionProducts` names. A printing whose print has no
product has no `tcgplayerPrice`.

**Aliases.** A card's `aliases` are other English names shops sell it under: YGOPRODeck's `beta_name` (`Red-Eyes B.
Dragon`), which the card also carries as `betaName`, and TCGplayer's product name at any of its prints (`Stellarnova
Binding`). A name another card has is never an alias, so `Luster Dragon` is not an alias of `Luster Dragon #2`. Each
run of `import_tcgcsv` starts a card's aliases from its `betaName` and adds TCGplayer's names from the products it ties
in that run, so a name it wrote before never mints a print by itself, and a beta name TCGplayer spells the same way
stays when the product moves.

<!--n:prints_no_product-->2,350<!--/n--> prints have no product. A single no rule settles goes to `review/tcgplayer-2.json`: `unmatched` has the product
and the reason, and `conflicts` lists a product that would share a print with another card, another rarity, or an edition
another product already prices.
`tools/coverage_report.py` accounts for every product in category 2.

**No effect text.** ygjson records facts. It copies no card effect text, product description or card art, and its image
fields are links. A reader that needs the text reads it from TCGCSV or YGOPRODeck at load time. See `NOTICE`.

## Archetypes

`data/archetypes.json` holds the archetypes YGOPRODeck names (<!--n:archetypes.ygoprodeck-->666<!--/n-->) plus the YGOJSON series that Konami calls an
archetype and YGOPRODeck lacks (<!--n:archetypes.ygojson-->243<!--/n-->). `source` says which. A YGOJSON series that matches one of ours by English name
adds `names` in ten languages, `isArchetype` and its YGOJSON id. `isArchetype` is false for a series Konami does not
call an archetype (<!--n:archetypes.not_archetype-->106<!--/n--> today). A card's `archetypes` lists slugs, and `AllArchetypes.json` derives `members`, the card
ids of the archetype in numeric order, at build time. <!--n:archetypes.no_member-->131<!--/n--> archetypes have no member card yet.

## Sealed products

A sealed product is a TCGCSV product with neither a card number nor a rarity, in a group matched to a set. It lives
in `data/sealed/<set id>.json`. <!--n:sealed-->1,160<!--/n--> are listed.

`category` is one of booster_pack (<!--n:sealed.booster_pack-->384<!--/n-->), booster_box (<!--n:sealed.booster_box-->285<!--/n-->), display (<!--n:sealed.display-->114<!--/n-->),
structure_deck (<!--n:sealed.structure_deck-->79<!--/n-->), special_edition (<!--n:sealed.special_edition-->63<!--/n-->), tin (<!--n:sealed.tin-->43<!--/n-->),
collectors_set (<!--n:sealed.collectors_set-->44<!--/n-->), starter_deck (<!--n:sealed.starter_deck-->37<!--/n-->), deck (<!--n:sealed.deck-->22<!--/n-->),
mega_tin (<!--n:sealed.mega_tin-->15<!--/n-->), case (<!--n:sealed.case-->15<!--/n-->), bundle (<!--n:sealed.bundle-->6<!--/n-->),
promo_pack (<!--n:sealed.promo_pack-->5<!--/n-->) or other (<!--n:sealed.other-->48<!--/n-->). The category comes from ordered name rules, first match wins. A product that is an accessory, such as a
binder or a card box for a field center, is skipped and appears in no file. <!--n:sealed.no_set-->55<!--/n--> products in groups
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
YGOJSON lists for it: <!--n:sealed.ygojson-->199<!--/n--> products. A pack of one of our sets becomes a `sealed` entry for that set's booster pack with
YGOJSON's quantity. A pack that names a card becomes a `cards` entry for that card's print. Contents YGOJSON states
replace the rule-written `cards`, and the product is `complete` when every pack resolved with a quantity.

`contentsStatus` is `complete` when every item and count is stated (<!--n:sealed.status.complete-->235<!--/n--> products), `partial` when what is listed is
right but items or counts are missing (<!--n:sealed.status.partial-->674<!--/n-->), and `unknown` when nothing is stated (<!--n:sealed.status.unknown-->251<!--/n-->). Each product's `sources` cite
TCGplayer's product page and the YGOJSON record.

## Legality

`legality/formats.json` lists four formats: `tcg`, `ocg`, `speed_duel` and `goat`. `legality/bans.json` holds events,
sorted by card id, format and date. An event says a card's status in a format changed. A status is copies allowed:
`banned` 0, `limited` 1, `semi_limited` 2 and `legal` 3. The status in force on a date is the card's last event on or
before it, and before its first event the card is legal.

An event has `effective`, the date a source states, or `inForceBy`, the date the tool first saw the status. An
`inForceBy` date is a latest date: the change may have started earlier, and no source says when.

- **History.** YGOJSON dates every change in a card's `tcg`, `ocg` and `speed` history. Each dated entry is an event
  with source `ygojson` (<!--n:events.ygojson-->2,847<!--/n--> events). YGOJSON's `forbidden`, `limited`, `semilimited` and `unlimited` are `banned`,
  `limited`, `semi_limited` and `legal`. Speed Duel also uses `limit1`, `limit2` and `limit3`, which are `limited`,
  `semi_limited` and `legal`. `unreleased` is not a status and makes no event.
- **Dated lists.** YGOJSON's dates end with the October 2025 lists. From those lists onward, `tools/legality.py` reads
  Yugipedia's list pages, such as `October 2026 Lists (TCG)`, and follows each page's `next` link. Each change a list
  makes is an event with the page's `start_date` and source `yugipedia` (<!--n:events.yugipedia-->185<!--/n--> events). A list names every limited card,
  so a card it leaves out is legal, unless a name on that list matches no single card here. Such a list moves only the
  cards it names, and the tool prints the name. The walk stops at a page of another medium or format, at a date that
  does not move forward, or at a page that drops over a quarter of the last list, and the tool prints the last date it read.
  The tool reads Yugipedia and not Konami's card database, because that database's terms of use forbid automated
  collection.
- **Current status.** YGOPRODeck's `banlist_info` leads for `tcg`, `ocg` and `goat`, and a card with no entry for a
  format is legal. YGOPRODeck gives no status to any name with `<` or `>`, including cards Konami's list limits, so its
  silence on such a name says nothing. YGOJSON leads for `speed_duel`. The lead source's current status becomes an event
  only when it differs from the card's last event, or from legal when there is none. That event has `inForceBy`, and
  the source is `ygoprodeck` or `ygojson` (<!--n:events.in_force_by-->73<!--/n--> events). YGOPRODeck has no history and YGOJSON has no GOAT list, so every
  GOAT event is of this kind. In `tcg` and `ocg` such an event means a list reached YGOPRODeck before Yugipedia.
- **Exact dates replace undated ones.** `tools/legality.py` loads `bans.json` first and never rewrites or removes an
  event with `effective`. It removes an `inForceBy` event once the dated events give the same status on its date. A
  `legal` one also goes once the lead source no longer states the card. A restriction never goes because a source went
  silent, and an `inForceBy` event the dated events contradict otherwise stays, so a difference between the sources
  stays visible.

The file holds <!--n:events-->3,105<!--/n--> events: <!--n:events.ocg-->1,572<!--/n--> in `ocg`, <!--n:events.tcg-->1,395<!--/n--> in `tcg`, <!--n:events.goat-->73<!--/n--> in `goat` and <!--n:events.speed_duel-->65<!--/n--> in
`speed_duel`; <!--n:events.banned-->503<!--/n--> `banned`, <!--n:events.limited-->1,095<!--/n--> `limited`, <!--n:events.semi_limited-->738<!--/n--> `semi_limited` and <!--n:events.legal-->769<!--/n--> `legal`.

The history before October 2025 can miss a list. Konami's TCG lists of April 14, 2021 and March 10, 2023 have no events
here, so an event in the weeks after one of those dates reads as the list before it.

`uv run python tools/legality.py --check` replays the events to today and compares each card and format with the lead
source's current status. It prints each difference and exits 1 if there is any. A difference means a ban list changed
since the last run: run `tools/legality.py` and commit `bans.json`. The check does not read Yugipedia. It needs YGOPRODeck's card list and
downloads it into `.cache/ygoprodeck` when it is missing, so CI checks the committed events against the list as it is
today. `speed_duel` needs `.cache/ygojson` and is skipped without it.

## Review files

| File | Lists |
|---|---|
| `review/rarities.json` | rarity strings that mapped to `unknown`, with the number of prints, and the count of duplicate rows YGOPRODeck repeats |
| `review/ygojson.json` | YGOPRODeck sets with no YGOJSON match, YGOJSON English sets no set of ours claimed, sets matched by the weaker rules, cards with no match, skipped series, scans that land on no single print |
| `review/yugipedia.json` | sets with no page or infobox, infobox types the mapping lacks, pages shared by several sets, ambiguous parents |
| `review/tcgplayer-2.json` | TCGplayer products no rule could tie to a print (`unmatched`), products that would share a print (`conflicts`), groups with no set (`groups`), and groups matched through an alias (`groupAliases`) |
| `review/sealed.json` | sealed products in a group with no set (`noSet`), products with category `other`, and YGOJSON products no TCGplayer product matched (`ygojsonUnmatched`) |
| `review/ids.json` | retired prints and cards whose successors lead to no live id or to several, and the sets and archetypes the last run renamed, for a person to settle in `mappings/ids.json` |

### Hand decisions

A review item that is settled by hand is recorded once and honoured on every rebuild, each with its `why`:

- `mappings/ignore.json` accepts review items as they are:
  `{"tcgplayer-2": {"unmatched": [{"match": {"productId": 23322}, "why": "..."}]}}`. An entry matches every item of
  that list whose fields include all of `match`. On the next run the importer moves the matched items out of the list
  into the file's `ignored` section, so the lists hold only what is still to settle.
- `mappings/print_overrides.json` sets a print fact a source gets wrong:
  `{"prints": {"<print id>": {"editions": ["first"], "why": "..."}}}`. `import_tcgcsv.py` applies it last. Only
  `editions` can be set, since a print's set, number, rarity and variant make its id.

`validate.py` reports an entry with no `why`, an ignore entry that matches nothing (the item is gone: remove the
entry), an item still listed or still ignored after its entry changed (rerun the pipeline), and an override whose
print does not exist or does not carry its values. `pipeline.py` and `build.py` print how many items the review lists
still hold, and every release records them per list in `meta.reviewCounts`: the number to bring down.

`uv run python tools/coverage_report.py` reports where every TCGplayer product in category 2 ended up: on a print, on a
sealed product, skipped as an accessory, in a group published after today, or in review. `--strict` exits 1 if any
product is unaccounted for.

## Building

```sh
uv sync --group dev
uv run python tools/pipeline.py [--from STAGE] [--refresh SOURCE] [--offline]   # the six import stages, in order
uv run python tools/coverage_report.py [--strict] # where every TCGplayer product went
uv run python tools/legality.py            # ban list events
uv run python tools/validate.py [--online]
uv run python tools/build.py --version 0.2.0   # dist/AllSets, AllCards, AllPrintings, AllArchetypes, AllProducts, Legality, Ids
```

`pipeline.py` runs the import stages in order, each printing its summary:

| Stage | Adds |
|---|---|
| `import_ygoprodeck` | sets, cards, prints and archetypes |
| `import_ygojson` | editions, ids, names and series |
| `import_yugipedia` | set types, series, parents and database ids |
| `import_tcgcsv` | TCGplayer groups and products |
| `import_sealed` | sealed products |
| `ids` | the id ledger (on a rename it exits 3, and the pipeline runs the stages once more) |

The order matters: each importer keeps what the earlier ones wrote and adds its own fields, so a rerun in order
changes nothing unless a source changed, and a stage run on its own, or out of order, can leave the data wrong without
saying so. The pipeline stops at the first stage that fails. `--from STAGE` starts at a later stage, and is refused
unless the stage before it completed in the last run, the data is still as that run left it (the pipeline keeps a hash
in `.cache/pipeline.json`), and every earlier source's cache holds the snapshot `sources.json` names. `--refresh
ygoprodeck`, `--refresh tcgcsv` and `--refresh ygojson` (the branch's current commit) download a source again before
its stage; `--offline` downloads nothing, so a stage whose cache is incomplete fails. The importers can still be run
one by one (`tools/import_*.py`, `tools/ids.py`), in this order. The downloads are cached under `.cache/`, which is never committed. YGOPRODeck
is fetched on the first run. Yugipedia pages and TCGCSV files are fetched when they are not cached, at one request per
second and one every half second. `import_ygojson.py` downloads YGOJSON's `v1/aggregate` branch at the commit
`sources.json` pins, when the cache holds another, and checks every file against the commit's git blob hash;
`--update` takes the branch's current commit instead. `--refresh` on
`import_ygoprodeck.py` and `import_tcgcsv.py` downloads into a new directory and puts it in place of the cache only once
every file has come, so a refresh that fails halfway leaves the old cache as it was. To take a newer Yugipedia snapshot,
move that cache aside and rebuild. Every download (`tools/fetch.py`) retries a 429, a 5xx, a network error or a reply
cut short, up to five tries with a doubling wait or what `Retry-After` asks, and Yugipedia is asked with `maxlag`; a
download that still fails stops the run with the URL and the reason. A cache file is written whole or not at all, and
one that is not valid JSON is fetched again. `import_tcgcsv.py` refuses a TCGCSV listing with no groups or
no products, and while a group the data holds is missing from the listing or has no products file, it leaves that
group's products, prints and set as they are.

`validate.py` checks every file against its schema, then every id and reference: print ids follow the rule, a print's
set exists, no parent loops, no TCGplayer product or group sits on two prints or sets, archetype slugs exist, a
legality event names a card and a format that exist, a set's era holds its release date (or is its parent's when it has
none), an archetype's `name` is its `names.en`, and no name has a leading, trailing or doubled space. The schemas fix
the values of `tcgplayer.match`, `linkArrows`, the language keys of `names` and the sealed categories, the shape of
every id that points at a set, era, print or sealed product, and require `rawRarity` on a print whose rarity is
`unknown`; `schema/formats.schema.json` covers `legality/formats.json`. `--online` also asks TCGCSV whether every TCGplayer product id on
a print or a sealed product still exists in category 2. It downloads the catalogue into a temporary directory, about
660 requests.

`validate.py` also checks `sources.json` against its schema and against each cache under `.cache/` that exists, and
names the importer to rerun when a cache holds another snapshot. `build.py` runs the same checks, except the caches,
and refuses to write anything if one fails. It needs nothing from `.cache/`, so CI builds the release from the committed
data and copies `sources.json` into `meta.sources`.

### Rebuilding a release

`sources.json` records, for the data on `main`, the snapshot of each source, written by the importer that read it:

| Source | Recorded | Written by |
|---|---|---|
| `ygoprodeck` | `databaseVersion` and `lastUpdate` from `checkDBVer.php` | `import_ygoprodeck.py` |
| `ygojson` | the `v1/aggregate` `commit` and its `increment` | `import_ygojson.py` |
| `tcgcsv` | the latest `modifiedOn` among the groups | `import_tcgcsv.py` |
| `yugipedia` | the `pages` cached and the UTC day the newest was fetched (`fetchedThrough`) | `import_yugipedia.py`, `legality.py` |

Every release file carries the same object in `meta.sources`. A release's data is the commit it was tagged at, so to
rebuild one, check out its tag and run `uv run python tools/build.py --version <version>`: the build reads only
committed files. To redo the imports themselves, run the pipeline above on that checkout. YGOJSON comes back exactly:
`import_ygojson.py` downloads the pinned commit (YGOJSON rewrites the branch on each update, so a commit GitHub has
since dropped can no longer be fetched). YGOPRODeck, TCGCSV and Yugipedia serve only today's data, so an exact rerun
needs the `.cache/` the release was imported from; `validate.py` says whether a cache is that one.

## Development

```sh
uv sync --group dev
uv run ruff check                          # lint
uv run mypy                                # types (tools/)
uv run pytest
uv run python tools/validate.py            # offline
uv run python tools/stats.py [--write]     # the README's numbers against the data; --write updates them
uv run python tools/validate.py --online   # also checks product ids against TCGCSV
uv run python tools/legality.py --check    # compares with YGOPRODeck's live list
```

CI runs only the offline checks (ruff, mypy, pytest, `validate.py`, `stats.py`, and the id ledger check against the previous state)
on every pull request, every push to `main` and every `v*` tag. Every count this README quotes sits between two HTML
comments, `n:<key>` before it and `/n` after it, which do not show once rendered; `tools/stats.py` computes them from the committed data and fails
when one differs, and `--write` rewrites them. The release paragraph names the version in `pyproject.toml` and the counts
of its tag, or of the working tree before the tag exists: to release, bump the version, run `stats.py --write`, commit
and tag. pytest includes `tests/test_pipeline.py`, which runs
`pipeline.py --offline` end to end on a small snapshot of the four sources (one set and three of its cards, in
`tests/fixtures/pipeline`, cut from a full cache by `tests/fixtures/make_pipeline_fixture.py`) and validates the result. The two live checks run weekly and on demand in
`live-checks.yml`; a failure there means the data needs refreshing and does not block anything. A `v*` tag also checks
that it matches the version in `pyproject.toml`, builds the release files and attaches them to a GitHub release.

`refresh.yml` runs every Monday, and on demand. It downloads YGOPRODeck and TCGCSV again and takes YGOJSON's current
commit (`pipeline.py --refresh ygoprodeck --refresh tcgcsv --refresh ygojson`), updates the ban lists
(`legality.py`), runs `validate.py` and the ledger check against `main`, and opens or updates one pull request from the
branch `refresh/sources`. Its body (`tools/refresh_summary.py`) gives the ids added and retired per kind, the ban-list
events added and removed, the review counts and `sources.json` before and after. A failing step leaves its log and
pushes nothing; a refresh that changes nothing in `sets/`, `data/`, `ids/` or `legality/` opens no pull request.
`.cache` is kept between runs with `actions/cache`, so Yugipedia pages are fetched once. The pull request is opened with
`GITHUB_TOKEN`, which cannot start other workflows: the checks above run before the push, and CI runs on the pull
request once it is closed and reopened. The repository has to allow GitHub Actions to create pull requests (Settings >
Actions > General). Each
action is pinned to a commit SHA, with its release in a comment; Dependabot proposes new pins weekly.

## Licence

The tools and tests are MIT (`LICENSE`). The data and schemas are CC BY 4.0 (`LICENSE-DATA`). See `NOTICE` for what is
and is not copied from the sources. Yu-Gi-Oh! and its marks belong to Kazuki Takahashi/Shueisha and Konami. ygjson is
not affiliated with them, YGOPRODeck, Yugipedia or TCGplayer.
