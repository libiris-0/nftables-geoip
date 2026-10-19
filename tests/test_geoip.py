"""SPEC 1.1: reading GeoIP data, dropping overlapping networks and merging ranges."""
import tempfile
import unittest
from pathlib import Path

from nftables_geoip.geoip import BLOCKS, LOCATIONS, Network, read_networks
from nftables_geoip.ipmap import IPMapBuilder
from tests import world


class ReadNetworksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = world.write_geoip(Path(cls._tmp.name) / "geoip")
        cls.nets = list(read_networks(cls.dir))
        cls.by_start = {(n.family, n.start): n for n in cls.nets}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def net(self, cidr: str) -> Network:
        family = 6 if ":" in cidr else 4
        return self.by_start[(family, world.cidr_range(cidr)[0])]

    def test_every_row_becomes_one_network(self):
        rows = sum(len((self.dir / name).read_text(encoding="utf-8").splitlines()) - 1
                   for name in BLOCKS.values())
        self.assertEqual(len(self.nets), rows)

    def test_fields(self):
        n = self.net("10.21.0.0/24")                       # first network of JP
        self.assertEqual((n.family, n.country, n.continent, n.lat, n.lon),
                         (4, "JP", "AS", 36.2, 138.3))
        self.assertEqual((n.start, n.end), world.cidr_range("10.21.0.0/24"))
        n6 = self.net("2001:db8:15::/48")
        self.assertEqual((n6.family, n6.country), (6, "JP"))
        self.assertEqual(n6.end - n6.start + 1, 1 << 80)

    def test_registered_country_when_location_is_empty(self):
        n = self.net(world.REGISTERED_ONLY_NET)
        self.assertEqual((n.country, n.continent), ("JP", "AS"))
        self.assertIsNone(n.lat)

    def test_registered_country_when_location_has_no_country(self):
        n = self.net(world.CONTINENT_ONLY_NET)
        self.assertEqual((n.country, n.continent), ("DE", "EU"))
        self.assertEqual((n.lat, n.lon), (50.0, 8.0))      # coordinates still come from the network itself

    def test_no_country_at_all(self):
        n = self.net(world.NO_COUNTRY_NET)
        self.assertEqual((n.country, n.continent, n.lat, n.lon), ("", "", None, None))

    def test_every_file_is_required(self):
        for missing in (LOCATIONS, *BLOCKS.values()):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as d:
                d = world.write_geoip(Path(d))
                (d / missing).unlink()
                with self.assertRaises(FileNotFoundError) as e:
                    list(read_networks(d))
                self.assertIn(missing, str(e.exception))


def build_ipmap(networks, codes):
    builder = IPMapBuilder()
    for net in networks:
        builder.add(net)
    return builder.ranges(codes)


class IPMapTests(unittest.TestCase):
    def nets(self, *rows):
        return [Network(f, s, e, c, "", None, None) for f, s, e, c in rows]

    def test_overlapping_networks_are_dropped(self):
        # deliberately out of order: the inner network comes before the outer one
        maps, dropped = build_ipmap(self.nets(
            (4, 0, 127, "B"),           # same start as the outer network
            (4, 128, 191, "B"),         # inside the outer network
            (4, 0, 255, "A"),
            (4, 256, 511, "B")), {"A": 1, "B": 2})
        self.assertEqual(maps[4], [(0, 255, 1), (256, 511, 2)])
        self.assertEqual(dropped, 2)

    def test_adjacent_ranges_with_the_same_code_merge(self):
        maps, _ = build_ipmap(self.nets(
            (4, 0, 9, "A"), (4, 10, 19, "A"), (4, 30, 39, "A"),   # not adjacent: not merged
            (4, 40, 49, "B"), (6, 0, 0, "A")), {"A": 1, "B": 2})
        self.assertEqual(maps[4], [(0, 19, 1), (30, 39, 1), (40, 49, 2)])
        self.assertEqual(maps[6], [(0, 0, 1)])

    def test_input_order_does_not_matter(self):
        rows = [(4, 20, 29, "B"), (4, 0, 9, "A"), (4, 10, 19, "A")]
        a, _ = build_ipmap(self.nets(*rows), {"A": 1, "B": 2})
        b, _ = build_ipmap(self.nets(*reversed(rows)), {"A": 1, "B": 2})
        self.assertEqual(a, b)

    def test_both_families_always_present(self):
        maps, _ = build_ipmap(self.nets((4, 0, 0, "A")), {"A": 1})
        self.assertEqual(maps[6], [])

    def test_network_without_country_uses_zz(self):
        maps, _ = build_ipmap(self.nets((4, 0, 0, "")), {"ZZ": 7})
        self.assertEqual(maps[4], [(0, 0, 7)])


if __name__ == "__main__":
    unittest.main()
