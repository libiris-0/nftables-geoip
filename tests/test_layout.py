"""SPEC 3: country range, continent blocks, path cost, ordering and code assignment."""
import random
import unittest

from nftables_geoip import pathsearch
from nftables_geoip.countries import Country
from nftables_geoip.layout import (LayoutError, choose_block_size, cost_matrix, layout,
                                   parse_countries, place)
from nftables_geoip.links import Links, parse_links
from tests import world


def world_countries():
    return {c: Country(c, cont, lat, lon) for c, cont, lat, lon, _ in world.COUNTRIES}


def world_links():
    return parse_links(world.links_text(), set(world_countries()))


class CountriesRangeTests(unittest.TestCase):
    """3.1"""

    def test_aligned_power_of_two(self):
        self.assertEqual(parse_countries("0x800-0xfff"), (0x800, 0x800))
        self.assertEqual(parse_countries("256-511"), (256, 256))
        self.assertEqual(parse_countries("0-0xffff"), (0, 0x10000))

    def test_rejected(self):
        for text in ("0x800-0xffe",      # size is not a power of two
                     "0x400-0xbff",      # start is not a multiple of the size
                     "0xfff-0x800",      # reversed
                     "0x800", "a-b", "0x800-0xfff-0x1000"):
            with self.subTest(text=text), self.assertRaises(LayoutError):
                parse_countries(text)


class BlockSizeTests(unittest.TestCase):
    """3.2"""

    def test_largest_power_of_two_that_fits(self):
        real = [58, 53, 51, 41, 28, 14, 5]                  # countries per continent in the real data
        self.assertEqual(choose_block_size(real, 2048), 256)
        self.assertEqual(choose_block_size(real + [1], 2048), 256)     # exactly eight blocks with ZZ
        self.assertEqual(choose_block_size([3, 2], 2048), 1024)
        self.assertEqual(choose_block_size(real, 1024), 128)

    def test_no_fit(self):
        with self.assertRaises(LayoutError):
            choose_block_size([58, 53, 51, 41, 28, 14, 5], 256)    # blocks of at least 64 leave no room for 7
        with self.assertRaises(LayoutError):
            choose_block_size([300], 256)


class CostTests(unittest.TestCase):
    """3.3"""

    def test_cost_formula(self):
        countries = {"A": Country("A", "EU", 0.0, 0.0), "B": Country("B", "EU", 0.0, 0.0),
                     "C": Country("C", "EU", 0.0, 0.0)}
        links = Links([frozenset("AB"), frozenset("ABC"), frozenset("AB")], {("A", "C")})
        C = cost_matrix(["A", "B", "C"], countries, links)
        self.assertEqual(C[0][1], -3.0)                     # three shared cables
        self.assertEqual(C[0][2], -2.0)                     # one cable plus a border
        self.assertEqual(C[1][2], -1.0)
        self.assertEqual(C[1][0], C[0][1])                  # symmetric

    def test_distance_term(self):
        countries = {"A": Country("A", "EU", 0.0, 0.0), "B": Country("B", "EU", 0.0, 180.0)}
        C = cost_matrix(["A", "B"], countries, None)
        self.assertAlmostEqual(C[0][1], 1.5 * 12742 * 3.141592653589793 / 2 / 1000, places=6)


class PathSearchTests(unittest.TestCase):
    """The path search used by 3.4 step 1."""

    def line(self, n):
        return [[abs(i - j) * 1.0 for j in range(n)] for i in range(n)]

    def test_line_is_found_and_tie_broken(self):
        order = list(range(9))
        random.Random(1).shuffle(order)
        self.assertEqual(pathsearch.solve(order, self.line(9)), list(range(9)))

    def test_anchors(self):
        C = self.line(6)
        self.assertEqual(pathsearch.solve([3, 1, 4, 2], C, left=0, right=5), [1, 2, 3, 4])
        self.assertEqual(pathsearch.path_cost([1, 2], C, left=0, right=5), 1 + 1 + 3)


class PlaceTests(unittest.TestCase):
    """3.5"""

    def test_every_aligned_sub_block_holds_a_contiguous_stretch(self):
        rnd = random.Random(5)
        for n, size in ((1, 8), (2, 2), (5, 8), (8, 8), (13, 64), (58, 256)):
            with self.subTest(n=n, size=size):
                C = [[rnd.random() for _ in range(n)] for _ in range(n)]
                codes = place(list(range(n)), 256, size, C)
                self.assertEqual(codes, sorted(set(codes)))          # order kept, all distinct
                self.assertEqual(codes[0], 256)                      # first country at the start of the block
                self.assertTrue(all(256 <= c < 256 + size for c in codes))
                for log in range(size.bit_length()):
                    sub = 1 << log
                    for lo in range(256, 256 + size, sub):
                        inside = [i for i, c in enumerate(codes) if lo <= c < lo + sub]
                        if inside:
                            self.assertEqual(inside, list(range(inside[0], inside[-1] + 1)))

    def test_cut_at_the_weakest_link(self):
        C = [[0.0] * 8 for _ in range(8)]
        for i in range(7):
            C[i][i + 1] = C[i + 1][i] = -5.0
        C[3][4] = C[4][3] = 5.0                             # weakest in the middle
        C[1][2] = C[2][1] = 4.0                             # second weakest, but off centre
        codes = place(list(range(8)), 0, 16, C)
        self.assertEqual([c >> 3 for c in codes], [0, 0, 0, 0, 1, 1, 1, 1])

    def test_balance_breaks_ties(self):
        C = [[0.0] * 6 for _ in range(6)]                   # all links equally strong
        codes = place(list(range(6)), 0, 8, C)
        self.assertEqual([c >> 2 for c in codes], [0, 0, 0, 1, 1, 1])


class LayoutTests(unittest.TestCase):
    """Overall properties of 3.2 to 3.5."""

    @classmethod
    def setUpClass(cls):
        cls.countries = world_countries()
        cls.lay = layout(cls.countries, world_links(), 0x800, 0x800)

    def test_codes_are_unique_and_inside_the_range(self):
        codes = self.lay.codes
        self.assertEqual(set(codes), set(self.countries))
        self.assertEqual(len(set(codes.values())), len(codes))
        self.assertTrue(all(0x800 <= v <= 0xfff for v in codes.values()))

    def test_each_continent_is_one_aligned_block(self):
        S = self.lay.block_size
        self.assertEqual(S, 256)
        starts = sorted(lo for lo, _ in self.lay.blocks.values())
        self.assertEqual(starts, [0x800 + k * S for k in range(len(starts))])  # adjacent from LO
        for cont, (lo, hi) in self.lay.blocks.items():
            self.assertEqual(hi - lo + 1, S)
            inside = {c for c, v in self.lay.codes.items() if lo <= v <= hi}
            self.assertEqual(inside, {c for c, k in self.countries.items() if k.continent == cont})
            self.assertIn(lo, self.lay.codes.values())      # a country at the start of the block

    def test_order_follows_codes(self):
        self.assertEqual(self.lay.order, sorted(self.lay.codes, key=self.lay.codes.get))

    def test_links_pull_countries_together(self):
        far = Links([frozenset({"PT", "PL"})] * 20, set())
        geo = layout(self.countries, None, 0x800, 0x800).order
        net = layout(self.countries, far, 0x800, 0x800).order
        self.assertGreater(abs(geo.index("PT") - geo.index("PL")), 1)
        self.assertEqual(abs(net.index("PT") - net.index("PL")), 1)

    def test_deterministic(self):
        again = layout(dict(reversed(list(self.countries.items()))), world_links(), 0x800, 0x800)
        self.assertEqual(again.codes, self.lay.codes)

    def test_small_range_rejected(self):
        with self.assertRaises(LayoutError):
            layout(self.countries, None, 0x800, 8)


if __name__ == "__main__":
    unittest.main()
