#!/usr/bin/env python3
"""Builds the card file the Cauldron app carries, from Scryfall's bulk data.

Scryfall publishes every card as two files that matter here, about 100MB
compressed between them. A phone needs a few megabytes of that: the words on each
card, one row per picture, and which sets each card was printed in. This reads the
two and writes one small file plus a manifest describing it.

    python build.py --out dist

Standard library only, so there is nothing to install.

What the output looks like is in README.md. The rules for what counts as a card,
and why, are on the functions below.
"""

import argparse
import datetime
import gzip
import hashlib
import io
import json
import os
import sys
import urllib.request

#: Bumped when a reader of the old file could not read the new one.
FORMAT = 1

#: Scryfall refuses requests without a descriptive User-Agent.
USER_AGENT = "cauldron-data/1.0 (https://github.com/yeahdef/cauldron-data)"
BULK_INDEX = "https://api.scryfall.com/bulk-data"

#: One row per card, for the rules; one row per printing, for pictures and sets.
SOURCES = ("oracle_cards", "default_cards")

# What is NOT a card. The app keeps tokens, emblems, planes and schemes in their
# own places, and the rest of these are not game pieces at all.
NOT_CARD_LAYOUTS = {
    "token", "double_faced_token", "emblem", "art_series", "vanguard", "scheme", "planar",
}
#: Checked on the ORACLE row only. See [is_card] for why not on a printing.
NOT_CARD_SET_TYPES = {"memorabilia", "token", "minigame"}
#: Type lines that open with one of these are substitute cards, counters, dungeons
#: and sticker sheets, which the app already keeps with its tokens.
NOT_CARD_TYPES = ("Card", "Token", "Dungeon", "Stickers")

#: Layouts with a face on each side of the cardboard. Each side is its own print,
#: because the printers are one-sided. Everything else with faces (split,
#: adventure, flip, prepare) has both on ONE side and stays whole.
TWO_SIDED = {"transform", "modal_dfc"}

#: A picture Scryfall does not really have yet.
NO_PICTURE = {"placeholder", "missing"}

#: Promo type that marks a Universes Beyond printing, which the app can keep out of
#: random prints.
UNIVERSES_BEYOND = "universesbeyond"


class BuildError(Exception):
    """The output is not fit to publish."""


def is_card(card):
    """Whether an Oracle Cards row is a card the card index should hold.

    Deliberately NOT a question about `games`. The Oracle file keeps one printing
    per card and it is sometimes a digital one: Dance of the Dead comes through as
    its Magic Online printing, and filtering on paper would drop a card that has
    been in paper since 1995.
    """
    if card.get("layout") in NOT_CARD_LAYOUTS:
        return False
    if card.get("set_type") in NOT_CARD_SET_TYPES:
        return False
    first_type = (card.get("type_line") or "").split(" ")[0]
    return first_type not in NOT_CARD_TYPES


def _put(row, key, value):
    """Sets [key] unless there is nothing to say, which keeps rows short."""
    if value not in (None, "", [], 0, False):
        row[key] = value


def _words(source):
    """The fields a face, a part or a whole card all have."""
    row = {"n": source.get("name", "")}
    _put(row, "m", source.get("mana_cost"))
    _put(row, "t", source.get("type_line"))
    _put(row, "x", source.get("oracle_text"))
    # Kept as text and kept when "0": a 0/1 has a power and it is nought.
    for key, field in (("p", "power"), ("h", "toughness"), ("l", "loyalty"), ("d", "defense")):
        if source.get(field) is not None:
            row[key] = source[field]
    return row


def card_rows(card):
    """The printable things one Oracle row is: one, or one per side."""
    faces = card.get("card_faces") or []
    two_sided = card.get("layout") in TWO_SIDED and len(faces) > 1
    rows = []
    for index, source in enumerate(faces if two_sided else [card]):
        row = {"o": card["oracle_id"]}
        _put(row, "f", index)
        row.update(_words(source))
        if faces and not two_sided:
            # Two parts on one side. The whole card's name is "Fire // Ice" and it
            # has no rules text of its own: the parts do.
            row["parts"] = [_words(part) for part in faces]
        colors = source.get("colors", card.get("colors")) or []
        _put(row, "c", "".join(c for c in "WUBRG" if c in colors))
        identity = card.get("color_identity") or []
        _put(row, "ci", "".join(c for c in "WUBRG" if c in identity))
        mana_value = card.get("cmc")
        if mana_value:
            row["mv"] = int(mana_value) if float(mana_value).is_integer() else mana_value
        _put(row, "r", card.get("edhrec_rank"))
        row["y"] = card.get("layout", "")
        rows.append(row)
    return rows


def _meld_results(cards):
    """Name of each meld half -> name of what it melds into."""
    out = {}
    for card in cards:
        parts = card.get("all_parts") or []
        result = [p["name"] for p in parts if p.get("component") == "meld_result"]
        if len(result) != 1:
            continue
        for part in parts:
            if part.get("component") == "meld_part":
                out[part["name"]] = result[0]
    return out


def face_keys(printing):
    """Which card rows a printing shows, as (oracle id, face, side, source).

    A reversible card is two ordinary cards sharing a piece of cardboard, so each
    side is face 0 of its OWN oracle id. A transforming card is one oracle id with
    two faces. Anything else is one face, on the front.
    """
    faces = printing.get("card_faces") or []
    layout = printing.get("layout")
    if layout in TWO_SIDED and len(faces) > 1:
        return [(printing.get("oracle_id"), i, "back" if i else "front", f) for i, f in enumerate(faces)]
    if layout == "reversible_card" and faces:
        return [(f.get("oracle_id"), 0, "back" if i else "front", f) for i, f in enumerate(faces)]
    return [(printing.get("oracle_id"), 0, "front", printing)]


def _illustration(printing, source):
    if source.get("illustration_id"):
        return source["illustration_id"]
    if printing.get("illustration_id"):
        return printing["illustration_id"]
    faces = printing.get("card_faces") or []
    return faces[0].get("illustration_id") if faces else None


def _art_rank(printing):
    """Lower is the better row to keep when two printings show one picture.

    A good scan first, then one in English, then one on paper, then the oldest:
    the printing the painting was made for. The id last, so the choice is the same
    on every run.
    """
    return (
        printing.get("image_status") != "highres_scan",
        printing.get("lang") != "en",
        "paper" not in (printing.get("games") or []),
        printing.get("released_at") or "",
        printing["id"],
    )


def build(oracle_cards, default_cards):
    """The four tables, from the two sources. Each source is any iterable of dicts."""
    oracle_cards = [c for c in oracle_cards if is_card(c) and c.get("oracle_id")]
    # Sorted, so a build from unchanged data is byte for byte the same file and no
    # phone downloads it twice.
    oracle_cards.sort(key=lambda c: c["oracle_id"])

    cards = []
    index = {}
    for card in oracle_cards:
        for row in card_rows(card):
            index[(row["o"], row.get("f", 0))] = len(cards)
            cards.append(row)
    by_name = {row["n"]: row["o"] for row in cards if "f" not in row}
    for half, result in _meld_results(oracle_cards).items():
        for row in cards:
            if row["n"] == half and result in by_name and row["o"] != by_name[result]:
                row["meld"] = by_name[result]

    # One pass over EVERY printing, for two things.
    #
    # The pictures: one row per painting of each card. Scryfall has a Unique Artwork
    # file that sounds like this and is not. It keeps one printing per painting
    # across ALL cards, so where two cards share a painting (the six Unstable
    # variants of one card, a card and its Alchemy rebalancing) one of them is left
    # with no picture at all. Counted per card here instead.
    #
    # And the sets: which sets a card is in, and which of its pictures each used. A
    # reprint that reuses old art is still that set's printing, and half of all
    # card-and-set pairs are exactly that.
    best = {}
    sets = {}
    membership = {}
    for printing in default_cards:
        code = printing.get("set")
        if not code or printing.get("layout") == "art_series":
            continue
        seen = False
        for oracle, face, side, source in face_keys(printing):
            card = index.get((oracle, face))
            if card is None:
                continue
            seen = True
            # A playtest card has no illustration id. Its printing stands in, so the
            # picture still has a name the app can remember it by.
            picture = _illustration(printing, source) or printing["id"]
            membership.setdefault(card, {}).setdefault(code, set()).add(picture)
            if printing.get("image_status") in NO_PICTURE:
                continue
            row = {"k": card, "i": printing["id"], "il": picture}
            _put(row, "a", source.get("artist") or printing.get("artist"))
            _put(row, "s", code)
            _put(row, "cn", printing.get("collector_number"))
            _put(row, "fl", source.get("flavor_text") or printing.get("flavor_text"))
            _put(row, "ub", UNIVERSES_BEYOND in (printing.get("promo_types") or []))
            _put(row, "lo", printing.get("image_status") == "lowres")
            _put(row, "bk", side == "back")
            key = (card, picture)
            rank = _art_rank(printing)
            if key not in best or rank < best[key][0]:
                best[key] = (rank, row)
        if seen:
            known = sets.setdefault(code, {"c": code, "n": printing.get("set_name", code)})
            _put(known, "ty", printing.get("set_type"))
            released = printing.get("released_at")
            if released and released < known.get("d", "9999"):
                known["d"] = released
    art = [row for _, row in sorted(best.values(), key=lambda pair: (pair[1]["k"], pair[1]["i"], pair[1]["il"]))]
    art_index = {(row["k"], row["il"]): i for i, row in enumerate(art)}
    for card, by_set in membership.items():
        for code, pictures in by_set.items():
            by_set[code] = {art_index[(card, p)] for p in pictures if (card, p) in art_index}
    printings = [
        {"k": card, "s": {code: sorted(pictures) for code, pictures in sorted(by_set.items())}}
        for card, by_set in sorted(membership.items())
    ]
    return {
        "sets": sorted(sets.values(), key=lambda s: (s.get("d", ""), s["c"])),
        "cards": cards,
        "art": art,
        "printings": printings,
    }


# What a healthy build looks like. Scryfall grows; it does not shrink. A count
# under one of these is a failed download or a changed format, never fewer cards.
MINIMUM = {"cards": 34_000, "art": 49_000, "sets": 650, "printings": 34_000}

#: How far a count may fall from the last published build before it is refused.
MAX_DROP = 0.01

#: Cards that each stand for a trap this build has to get right.
CANARIES = (
    ("Lightning Bolt", 0),
    ("Dance of the Dead", 0),          # its Oracle printing is digital
    ("Fire // Ice", 0),                # two parts, one side
    ("Westvale Abbey", 0),
    ("Ormendahl, Profane Prince", 1),  # a back face is its own row
    ("Mountain", 0),
)


def check(tables, previous=None, minimum=None):
    """Raises [BuildError] if [tables] should not be published."""
    minimum = MINIMUM if minimum is None else minimum
    problems = []
    for table, least in minimum.items():
        if len(tables[table]) < least:
            problems.append(f"{table}: {len(tables[table])} rows, expected at least {least}")
    for table, before in ((previous or {}).get("counts") or {}).items():
        now = len(tables.get(table, []))
        if now < before * (1 - MAX_DROP):
            problems.append(f"{table}: fell from {before} to {now}")

    cards = tables["cards"]
    keys = [(row["o"], row.get("f", 0)) for row in cards]
    if len(keys) != len(set(keys)):
        problems.append("a card face appears twice")
    if minimum:
        named = {(row["n"], row.get("f", 0)) for row in cards}
        for canary in CANARIES:
            if canary not in named:
                problems.append(f"missing {canary[0]} (face {canary[1]})")
        pictured = {row["k"] for row in tables["art"]}
        bare = len(cards) - len(pictured)
        if bare > len(cards) * 0.005:
            problems.append(f"{bare} cards have no picture at all")
    if problems:
        raise BuildError("; ".join(problems))


def write(tables, out_dir, sources=None, now=None):
    """Writes the data file and its manifest into [out_dir]. Returns the manifest."""
    os.makedirs(out_dir, exist_ok=True)
    buffer = io.BytesIO()
    # mtime pinned, or the same rows would hash differently every run.
    with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=9, mtime=0) as gz:
        def line(value):
            gz.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            gz.write(b"\n")

        line({"format": FORMAT})
        for table in ("sets", "cards", "art", "printings"):
            # The count comes BEFORE the rows, so a reader can tell a file that
            # stopped early from one that ended.
            line({"table": table, "rows": len(tables[table])})
            for row in tables[table]:
                line(row)
    data = buffer.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    # The hash is in the name, so a manifest can never point at a file that has
    # since been replaced under it.
    name = f"cauldron-cards-{digest[:12]}.jsonl.gz"
    with open(os.path.join(out_dir, name), "wb") as f:
        f.write(data)
    manifest = {
        "format": FORMAT,
        "file": name,
        "sha256": digest,
        "size": len(data),
        "counts": {table: len(rows) for table, rows in tables.items()},
        "built_at": (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scryfall": sources or {},
    }
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    return manifest


def read_jsonl(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for text in f:
            if text.strip():
                yield json.loads(text)


def _get(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    return urllib.request.urlopen(request, timeout=120)


def download(cache_dir):
    """Fetches today's bulk files into [cache_dir]. Returns paths and timestamps."""
    os.makedirs(cache_dir, exist_ok=True)
    with _get(BULK_INDEX) as response:
        listed = {entry["type"]: entry for entry in json.load(response)["data"]}
    paths, stamps = {}, {}
    for source in SOURCES:
        entry = listed[source]
        url = entry["jsonl_download_uri"]
        path = os.path.join(cache_dir, url.rsplit("/", 1)[1])
        if not os.path.exists(path):
            print(f"downloading {source}", file=sys.stderr)
            with _get(url) as response, open(path + ".part", "wb") as f:
                while chunk := response.read(1 << 20):
                    f.write(chunk)
            os.replace(path + ".part", path)
        paths[source] = path
        stamps[source] = entry["updated_at"]
    return paths, stamps


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="dist")
    parser.add_argument("--cache", default=".cache", help="where downloaded bulk files are kept")
    parser.add_argument("--previous", help="the last published manifest.json, to compare counts against")
    for source in SOURCES:
        parser.add_argument(f"--{source.replace('_', '-')}", help="a local .jsonl.gz to use instead of downloading")
    args = parser.parse_args(argv)

    local = {source: getattr(args, source) for source in SOURCES}
    if all(local.values()):
        paths, stamps = local, {}
    elif any(local.values()):
        parser.error("give both local files or neither")
    else:
        paths, stamps = download(args.cache)

    previous = None
    if args.previous and os.path.exists(args.previous):
        with open(args.previous, encoding="utf-8") as f:
            previous = json.load(f)

    tables = build(*(read_jsonl(paths[source]) for source in SOURCES))
    try:
        check(tables, previous)
    except BuildError as error:
        print(f"refusing to publish: {error}", file=sys.stderr)
        return 1
    manifest = write(tables, args.out, stamps)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
