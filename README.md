# cauldron-data

Card data for the Cauldron app, slimmed from [Scryfall](https://scryfall.com)'s
bulk files.

Scryfall publishes every Magic card as about 100MB of compressed JSON. The app
needs about 8MB of it. `build.py` reads Scryfall's Oracle Cards and Default Cards
files and writes one small file and a manifest, and a weekly Action publishes both
to the `data` release of this repository.

    python build.py --out dist     # downloads from Scryfall, then builds
    python -m unittest             # no network

Standard library only.

## What is in it

Every card that is not a token, emblem, plane, scheme, dungeon or sticker sheet,
including digital-only cards and Un-sets. A card with a face on each side
(transforming and modal double-faced cards) is two rows, one per side, because
each side is printed on its own. A card with two parts on one side (split,
adventure, flip) is one row with its parts listed.

## The file

`manifest.json` names the current data file and gives its SHA-256, its size and
its row counts. The data file is gzipped JSON Lines. The first line is
`{"format": 1}`. Each table then opens with `{"table": name, "rows": count}`
followed by exactly that many rows, so a file that stopped early can be told from
one that ended.

Rows refer to each other by position: `k` is a row number in `cards`, and the
numbers in `printings` are row numbers in `art`. Empty fields are left out.

**sets**: `c` code, `n` name, `ty` set type, `d` release date.

**cards**, one per printable face:

| key | |
|---|---|
| `o` | Scryfall oracle id |
| `f` | 1 for a back face; left out for a front |
| `n` `m` `t` `x` | name, mana cost, type line, rules text |
| `p` `h` `l` `d` | power, toughness, loyalty, defense |
| `parts` | for two parts on one side: each part's `n m t x p h l d` |
| `c` `ci` | colours and colour identity, as WUBRG letters |
| `mv` | mana value |
| `r` | EDHREC rank, lower is more played |
| `ra` | every rarity the card has been printed at, as letters: `c` common, `u` uncommon, `r` rare, `m` mythic, `s` special, `b` bonus |
| `y` | Scryfall layout |
| `meld` | on a meld half: the oracle id of what it melds into |

**art**, one per painting of each card:

| key | |
|---|---|
| `k` | row in `cards` |
| `i` | Scryfall id of the printing the picture is taken from |
| `il` | illustration id (the printing id where a card has none) |
| `a` `s` `cn` | artist, set code, collector number |
| `fl` | flavor text of that printing |
| `ub` | 1 for a Universes Beyond printing |
| `lo` | 1 for a low-resolution scan |
| `bk` | 1 when the picture is on the back of the printing |

The art crop is at
`https://cards.scryfall.io/art_crop/{front|back}/{i[0]}/{i[1]}/{i}.jpg`.

**printings**: `k` row in `cards`, and `s`, a map from set code to the rows in
`art` that set used for the card.

## Credit

Card data and images are from Scryfall. This is unofficial Fan Content permitted
under the Wizards of the Coast Fan Content Policy. The literal and graphical
information presented about Magic: The Gathering, including card text and card
images, is copyright Wizards of the Coast, LLC. Not approved or endorsed by
Wizards of the Coast or by Scryfall.
