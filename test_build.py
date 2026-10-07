"""The rules build.py applies, each against the smallest card that needs it.

No network and no real data: every card here is written out by hand, with only the
fields the rule under test reads. The numbers a real build produces are checked by
the guards in `check`, which run on every build.
"""

import gzip
import json
import os
import tempfile
import unittest

import build


def card(name, oracle=None, **more):
    oracle = oracle or "o-" + name
    base = {
        "id": "p-" + name, "oracle_id": oracle, "name": name, "layout": "normal",
        "type_line": "Instant", "oracle_text": "Do a thing.", "mana_cost": "{R}", "cmc": 1.0,
        "colors": ["R"], "color_identity": ["R"], "set": "lea", "set_name": "Alpha",
        "set_type": "core", "released_at": "1993-08-05", "lang": "en", "games": ["paper"],
        "image_status": "highres_scan", "illustration_id": "ill-" + name, "artist": "Somebody",
        "collector_number": "1",
    }
    base.update(more)
    return base


def bolt(**more):
    return card("Lightning Bolt", "o-bolt", **more)


def abbey(**more):
    """A land on the front and a creature on the back."""
    base = card(
        "Westvale Abbey // Ormendahl, Profane Prince", "o-abbey", layout="transform",
        type_line="Land // Legendary Creature", cmc=0.0, colors=None, color_identity=["B"],
        card_faces=[
            {"name": "Westvale Abbey", "type_line": "Land", "oracle_text": "{T}: Add {C}.",
             "mana_cost": "", "colors": [], "illustration_id": "ill-abbey", "artist": "Front Painter"},
            {"name": "Ormendahl, Profane Prince", "type_line": "Legendary Creature",
             "oracle_text": "Flying", "mana_cost": "", "colors": ["B"], "power": "9", "toughness": "7",
             "illustration_id": "ill-ormendahl", "artist": "Back Painter"},
        ],
    )
    del base["illustration_id"]
    base.update(more)
    return base


def fire_ice(**more):
    base = card(
        "Fire // Ice", "o-fire", layout="split", mana_cost="{1}{R} // {1}{U}",
        type_line="Instant // Instant", colors=["R", "U"], color_identity=["R", "U"], cmc=4.0,
        card_faces=[
            {"name": "Fire", "mana_cost": "{1}{R}", "type_line": "Instant", "oracle_text": "Two damage."},
            {"name": "Ice", "mana_cost": "{1}{U}", "type_line": "Instant", "oracle_text": "Tap. Draw."},
        ],
    )
    del base["oracle_text"]
    base.update(more)
    return base


def tables(oracle, printings=None):
    return build.build(oracle, oracle if printings is None else printings)


class WhatIsACard(unittest.TestCase):

    def test_tokens_planes_and_the_rest_are_left_out(self):
        kept = tables([
            bolt(),
            card("Goblin", "o-goblin", layout="token", type_line="Token Creature"),
            card("Naar Isle", "o-naar", layout="planar", type_line="Plane"),
            card("All in Good Time", "o-scheme", layout="scheme", type_line="Scheme"),
            card("Art", "o-art", layout="art_series", type_line="Card"),
            card("Undercity", "o-dungeon", set_type="token", type_line="Dungeon"),
            card("The Harvester", "o-hero", set_type="memorabilia", type_line="Hero"),
            card("Sticker Sheet", "o-sticker", type_line="Stickers"),
        ])["cards"]
        self.assertEqual(["Lightning Bolt"], [row["n"] for row in kept])

    def test_a_card_whose_oracle_printing_is_digital_is_still_a_card(self):
        # Dance of the Dead. The Oracle file hands over its Magic Online printing,
        # and a filter on paper would drop a card printed in 1995.
        kept = tables([card("Dance of the Dead", "o-dance", games=["mtgo"], set="me2")])["cards"]
        self.assertEqual(["Dance of the Dead"], [row["n"] for row in kept])

    def test_digital_only_and_un_set_cards_are_in(self):
        kept = tables([
            card("Alchemy Thing", "o-alc", games=["arena"], set_type="alchemy"),
            card("Silver Thing", "o-fun", set_type="funny"),
        ])["cards"]
        self.assertEqual(2, len(kept))


class Faces(unittest.TestCase):

    def test_each_side_of_a_two_sided_card_is_its_own_row(self):
        front, back = tables([abbey()])["cards"]
        self.assertEqual(("Westvale Abbey", None), (front["n"], front.get("f")))
        self.assertEqual(("Ormendahl, Profane Prince", 1), (back["n"], back.get("f")))
        self.assertEqual(front["o"], back["o"])
        # Each side's own words, not the whole card's.
        self.assertEqual("Flying", back["x"])
        self.assertEqual(("9", "7"), (back["p"], back["h"]))
        self.assertEqual("B", back["c"])
        self.assertNotIn("c", front)

    def test_two_parts_on_one_side_stay_one_row(self):
        (row,) = tables([fire_ice()])["cards"]
        self.assertEqual("Fire // Ice", row["n"])
        self.assertNotIn("f", row)
        self.assertNotIn("x", row)
        self.assertEqual(["Fire", "Ice"], [part["n"] for part in row["parts"]])
        self.assertEqual("{1}{U}", row["parts"][1]["m"])

    def test_a_power_of_nought_is_kept(self):
        (row,) = tables([card("Wall", "o-wall", power="0", toughness="4")])["cards"]
        self.assertEqual(("0", "4"), (row["p"], row["h"]))

    def test_mana_value_is_a_whole_number_where_it_is_one(self):
        whole, half = tables([bolt(), card("Little Girl", "o-girl", cmc=0.5)])["cards"]
        self.assertEqual(1, half["mv"] * 2)
        self.assertIsInstance(whole["mv"], int)

    def test_a_meld_half_points_at_what_it_becomes(self):
        parts = [
            {"component": "meld_part", "name": "Gisela"},
            {"component": "meld_part", "name": "Bruna"},
            {"component": "meld_result", "name": "Brisela"},
        ]
        rows = tables([
            card("Gisela", "o-gisela", layout="meld", all_parts=parts),
            card("Bruna", "o-bruna", layout="meld", all_parts=parts),
            card("Brisela", "o-brisela", layout="meld", all_parts=parts),
        ])["cards"]
        melds = {row["n"]: row.get("meld") for row in rows}
        self.assertEqual({"Gisela": "o-brisela", "Bruna": "o-brisela", "Brisela": None}, melds)


class Pictures(unittest.TestCase):

    def test_one_row_per_painting_not_per_printing(self):
        built = tables([bolt()], [
            bolt(id="p-alpha"),
            bolt(id="p-beta", set="leb", set_name="Beta"),            # same painting again
            bolt(id="p-m10", set="m10", set_name="2010", illustration_id="ill-new"),
        ])
        self.assertEqual(["ill-Lightning Bolt", "ill-new"], sorted(row["il"] for row in built["art"]))

    def test_the_better_scan_is_the_one_kept(self):
        built = tables([bolt()], [
            bolt(id="p-blurry", image_status="lowres"),
            bolt(id="p-sharp", set="leb"),
        ])
        self.assertEqual(["p-sharp"], [row["i"] for row in built["art"]])

    def test_a_placeholder_is_not_a_picture_but_is_still_a_printing(self):
        built = tables([bolt()], [
            bolt(id="p-real"),
            bolt(id="p-soon", set="new", set_name="Next Set", image_status="placeholder", illustration_id="ill-soon"),
        ])
        self.assertEqual(["p-real"], [row["i"] for row in built["art"]])
        self.assertEqual({"lea": [0], "new": []}, built["printings"][0]["s"])

    def test_each_side_gets_its_own_painting_and_knows_its_side(self):
        built = tables([abbey()])
        by_card = {row["k"]: row for row in built["art"]}
        self.assertEqual(("ill-abbey", "Front Painter", None), (by_card[0]["il"], by_card[0]["a"], by_card[0].get("bk")))
        self.assertEqual(("ill-ormendahl", "Back Painter", True), (by_card[1]["il"], by_card[1]["a"], by_card[1].get("bk")))

    def test_two_cards_sharing_a_painting_both_keep_it(self):
        # What Scryfall's Unique Artwork file gets wrong for this purpose: it keeps
        # one card per painting, and the other is left with nothing to print.
        built = tables([
            card("Everythingamajig", "o-a", illustration_id="ill-shared"),
            card("Everythingamajig", "o-b", id="p-b", illustration_id="ill-shared"),
        ])
        self.assertEqual([0, 1], [row["k"] for row in built["art"]])

    def test_a_card_with_no_illustration_id_is_pictured_by_its_printing(self):
        playtest = card("Playtest", "o-play", id="p-play")
        del playtest["illustration_id"]
        (row,) = tables([playtest])["art"]
        self.assertEqual("p-play", row["il"])

    def test_a_reversible_card_is_two_ordinary_cards(self):
        reversible = {
            "id": "p-rev", "layout": "reversible_card", "set": "sld", "set_name": "Secret Lair",
            "image_status": "highres_scan", "lang": "en", "games": ["paper"],
            "card_faces": [
                {"oracle_id": "o-bolt", "name": "Lightning Bolt", "illustration_id": "ill-side-a"},
                {"oracle_id": "o-bolt", "name": "Lightning Bolt", "illustration_id": "ill-side-b"},
            ],
        }
        built = tables([bolt()], [reversible])
        self.assertEqual([(0, None), (0, True)], [(row["k"], row.get("bk")) for row in built["art"]])

    def test_universes_beyond_and_flavor_come_along(self):
        (row,) = tables([bolt(promo_types=["universesbeyond"], flavor_text="Zap.")])["art"]
        self.assertEqual((True, "Zap."), (row["ub"], row["fl"]))


class Sets(unittest.TestCase):

    def test_a_reprint_with_old_art_is_still_in_its_set(self):
        built = tables([bolt()], [
            bolt(id="p-alpha"),
            bolt(id="p-m10", set="m10", set_name="Magic 2010", set_type="core", released_at="2009-07-17"),
        ])
        # Both sets, pointing at the one painting they share.
        self.assertEqual({"lea": [0], "m10": [0]}, built["printings"][0]["s"])
        self.assertEqual(["lea", "m10"], [s["c"] for s in built["sets"]])

    def test_a_set_with_no_cards_in_the_index_is_not_listed(self):
        built = tables([bolt()], [bolt(), card("Goblin", "o-goblin", layout="token", set="tm10")])
        self.assertEqual(["lea"], [s["c"] for s in built["sets"]])


class Rarity(unittest.TestCase):

    def test_a_card_carries_every_rarity_it_has_been_printed_at(self):
        built = tables([bolt()], [
            bolt(id="p-alpha", rarity="common"),
            bolt(id="p-jud", set="jud", set_name="Judge", rarity="rare"),
            bolt(id="p-m10", set="m10", set_name="2010", rarity="common"),
        ])
        # Commonest first, each once, whatever order the printings came in.
        self.assertEqual("cr", built["cards"][0]["ra"])

    def test_both_sides_of_a_card_have_its_rarity(self):
        front, back = tables([abbey()], [abbey(rarity="rare")])["cards"]
        self.assertEqual(("r", "r"), (front["ra"], back["ra"]))

    def test_a_printing_with_no_rarity_adds_nothing(self):
        (row,) = tables([bolt()])["cards"]
        self.assertNotIn("ra", row)

    def test_a_painting_carries_the_rarities_it_was_printed_at(self):
        built = tables([bolt()], [
            bolt(id="p-alpha", rarity="common"),
            bolt(id="p-beta", set="leb", rarity="uncommon"),                      # the same painting again
            bolt(id="p-jud", set="jud", rarity="rare", illustration_id="ill-judge"),
        ])
        by_painting = {row["il"]: row.get("ra") for row in built["art"]}
        # Each painting its own, and the card all of them.
        self.assertEqual({"ill-Lightning Bolt": "cu", "ill-judge": "r"}, by_painting)
        self.assertEqual("cur", built["cards"][0]["ra"])

    def test_a_painting_names_the_printing_it_has_at_each_other_rarity(self):
        # Command Tower's first painting: a common in the set it came out in, a
        # common again and again, and a rare once, as a promo.
        built = tables([bolt()], [
            bolt(id="p-first", rarity="common", released_at="2011-06-17", collector_number="269"),
            bolt(id="p-promo", set="j12", rarity="rare", released_at="2012-01-01", collector_number="8"),
            bolt(id="p-again", set="c13", rarity="common", released_at="2013-11-01", collector_number="281"),
        ])
        (row,) = built["art"]
        # It IS its earliest printing, which is a common.
        self.assertEqual(("p-first", "c"), (row["i"], row["r1"]))
        self.assertEqual("cr", row["ra"])
        # And as a rare it is the promo: its id, its set, its number.
        self.assertEqual({"r": ["p-promo", "j12", "8"]}, row["rp"])

    def test_a_painting_only_ever_one_rarity_names_no_others(self):
        (row,) = tables([bolt(rarity="uncommon")])["art"]
        self.assertEqual(("u", "u"), (row["ra"], row["r1"]))
        self.assertNotIn("rp", row)

    def test_a_printing_with_no_picture_yet_is_not_one_to_show_a_painting_as(self):
        built = tables([bolt()], [
            bolt(id="p-real", rarity="common"),
            bolt(id="p-soon", set="new", rarity="mythic", image_status="placeholder"),
        ])
        (row,) = built["art"]
        self.assertEqual("c", row["ra"])
        self.assertNotIn("rp", row)
        # The CARD has still been a mythic: it is in that set at that rarity.
        self.assertEqual("cm", built["cards"][0]["ra"])

    def test_the_odd_rarities_are_kept_too(self):
        built = tables([bolt()], [bolt(id="p-a", rarity="mythic"), bolt(id="p-b", set="x", rarity="special"), bolt(id="p-c", set="y", rarity="bonus")])
        self.assertEqual("msb", built["cards"][0]["ra"])


class Price(unittest.TestCase):

    def test_a_card_costs_what_its_cheapest_printing_costs(self):
        built = tables([bolt()], [
            bolt(id="p-alpha", prices={"usd": "450.00", "usd_foil": None}),
            bolt(id="p-m10", set="m10", prices={"usd": "1.25", "usd_foil": "9.00"}),
            bolt(id="p-judge", set="jud", prices={"usd": None, "usd_foil": "80.00"}),
        ])
        self.assertEqual(1.25, built["cards"][0]["pr"])

    def test_a_foil_only_printing_still_has_a_price(self):
        (row,) = tables([bolt(prices={"usd": None, "usd_foil": "12.50", "usd_etched": "20.00"})])["cards"]
        self.assertEqual(12.5, row["pr"])

    def test_a_card_nobody_sells_has_no_price(self):
        for prices in ({}, None, {"usd": None, "eur": "3.00", "tix": "0.02"}, {"usd": "not a number"}):
            (row,) = tables([bolt(prices=prices)])["cards"]
            self.assertNotIn("pr", row, prices)

    def test_both_sides_of_a_card_cost_the_same(self):
        front, back = tables([abbey()], [abbey(prices={"usd": "4.00"})])["cards"]
        self.assertEqual((4.0, 4.0), (front["pr"], back["pr"]))


class Folders(unittest.TestCase):

    LISTED = [
        {"code": "fin", "parent_set_code": None},
        {"code": "fic", "parent_set_code": "fin"},
        {"code": "pfin", "parent_set_code": "fin"},
        {"code": "afic", "parent_set_code": "fic"},   # a scene box, filed under the commander set
        {"code": "tfin", "parent_set_code": "fin"},   # tokens: no cards of ours in it
        {"code": "lea", "parent_set_code": None},
    ]

    def filed(self, *codes, listed=None):
        printings = [bolt(id="p-" + code, set=code, set_name=code.upper()) for code in codes]
        built = build.build([bolt()], printings, self.LISTED if listed is None else listed)
        return {row["c"]: row.get("p") for row in built["sets"]}

    def test_a_set_is_filed_under_the_release_it_came_with(self):
        self.assertEqual({"fin": None, "fic": "fin", "pfin": "fin", "lea": None}, self.filed("fin", "fic", "pfin", "lea"))

    def test_the_folder_is_the_top_of_the_chain_not_the_next_link(self):
        # The scene box belongs to the commander set, which belongs to the main set.
        self.assertEqual("fin", self.filed("fin", "fic", "afic")["afic"])

    def test_a_set_is_never_filed_under_one_that_is_not_in_the_list(self):
        # No card of the main set, so nothing to open: the commander set stands alone,
        # and the scene box goes under it, the highest ancestor that is there.
        self.assertEqual({"fic": None, "afic": "fic"}, self.filed("fic", "afic"))

    def test_without_the_list_of_sets_nothing_is_filed(self):
        self.assertEqual({"fin": None, "fic": None}, self.filed("fin", "fic", listed=[]))

    def test_sets_that_name_each_other_do_not_hang_the_build(self):
        loop = [{"code": "aaa", "parent_set_code": "bbb"}, {"code": "bbb", "parent_set_code": "aaa"}]
        self.assertEqual({"aaa": "bbb", "bbb": "aaa"}, self.filed("aaa", "bbb", listed=loop))


def booster(code="lea", set_code="lea", **more):
    base = {
        "name": "Alpha", "code": code, "set_code": set_code,
        "boosters": [{"weight": 1, "sheets": {"common": 1}}],
        "sheets": {"common": {"total_weight": 1, "cards": {"lea:1": 1}}},
    }
    base.update(more)
    return base


class Packs(unittest.TestCase):

    def setUp(self):
        # These are packs of one card, to say one thing each. The floor has its own test.
        self.floor = build.MIN_PACK_CARDS
        build.MIN_PACK_CARDS = 1

    def tearDown(self):
        build.MIN_PACK_CARDS = self.floor

    def packs(self, boosters, printings=None):
        return build.build([bolt()], printings or [bolt(rarity="common")], boosters=boosters)["packs"]

    def test_a_box_of_a_few_cards_is_not_a_pack(self):
        build.MIN_PACK_CARDS = 3
        cards = [card(f"Card {n}", collector_number=str(n), rarity="common") for n in range(1, 4)]
        sheet = {"common": {"cards": {"lea:1": 1, "lea:2": 1, "lea:3": 1}}}
        self.assertEqual(1, len(build.build(cards, cards, boosters=[booster(sheets=sheet)])["packs"]))
        # The same card three ways is one card.
        sheet = {"common": {"cards": {"lea:1": 1, "lea:1:foil": 1, "lea:2": 1}}}
        self.assertEqual([], build.build(cards, cards, boosters=[booster(sheets=sheet)])["packs"])

    def test_a_sheet_names_its_cards_by_where_they_are_in_this_file(self):
        (pack,) = self.packs([booster()])
        self.assertEqual("lea", pack["s"])
        self.assertEqual([[0, 0, "p-Lightning Bolt", "lea", "1", "c"]], pack["p"])
        self.assertEqual({"common": {"c": [0, 1]}}, pack["sh"])
        self.assertEqual([[1, {"common": 1}]], pack["v"])
        self.assertEqual(1, pack["z"])

    def test_a_foil_is_the_same_card(self):
        sheet = {"common": {"cards": {"lea:1": 3, "lea:1:foil": 1}}}
        (pack,) = self.packs([booster(sheets=sheet)])
        self.assertEqual([0, 4], pack["sh"]["common"]["c"])

    def test_the_play_booster_is_the_one_drafted_then_the_draft_booster(self):
        named = [booster("lea-collector", name="C"), booster("lea-draft", name="D"), booster("lea-play", name="P")]
        self.assertEqual("P", self.packs(named)[0]["n"])
        self.assertEqual("D", self.packs(named[:2])[0]["n"])
        # A collector booster is nobody's draft pack, and is a pack of its own kind.
        self.assertEqual(["collector"], [p.get("k") for p in self.packs(named[:1])])

    def test_a_sets_other_boosters_are_packs_of_their_own(self):
        named = [
            booster("lea-draft", name="D"), booster("lea-collector", name="C"), booster("lea-set", name="S"),
            booster("lea-jumpstart", name="J"), booster("lea-collector-sample", name="no"), booster("lea-theme-w", name="no"),
        ]
        packs = self.packs(named)
        self.assertEqual([("D", None), ("S", "set"), ("C", "collector"), ("J", "jumpstart")], [(p["n"], p.get("k")) for p in packs])
        # A set sold only as Jumpstart packs has that pack and no draft one.
        self.assertEqual([("J", "jumpstart")], [(p["n"], p.get("k")) for p in self.packs(named[3:4])])

    def test_a_sheet_of_nothing_this_file_carries_is_left_out_of_the_pack(self):
        made = booster(
            boosters=[{"weight": 1, "sheets": {"common": 1, "token": 1}}],
            sheets={"common": {"cards": {"lea:1": 1}}, "token": {"cards": {"tlea:9": 1}}},
        )
        (pack,) = self.packs([made])
        self.assertEqual([[1, {"common": 1}]], pack["v"])
        self.assertNotIn("token", pack["sh"])

    def test_a_pack_asks_for_no_more_of_a_sheet_than_it_has(self):
        (pack,) = self.packs([booster(boosters=[{"weight": 1, "sheets": {"common": 10}}])])
        self.assertEqual([[1, {"common": 1}]], pack["v"])

    def test_make_ups_that_come_to_the_same_thing_are_one(self):
        made = booster(boosters=[
            {"weight": 3, "sheets": {"common": 1}},
            {"weight": 1, "sheets": {"common": 1, "token": 1}},
        ])
        (pack,) = self.packs([made])
        self.assertEqual([[4, {"common": 1}]], pack["v"])

    def test_a_two_part_card_is_found_under_the_number_scryfall_gives_it(self):
        sheet = {"common": {"cards": {"lea:1a": 1}}}
        (pack,) = self.packs([booster(sheets=sheet)])
        self.assertEqual("1", pack["p"][0][4])

    def test_a_two_sided_card_brings_its_other_side(self):
        built = build.build([abbey()], [abbey(rarity="rare")], boosters=[booster()])
        (entry,) = built["packs"][0]["p"]
        self.assertEqual([0, 0], entry[:2])
        self.assertEqual([1, 1], entry[6:])

    def test_a_balanced_sheet_says_so(self):
        sheet = {"common": {"balance_colors": True, "cards": {"lea:1": 1}}}
        self.assertEqual(1, self.packs([booster(sheets=sheet)])[0]["sh"]["common"]["b"])

    def test_no_boosters_is_no_packs_and_still_a_build(self):
        self.assertEqual([], self.packs([]))


class Guards(unittest.TestCase):

    def small(self):
        return tables([bolt(), abbey(), fire_ice()])

    def test_a_small_healthy_build_passes_with_the_floors_off(self):
        build.check(self.small(), minimum={})

    def test_a_real_build_must_reach_the_floors(self):
        with self.assertRaisesRegex(build.BuildError, "cards: 4 rows"):
            build.check(self.small())

    def test_a_count_that_fell_is_refused(self):
        with self.assertRaisesRegex(build.BuildError, "cards: fell from 5000 to 4"):
            build.check(self.small(), previous={"counts": {"cards": 5000}}, minimum={})

    def test_a_count_that_grew_is_fine(self):
        build.check(self.small(), previous={"counts": {"cards": 3, "art": 1}}, minimum={})

    def test_the_same_face_twice_is_refused(self):
        twice = self.small()
        twice["cards"].append(dict(twice["cards"][0]))
        with self.assertRaisesRegex(build.BuildError, "appears twice"):
            build.check(twice, minimum={})


class TheFile(unittest.TestCase):

    def read(self, folder, manifest):
        with gzip.open(os.path.join(folder, manifest["file"]), "rt", encoding="utf-8") as f:
            return [json.loads(text) for text in f]

    def test_every_table_says_how_long_it_is_before_it_starts(self):
        built = tables([bolt(), abbey()])
        with tempfile.TemporaryDirectory() as folder:
            manifest = build.write(built, folder)
            lines = self.read(folder, manifest)
        self.assertEqual({"format": build.FORMAT}, lines[0])
        at = 1
        for table in ("sets", "cards", "art", "printings", "packs", "oversized", "oversized_art", "tokens"):
            self.assertEqual({"table": table, "rows": len(built[table])}, lines[at])
            self.assertEqual(built[table], lines[at + 1:at + 1 + len(built[table])])
            at += 1 + len(built[table])
        self.assertEqual(len(lines), at)
        self.assertEqual(manifest["counts"], {name: len(rows) for name, rows in built.items()})

    def test_the_same_data_is_the_same_file(self):
        # Or every phone would download it again each week for nothing. The input
        # order is reversed between the two, which Scryfall is free to do.
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = build.write(tables([bolt(), abbey(), fire_ice()]), a)
            second = build.write(tables([fire_ice(), abbey(), bolt()]), b)
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(first["file"], second["file"])

    def test_the_manifest_describes_the_file_it_names(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            manifest = build.write(tables([bolt()]), folder)
            with open(os.path.join(folder, manifest["file"]), "rb") as f:
                data = f.read()
            with open(os.path.join(folder, "manifest.json"), encoding="utf-8") as f:
                self.assertEqual(manifest, json.load(f))
        self.assertEqual(hashlib.sha256(data).hexdigest(), manifest["sha256"])
        self.assertEqual(len(data), manifest["size"])
        self.assertIn(manifest["sha256"][:12], manifest["file"])


class OversizedAndMomir(unittest.TestCase):
    def plane(self, name="Akoum", **more):
        base = card(name, layout="planar", type_line="Plane \u2014 Zendikar", oracle_text="Chaos ensues.", set="hop", set_type="planechase")
        base.update(more)
        return base

    def test_a_plane_is_not_a_card_and_is_kept_in_a_table_of_its_own(self):
        tables = build.build([bolt(), self.plane()], [bolt(), self.plane()])
        self.assertEqual(["Lightning Bolt"], [row["n"] for row in tables["cards"]])
        self.assertEqual([{"o": "o-Akoum", "n": "Akoum", "t": "Plane \u2014 Zendikar", "x": "Chaos ensues.", "y": "planar"}], tables["oversized"])
        self.assertEqual([{"k": 0, "i": "p-Akoum", "il": "ill-Akoum", "a": "Somebody", "s": "hop", "cn": "1"}], tables["oversized_art"])

    def test_a_scheme_is_kept_too_and_each_painting_of_it_once(self):
        first = card("All Shall Smolder", layout="scheme", type_line="Scheme", set="arc")
        again = dict(first, id="p-reprint", set="e01")
        repainted = dict(first, id="p-new", illustration_id="ill-new", set="dsc")
        tables = build.build([], [first, again, repainted])
        self.assertEqual(1, len(tables["oversized"]))
        self.assertEqual("scheme", tables["oversized"][0]["y"])
        self.assertEqual(["ill-All Shall Smolder", "ill-new"], sorted(row["il"] for row in tables["oversized_art"]))

    def test_a_plane_nobody_printed_or_not_in_english_is_left_out(self):
        digital = self.plane("Arena Only", games=["arena"])
        french = self.plane("Akoum Fr", lang="fr")
        tables = build.build([], [digital, french])
        self.assertEqual([], tables["oversized"])
        self.assertEqual([], tables["oversized_art"])

    def test_a_card_never_printed_on_paper_says_so(self):
        alchemy = card("A-Thing", games=["arena"], set_type="alchemy")
        tables = build.build([bolt(), alchemy], [bolt(), alchemy])
        by_name = {row["n"]: row for row in tables["cards"]}
        self.assertTrue(by_name["A-Thing"]["dg"])
        self.assertNotIn("dg", by_name["Lightning Bolt"])

    def test_a_card_printed_digitally_and_on_paper_is_a_paper_card(self):
        online = bolt(id="p-mtgo", games=["mtgo"], set="me1")
        tables = build.build([online], [online, bolt()])
        self.assertNotIn("dg", tables["cards"][0])

    def test_a_joke_card_says_so_and_a_real_card_from_a_joke_set_does_not(self):
        legal = {"vintage": "legal", "standard": "not_legal"}
        nowhere = {"vintage": "not_legal", "standard": "not_legal"}
        joke = card("Cheatyface", set="unh", set_type="funny", legalities=nowhere)
        real = card("Saw in Half", set="unf", set_type="funny", legalities=legal)
        plain = bolt(legalities=legal)
        tables = build.build([joke, real, plain], [joke, real, plain])
        by_name = {row["n"]: row for row in tables["cards"]}
        self.assertTrue(by_name["Cheatyface"]["fu"])
        self.assertNotIn("fu", by_name["Saw in Half"])
        self.assertNotIn("fu", by_name["Lightning Bolt"])

    def test_the_oversized_tables_are_written_after_the_rest(self):
        tables = build.build([bolt(), self.plane()], [bolt(), self.plane()])
        with tempfile.TemporaryDirectory() as out:
            manifest = build.write(tables, out)
            with gzip.open(os.path.join(out, manifest["file"]), "rt", encoding="utf-8") as f:
                headers = [json.loads(line)["table"] for line in f if line.startswith('{"table"')]
        self.assertEqual(["sets", "cards", "art", "printings", "packs", "oversized", "oversized_art", "tokens"], headers)
        self.assertEqual(1, manifest["counts"]["oversized"])


class Tokens(unittest.TestCase):
    def token(self, name="Goblin", **more):
        base = card(
            name, layout="token", type_line="Token Creature \u2014 Goblin", oracle_text="", set="tm21", set_type="token",
            power="1", toughness="1", keywords=["Haste"],
            image_uris={"png": "p.png", "large": "l.jpg", "normal": "n.jpg", "art_crop": "a.jpg", "small": "s.jpg"},
        )
        base.update(more)
        return base

    def names(self, *printings):
        return [row["name"] for row in build.build([], list(printings))["tokens"]]

    def test_a_token_is_kept_as_scryfall_gives_it_less_what_is_not_read(self):
        row = build.build([], [self.token()])["tokens"][0]
        self.assertEqual("p-Goblin", row["id"])
        self.assertEqual("o-Goblin", row["oracle_id"])
        self.assertEqual("Token Creature \u2014 Goblin", row["type_line"])
        self.assertEqual(["Haste"], row["keywords"])
        self.assertEqual({"png": "p.png", "large": "l.jpg", "normal": "n.jpg", "art_crop": "a.jpg"}, row["image_uris"])
        self.assertNotIn("set", row)
        self.assertNotIn("mana_cost", row)

    def test_a_power_of_nought_is_a_power(self):
        row = build.build([], [self.token("Wall", power="0", toughness="3")])["tokens"][0]
        self.assertEqual("0", row["power"])

    def test_a_token_is_not_a_card(self):
        tables = build.build([self.token()], [self.token()])
        self.assertEqual([], tables["cards"])

    def test_one_row_for_each_picture_and_the_oldest_printing_of_it(self):
        first = self.token(released_at="2013-09-27", id="p-old")
        again = self.token(released_at="2018-12-07", id="p-new")
        repainted = self.token(id="p-other", illustration_id="ill-other")
        rows = build.build([], [again, first, repainted])["tokens"]
        self.assertEqual(["p-old", "p-other"], sorted(row["id"] for row in rows))

    def test_a_picture_is_one_row_whatever_it_is_a_picture_of_and_it_is_the_older(self):
        germ = self.token("Germ", illustration_id="ill-shared", released_at="2011-02-04")
        other = self.token("Phyrexian Germ", id="p-other", illustration_id="ill-shared", released_at="2023-02-03")
        self.assertEqual(["Germ"], self.names(other, germ))

    def test_of_two_printings_in_one_set_it_is_the_lower_number(self):
        low = self.token(id="p-zzz", collector_number="4")
        high = self.token(id="p-aaa", collector_number="26")
        self.assertEqual(["p-zzz"], [row["id"] for row in build.build([], [high, low])["tokens"]])

    def test_the_games_on_a_booster_insert_are_not_tokens(self):
        game = self.token("Booster Blitz", type_line="Card", set_type="minigame", illustration_id=None)
        self.assertEqual([], self.names(game))

    def test_tokens_with_no_illustration_are_each_kept_once(self):
        mine = self.token("Lost Mine of Phandelver", layout="normal", type_line="Dungeon", illustration_id=None)
        again = dict(mine, id="p-again", set="oafr")
        mage = self.token("Dungeon of the Mad Mage", layout="normal", type_line="Dungeon", illustration_id=None)
        self.assertEqual(["Dungeon of the Mad Mage", "Lost Mine of Phandelver"], sorted(self.names(mine, again, mage)))

    def test_what_is_and_is_not_a_token(self):
        emblem = self.token("Chandra Emblem", layout="emblem", type_line="Emblem \u2014 Chandra")
        stickers = self.token("Ancestral Hot Dog Minotaur", layout="normal", type_line="Stickers")
        flipped = self.token("Flip Token", layout="flip", type_line="Token Creature \u2014 Human // Token Creature \u2014 Wolf")
        walker = self.token("Dungeon Walker", layout="normal", type_line="Legendary Planeswalker \u2014 Dungeon")
        substitute = self.token("Substitute", layout="token", type_line="Card", set_type="memorabilia")
        checklist = self.token("Checklist", layout="token", type_line="Card", set_type="token")
        french = self.token("Gobelin", lang="fr")
        plain = bolt()
        kept = self.names(emblem, stickers, flipped, walker, substitute, checklist, french, plain)
        self.assertEqual(["Ancestral Hot Dog Minotaur", "Chandra Emblem", "Checklist", "Flip Token"], sorted(kept))

    def test_a_token_with_a_face_on_each_side_keeps_both_faces(self):
        face = {"name": "Goblin", "type_line": "Token Creature \u2014 Goblin", "power": "1", "toughness": "1",
                "illustration_id": "ill-a", "image_uris": {"png": "a.png", "small": "a-s.jpg"}, "mana_cost": ""}
        other = dict(face, name="Soldier", illustration_id="ill-b", power="0")
        both = self.token("Goblin // Soldier", layout="double_faced_token", oracle_id=None, illustration_id=None,
                          image_uris=None, card_faces=[face, other])
        both.pop("oracle_id")
        row = build.build([], [both])["tokens"][0]
        self.assertEqual(["Goblin", "Soldier"], [f["name"] for f in row["card_faces"]])
        self.assertEqual({"png": "a.png"}, row["card_faces"][0]["image_uris"])
        self.assertEqual("0", row["card_faces"][1]["power"])
        self.assertNotIn("mana_cost", row["card_faces"][0])
        self.assertNotIn("image_uris", row)

    def test_a_reversible_token_is_one_and_a_reversible_card_is_not(self):
        sides = [{"name": "Mechtitan", "layout": "token", "type_line": "Token Legendary Artifact Creature \u2014 Construct", "illustration_id": "ill-m"}] * 2
        token = self.token("Mechtitan // Mechtitan", layout="reversible_card", type_line=None, card_faces=sides)
        real = [{"name": "Mechtitan Core", "layout": "normal", "type_line": "Artifact \u2014 Vehicle", "illustration_id": "ill-c"}] * 2
        vehicle = self.token("Mechtitan Core // Mechtitan Core", layout="reversible_card", type_line=None, card_faces=real, id="p-core")
        self.assertEqual(["Mechtitan // Mechtitan"], self.names(token, vehicle))

    def test_a_card_carries_its_keywords(self):
        squad = card("Arco-Flagellant", keywords=["Squad"])
        rows = build.build([squad, bolt()], [squad, bolt()])["cards"]
        by_name = {row["n"]: row for row in rows}
        self.assertEqual(["Squad"], by_name["Arco-Flagellant"]["kw"])
        self.assertNotIn("kw", by_name["Lightning Bolt"])


    def test_a_painting_only_ever_shown_in_a_client_says_so(self):
        online = bolt(id="p-mtgo", games=["mtgo"], illustration_id="ill-online")
        tables = build.build([bolt()], [bolt(), online])
        by_picture = {row["il"]: row for row in tables["art"]}
        self.assertTrue(by_picture["ill-online"]["dg"])
        self.assertNotIn("dg", by_picture["ill-Lightning Bolt"])
        self.assertNotIn("dg", tables["cards"][0])

    def test_a_playtest_card_is_a_joke_though_its_set_is_not_called_one(self):
        nowhere = {"vintage": "not_legal"}
        playtest = card("Totally Safe Hideout", set="mb2", set_type="masters", promo_types=["playtest"], legalities=nowhere)
        tables = build.build([playtest], [playtest])
        self.assertTrue(tables["cards"][0]["fu"])


    def test_a_painting_only_printed_in_another_language_says_which(self):
        japanese = bolt(id="p-ja", lang="ja", illustration_id="ill-ja")
        tables = build.build([bolt()], [bolt(), japanese])
        by_picture = {row["il"]: row for row in tables["art"]}
        self.assertEqual("ja", by_picture["ill-ja"]["lg"])
        self.assertNotIn("lg", by_picture["ill-Lightning Bolt"])


if __name__ == "__main__":
    unittest.main()
