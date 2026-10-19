"""SPEC 1.2: the links file."""
import unittest

from nftables_geoip.links import LinksError, parse_links
from tests import world

PRESENT = {"CN", "VN", "JP", "SG", "FR", "DE"}


def parse(text, present=PRESENT):
    return parse_links(text, present, "t")


class ParseTests(unittest.TestCase):
    def test_cables_and_borders(self):
        links = parse("cable:a  CN JP SG\nborder  VN CN\n")
        self.assertEqual(links.cables, [frozenset({"CN", "JP", "SG"})])
        self.assertEqual(links.borders, {("CN", "VN")})

    def test_comments_blank_lines_and_whitespace(self):
        links = parse("# comment\n\n  cable   CN\tJP   # trailing comment\n\t\n")
        self.assertEqual(links.cables, [frozenset({"CN", "JP"})])

    def test_identifier_is_optional(self):
        self.assertEqual(len(parse("cable CN JP\ncable CN JP\n").cables), 2)

    def test_duplicate_codes_in_a_line_count_once(self):
        self.assertEqual(parse("cable:a CN JP JP\n").cables, [frozenset({"CN", "JP"})])

    def test_repeated_border_counts_once(self):
        self.assertEqual(parse("border CN VN\nborder VN CN\n").borders, {("CN", "VN")})

    def test_countries_not_in_the_data_are_ignored(self):
        links = parse("cable:a CN XX YY\ncable:b CN JP XX\nborder CN XX\n")
        self.assertEqual(links.cables, [frozenset({"CN", "JP"})])   # only one country left on the first line
        self.assertEqual(links.borders, set())

    def test_errors(self):
        bad = {
            "unknown kind": "road CN JP",
            "kind with id": "road:x CN JP",
            "lower case": "cable cn JP",
            "three letters": "cable CHN JP",
            "one country": "cable:a CN",
            "one country after dedup": "cable:a CN CN",
            "border with three": "border CN VN JP",
            "duplicate id": "cable:a CN JP\nborder:a CN VN",
        }
        for what, text in bad.items():
            with self.subTest(what), self.assertRaises(LinksError):
                parse(text)

    def test_error_names_the_line(self):
        with self.assertRaises(LinksError) as e:
            parse("cable CN JP\n\nroad CN JP\n")
        self.assertIn("t:3", str(e.exception))

    def test_world_links_parse(self):
        present = {c[0] for c in world.COUNTRIES}
        links = parse(world.links_text(), present)
        self.assertEqual(len(links.cables), len(world.CABLES))
        self.assertIn(frozenset({"PT", "ES"}), links.cables)       # phantom keeps two countries without XX
        self.assertIn(("ES", "PT"), links.borders)


if __name__ == "__main__":
    unittest.main()
