"""End to end: the build directory of SPEC 4, the nft script of 6.2, query of 7, and command-line errors."""
import contextlib
import csv
import io
import ipaddress
import re
import tempfile
import unittest
from pathlib import Path

from nftables_geoip import nft
from nftables_geoip.cli import main
from tests import world


def run(*argv) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main([str(a) for a in argv])
    return code, out.getvalue(), err.getvalue()


def class_of(elements: list[tuple[str, str]], code: int) -> str | None:
    """Look up the class of a code in the geoclass elements, including the wildcard."""
    wildcard = None
    for key, value in elements:
        if key == "*":
            wildcard = value
            continue
        lo, _, hi = key.partition("-")
        if int(lo, 16) <= code <= int(hi or lo, 16):
            return value
    return wildcard


def parse_script(text: str) -> dict[str, list[tuple[str, str]]]:
    """nft script -> map name -> [(key, value)], checking the script structure."""
    maps: dict[str, list[tuple[str, str]]] = {}
    current = None
    for line in text.splitlines():
        if m := re.fullmatch(r"flush map inet t (\w+)", line):
            current = m[1]
            maps[current] = []
        elif m := re.fullmatch(r"add element inet t (\w+) \{", line):
            assert m[1] == current, line
        elif m := re.fullmatch(r"  (\S+) : (0x[0-9a-f]+),?", line):
            maps[current].append((m[1], m[2]))
        else:
            assert line == "}", line
    return maps


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        cls.root = root
        cls.geoip = world.write_geoip(root / "geoip")
        cls.links = world.write_links(root / "links.txt")
        cls.build = root / "build"
        code, _, cls.build_err = run("build", "--geoip", cls.geoip, "--countries", "0x800-0xfff",
                                     "--links", cls.links, "--out", cls.build)
        assert code == 0, cls.build_err
        with open(cls.build / "countries.csv", newline="") as f:
            cls.rows = list(csv.DictReader(f))
        cls.codes = {r["country"]: int(r["code"], 16) for r in cls.rows}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def rules(self, text: str) -> Path:
        p = Path(tempfile.mkdtemp(dir=self.root)) / "rules.txt"
        p.write_text(text)
        return p

    def compile(self, rules: str):
        out = Path(tempfile.mkdtemp(dir=self.root)) / "out.nft"
        code, _, err = run("compile", self.build, self.rules(rules), "--table", "inet t", "-o", out)
        self.assertEqual(code, 0, err)
        return out.read_text(), err

    # SPEC 4

    def test_build_dir_has_exactly_three_files(self):
        self.assertEqual(sorted(p.name for p in self.build.iterdir()),
                         ["countries.csv", "ipmap4.csv", "ipmap6.csv"])

    def test_countries_csv(self):
        self.assertEqual(list(self.rows[0])[:3], ["code", "country", "continent"])
        self.assertEqual(len(self.rows), len(world.COUNTRIES) + 1)              # plus ZZ
        codes = [r["code"] for r in self.rows]
        self.assertTrue(all(re.fullmatch(r"0x[0-9a-f]+", c) for c in codes))
        self.assertEqual([int(c, 16) for c in codes], sorted(int(c, 16) for c in codes))
        self.assertEqual({r["continent"] for r in self.rows if r["country"] == "ZZ"}, {"ZZ"})

    def test_ipmaps(self):
        for fam in (4, 6):
            with self.subTest(family=fam), open(self.build / f"ipmap{fam}.csv", newline="") as f:
                rows = list(csv.DictReader(f))
                self.assertEqual(list(rows[0]), ["start", "end", "code"])
                prev_end, prev_code = -2, None
                for r in rows:
                    s, e = (int(ipaddress.ip_address(r[k])) for k in ("start", "end"))
                    code = int(r["code"], 16)
                    self.assertEqual(ipaddress.ip_address(r["start"]).version, fam)
                    self.assertGreater(s, prev_end)                         # sorted, no overlap
                    self.assertFalse(s == prev_end + 1 and code == prev_code)   # merged
                    self.assertIn(code, self.codes.values())
                    prev_end, prev_code = e, code

    def test_special_networks(self):
        def code_of(addr):
            n = int(ipaddress.ip_address(addr))
            with open(self.build / "ipmap4.csv", newline="") as f:
                for r in csv.DictReader(f):
                    if int(ipaddress.ip_address(r["start"])) <= n <= int(ipaddress.ip_address(r["end"])):
                        return int(r["code"], 16)
        self.assertEqual(code_of("10.250.0.1"), self.codes["ZZ"])
        self.assertEqual(code_of("10.251.0.1"), self.codes["JP"])
        self.assertEqual(code_of("10.252.0.1"), self.codes["DE"])
        self.assertEqual(code_of("10.0.0.200"), self.codes["US"])               # the overlapping CN network is dropped
        self.assertIn("overlapping networks dropped: 1", self.build_err)

    def test_build_is_deterministic(self):
        again = self.root / "again"
        code, _, err = run("build", "--geoip", self.geoip, "--countries", "0x800-0xfff",
                           "--links", self.links, "--out", again)
        self.assertEqual(code, 0, err)
        for name in ("countries.csv", "ipmap4.csv", "ipmap6.csv"):
            self.assertEqual((again / name).read_bytes(), (self.build / name).read_bytes(), name)

    def test_build_without_links(self):
        code, _, err = run("build", "--geoip", self.geoip, "--countries", "0x800-0xfff",
                           "--out", self.root / "nolinks")
        self.assertEqual(code, 0, err)

    # 6.2

    def test_script_structure_and_values(self):
        text, _ = self.compile("default -> 0x200\n@EU -> 0x301\nJP -> 0x212\n")
        self.assertEqual([l for l in text.splitlines() if l.startswith("flush")],
                         ["flush map inet t geo4", "flush map inet t geo6", "flush map inet t geoclass"])
        maps = parse_script(text)
        # with a default, every network is written
        with open(self.build / "ipmap4.csv", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(maps["geo4"]), len(rows))
        first = rows[0]
        self.assertEqual(maps["geo4"][0], (f"{first['start']}-{first['end']}", first["code"]))
        # default is the trailing wildcard; no other geoclass element has the value 0x200
        self.assertEqual(maps["geoclass"][-1], ("*", "0x200"))
        self.assertNotIn("0x200", [v for _, v in maps["geoclass"][:-1]])
        self.assertEqual(class_of(maps["geoclass"], self.codes["JP"]), "0x212")
        self.assertEqual(class_of(maps["geoclass"], self.codes["FR"]), "0x301")
        self.assertEqual(class_of(maps["geoclass"], self.codes["CN"]), "0x200")

    def test_without_default_unclassed_addresses_are_left_out(self):
        text, err = self.compile("JP + SG -> 0x212\n")
        maps = parse_script(text)
        wanted = {hex(self.codes["JP"]), hex(self.codes["SG"])}
        self.assertEqual({v for _, v in maps["geo4"]}, wanted)
        self.assertEqual({v for _, v in maps["geo6"]}, wanted)
        # the three /24s of JP and of SG each merge into one range, plus one network registered to JP
        self.assertEqual(len(maps["geo4"]), 3)
        for code in wanted:
            self.assertIsNotNone(class_of(maps["geoclass"], int(code, 16)))
        self.assertNotIn("*", [k for k, _ in maps["geoclass"]])
        self.assertIn("no default", err)

    def test_single_addresses(self):
        text, _ = self.compile("default -> 1\n")
        for key, _ in parse_script(text)["geoclass"]:
            self.assertNotRegex(key, r"^(0x[0-9a-f]+)-\1$")  # a single value when first equals last

    def test_chunks(self):
        old = nft.CHUNK
        nft.CHUNK = 10
        try:
            text, _ = self.compile("default -> 1\n")
        finally:
            nft.CHUNK = old
        geo4 = len(parse_script(text)["geo4"])
        self.assertEqual(text.count("add element inet t geo4 {"), -(-geo4 // 10))

    def test_empty_map_has_only_flush(self):
        text, _ = self.compile("@ZZ -> 1\n")                 # ZZ has IPv4 networks only
        self.assertIn("flush map inet t geo6\nflush map inet t geoclass\n", text)

    def test_example_rules_compile(self):
        examples = Path(__file__).resolve().parent.parent / "examples"
        out = self.root / "example.nft"
        code, _, err = run("compile", self.build, examples / "rules.txt", "--table", "inet routing",
                           "-o", out)
        self.assertEqual(code, 0, err)
        self.assertIn("flush map inet routing geo4", out.read_text())

    def test_compile_is_deterministic(self):
        rules = "default -> 0x200\n@EU -> 0x301\n"
        self.assertEqual(self.compile(rules)[0], self.compile(rules)[0])

    # 7

    def test_query(self):
        rules = self.root / "q-rules.txt"
        rules.write_text("ESEA = CN + JP + SG\n")
        code, out, err = run("query", self.build, "--rules", rules, "ESEA - JP")
        self.assertEqual(code, 0, err)
        self.assertIn(hex(self.codes["CN"]), out)
        self.assertIn("SG", out)
        self.assertNotIn("JP", out)

    # errors

    def test_errors_exit_1_with_a_message(self):
        rules = self.rules("CN -> 1\n")
        cases = {
            "bad range": ("build", "--geoip", self.geoip, "--countries", "0x800-0xffe",
                          "--out", self.root / "x"),
            "range too small": ("build", "--geoip", self.geoip, "--countries", "0x800-0x80f",
                                "--out", self.root / "x"),
            "missing geoip": ("build", "--geoip", self.root / "nope", "--countries", "0x800-0xfff",
                              "--out", self.root / "x"),
            "overlap": ("compile", self.build, self.rules("@EU -> 1\nFR -> 2\n"),
                        "--table", "inet t", "-o", self.root / "x"),
            "empty table": ("compile", self.build, rules, "--table", " ", "-o", self.root / "x"),
            "missing rules": ("compile", self.build, self.root / "nope.txt",
                              "--table", "inet t", "-o", self.root / "x"),
            "missing build": ("compile", self.root / "nope", rules, "--table", "inet t",
                              "-o", self.root / "x"),
        }
        for what, argv in cases.items():
            with self.subTest(what):
                code, _, err = run(*argv)
                self.assertEqual(code, 1)
                self.assertTrue(err.startswith("error: "), err)

    def test_bad_links_file(self):
        bad = self.root / "bad-links.txt"
        bad.write_text("road CN JP\n")
        code, _, err = run("build", "--geoip", self.geoip, "--countries", "0x800-0xfff",
                           "--links", bad, "--out", self.root / "x")
        self.assertEqual(code, 1)
        self.assertIn("road", err)


if __name__ == "__main__":
    unittest.main()
