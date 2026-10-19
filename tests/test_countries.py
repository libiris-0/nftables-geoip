"""SPEC 2: continent, representative point and statistics of each country."""
import unittest

from nftables_geoip.countries import aggregate
from nftables_geoip.geoip import Network


def net(country, continent="EU", lat=0.0, lon=0.0, family=4, start=0, size=256):
    return Network(family, start, start + size - 1, country, continent, lat, lon)


class AggregateTests(unittest.TestCase):
    def test_counts(self):
        countries, _ = aggregate([net("TR", size=256), net("TR", family=6, size=1 << 80),
                                  net("TR", family=6, size=1)])
        tr = countries["TR"]
        self.assertEqual((tr.ipv4, tr.ipv6_64, tr.networks), (256, (1 << 16) + 1, 3))

    def test_continent_by_weighted_majority(self):
        # IPv4 weighs by addresses, IPv6 by /64s: one IPv6 /48 outweighs 1024 IPv4 addresses
        countries, _ = aggregate([net("XX", "EU", size=1024),
                                  net("XX", "AS", family=6, size=1 << 80)])
        self.assertEqual(countries["XX"].continent, "AS")

    def test_minority_above_one_percent_warns(self):
        _, warnings = aggregate([net("XX", "AS", size=1000), net("XX", "EU", size=20)])
        self.assertTrue(any(w.startswith("XX") for w in warnings))
        _, warnings = aggregate([net("YY", "AS", size=1000), net("YY", "EU", size=5)])
        self.assertFalse(any(w.startswith("YY") for w in warnings))

    def test_unknown_or_missing_continent_becomes_zz(self):
        countries, warnings = aggregate([net("AA", "XX"), net("BB", "")])
        self.assertEqual((countries["AA"].continent, countries["BB"].continent), ("ZZ", "ZZ"))
        self.assertTrue(any(w.startswith("AA") for w in warnings))
        self.assertTrue(any(w.startswith("BB") for w in warnings))

    def test_networks_without_country_form_zz(self):
        countries, warnings = aggregate([net("", "EU"), net("FR", "EU")])
        self.assertEqual(countries["ZZ"].continent, "ZZ")      # whatever continent the networks carry
        self.assertTrue(warnings)

    def test_spherical_mean(self):
        countries, _ = aggregate([net("FJ", lat=-17.0, lon=179.0), net("FJ", lat=-17.0, lon=-179.0)])
        self.assertAlmostEqual(abs(countries["FJ"].lon), 180.0, places=6)   # across the date line
        self.assertAlmostEqual(countries["FJ"].lat, -17.0, delta=0.01)

    def test_networks_without_coordinates_are_ignored_for_the_point(self):
        countries, _ = aggregate([net("DE", lat=50.0, lon=8.0), net("DE", lat=None, lon=None)])
        self.assertAlmostEqual(countries["DE"].lat, 50.0, places=6)

    def test_country_without_coordinates_sits_at_origin(self):
        countries, warnings = aggregate([net("DE", lat=None, lon=None)])
        self.assertEqual((countries["DE"].lat, countries["DE"].lon), (0.0, 0.0))
        self.assertTrue(any(w.startswith("DE") for w in warnings))


if __name__ == "__main__":
    unittest.main()
