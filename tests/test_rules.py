"""SPEC 5.1, 5.2, geoclass generation in 6.2, and the ranges and mask cover of 7."""
import unittest

from nftables_geoip.rules import (Evaluator, RuleError, Universe, class_ranges, compile_rules,
                                  masks, parse, runs)

# unused codes left on purpose: Asia from 0x900, Africa from 0xa00, Europe from 0xb00
UNI = Universe({
    "CN": ("AS", 0x900), "JP": ("AS", 0x901), "SG": ("AS", 0x910), "TR": ("AS", 0x950),
    "EG": ("AF", 0xa00),
    "FR": ("EU", 0xb00), "DE": ("EU", 0xb01), "RU": ("EU", 0xb02),
})


def ev(expr: str, defs: str = "") -> set[str]:
    return set(Evaluator(UNI, parse(defs + f"\nQ_ = {expr}\n")).region("Q_"))


class ParseTests(unittest.TestCase):
    """5.1"""

    def test_statements(self):
        p = parse("# comment\nA = CN  # trailing comment\n\ndefault -> 0x1\nA -> 17 !\n@EU -> 2\n")
        self.assertEqual(list(p.definitions), ["A"])
        self.assertEqual((p.default, p.default_line), (1, 4))
        self.assertEqual([(r.cls, r.line, r.override) for r in p.rules],
                         [(17, 5, True), (2, 6, False)])

    def test_errors(self):
        for text in ("CN = SG",                  # a country code is not a name
                     "default = CN",             # default is not a name
                     "A = CN\nA = JP",           # defined twice
                     "A =",                      # missing expression
                     "CN -> ", "CN -> 1 -> 2", "CN -> x", "-> 1",
                     "default -> 1 !",           # default cannot take !
                     "default -> 1\ndefault -> 2",
                     "CN $ JP -> 1"):
            with self.subTest(text=text), self.assertRaises(RuleError):
                parse(text)


class ExpressionTests(unittest.TestCase):
    """5.2 expressions"""

    def test_operators(self):
        self.assertEqual(ev("CN + JP + SG"), {"CN", "JP", "SG"})
        self.assertEqual(ev("@EU - FR"), {"DE", "RU"})
        self.assertEqual(ev("@AS & (CN + FR)"), {"CN"})
        self.assertEqual(ev("~(@AS + @EU)"), {"EG"})
        self.assertEqual(ev("~~CN"), {"CN"})
        self.assertEqual(ev("@ZZ"), set())

    def test_precedence(self):
        self.assertEqual(ev("CN + JP & @EU"), {"CN"})        # & binds tighter than +
        self.assertEqual(ev("@AS - CN + CN"), ev("@AS"))      # + and - associate left to right
        self.assertEqual(ev("~CN + CN"), set(UNI.countries))  # ~ applies to the next factor only

    def test_names(self):
        self.assertEqual(ev("ESEA - JP", "ESEA = CN + JP + SG"), {"CN", "SG"})
        self.assertEqual(ev("B", "B = A + JP\nA = CN"), {"CN", "JP"})   # definitions may come in any order

    def test_unknown_country_warns_and_is_empty(self):
        e = Evaluator(UNI, parse("Q_ = CN + QQ\n"))
        self.assertEqual(set(e.region("Q_")), {"CN"})
        self.assertTrue(any("QQ" in w for w in e.warnings))

    def test_errors(self):
        cases = {"A": "A = B + CN\nB = A",       # circular reference
                 "NOPE": "",                     # undefined
                 "@XX": "",                      # unknown continent
                 "(CN": "", "CN +": "", "CN JP": "", "CN + 5": "",
                 "cn": ""}                       # lower case is a name, undefined
        for expr, defs in cases.items():
            with self.subTest(expr=expr), self.assertRaises(RuleError):
                ev(expr, defs)


class CompileTests(unittest.TestCase):
    """5.2 classes and rules"""

    def test_classes(self):
        res = compile_rules("default -> 1\n@EU -> 2\nCN + JP -> 3\n", UNI)
        self.assertEqual(res.classes, {"CN": 3, "JP": 3, "SG": 1, "TR": 1, "EG": 1,
                                       "FR": 2, "DE": 2, "RU": 2})
        self.assertEqual(res.default, 1)

    def test_default_position_does_not_matter(self):
        a = compile_rules("default -> 1\n@EU -> 2\n", UNI)
        b = compile_rules("@EU -> 2\ndefault -> 1\n", UNI)
        self.assertEqual((a.classes, a.geoclass), (b.classes, b.geoclass))

    def test_class_range(self):
        for bad in ("0", "0x100000000"):
            with self.subTest(cls=bad), self.assertRaises(RuleError):
                compile_rules(f"CN -> {bad}\n", UNI)
        with self.assertRaises(RuleError):
            compile_rules("default -> 0\n", UNI)
        self.assertTrue(compile_rules("CN -> 0xffffffff\n", UNI).classes)

    def test_overlap_is_an_error_listing_every_conflict(self):
        with self.assertRaises(RuleError) as e:
            compile_rules("@EU -> 2\nCN -> 3\nDE + RU + CN -> 5\n", UNI)
        msg = str(e.exception)
        self.assertIn("line 3 overlaps line 1: DE RU", msg)
        self.assertIn("line 3 overlaps line 2: CN", msg)

    def test_same_class_overlap_is_fine(self):
        res = compile_rules("@EU -> 2\nDE -> 2\n", UNI)
        self.assertEqual(res.classes["DE"], 2)
        self.assertEqual(res.notes, [])

    def test_override(self):
        res = compile_rules("@EU -> 2\nDE -> 5 !\n", UNI)
        self.assertEqual(res.classes["DE"], 5)
        self.assertEqual(res.notes, ["line 2 overrides line 1: DE"])

    def test_useless_override_warns(self):
        res = compile_rules("@EU -> 2\nCN -> 5 !\n", UNI)
        self.assertTrue(any("overrides no countries" in w for w in res.warnings))

    def test_empty_rule_warns(self):
        res = compile_rules("@ZZ -> 2\n", UNI)
        self.assertTrue(any("selects no countries" in w for w in res.warnings))

    def test_unused_definitions_are_still_checked(self):
        with self.assertRaises(RuleError):
            compile_rules("A = NOPE\nCN -> 1\n", UNI)

    def test_no_default(self):
        res = compile_rules("CN -> 3\n", UNI)
        self.assertEqual(res.classes, {"CN": 3})
        self.assertIsNone(res.default)
        self.assertTrue(any("no default" in w for w in res.warnings))


class GeoclassTests(unittest.TestCase):
    """The three geoclass steps of 6.2"""

    def test_with_default_uses_wildcard(self):
        res = compile_rules("default -> 1\nCN + JP + SG -> 3\n@EU -> 2\n", UNI)
        # unused codes follow the country below: 0x902-0x90f follow JP, 0x911-0x94f follow SG
        self.assertEqual(res.geoclass, [(0x900, 0x94f, 3), (0xb00, 0xb02, 2)])

    def test_without_default(self):
        res = compile_rules("CN -> 3\nFR + DE -> 2\n", UNI)
        # JP has no class: JP and the unused codes after it take no value until the next classed country
        self.assertEqual(res.geoclass, [(0x900, 0x900, 3), (0xb00, 0xb01, 2)])

    def test_range_stops_at_the_last_country(self):
        ranges = class_ranges({c: 1 for c in UNI.countries}, UNI)
        self.assertEqual(ranges, [(0x900, 0xb02, 1)])

    def test_every_classed_code_is_covered(self):
        res = compile_rules("default -> 1\n@AS - JP -> 4\nRU -> 5\n", UNI)
        for country, cls in res.classes.items():
            code = UNI.code(country)
            hit = [k for lo, hi, k in res.geoclass if lo <= code <= hi]
            self.assertEqual(hit or [res.default], [cls], country)


class MaskTests(unittest.TestCase):
    """7"""

    def test_ranges(self):
        self.assertEqual(runs({"CN", "JP", "SG"}, UNI), [(0x900, 0x910)])    # spans unused codes
        self.assertEqual(runs({"CN", "SG"}, UNI), [(0x900, 0x900), (0x910, 0x910)])  # JP in between
        self.assertEqual(runs(set(), UNI), [])

    def covered(self, pairs):
        return {c for c, (_, code) in UNI.countries.items() if any(code & m == v for v, m in pairs)}

    def test_exact_cover(self):
        full = 0xfff                                        # the highest code 0xb02 has 12 bits
        for sel in ({"CN"}, {"CN", "JP"}, {"CN", "JP", "SG"}, {"FR", "DE", "RU"},
                    set(UNI.countries), {"TR", "EG"}, set()):
            with self.subTest(sel=sel):
                pairs = masks(sel, UNI)
                self.assertEqual(self.covered(pairs), sel)
                for v, m in pairs:
                    self.assertGreaterEqual(v, 0x900)       # not below the lowest country code
                    self.assertEqual(v & ~m & full, 0)      # value aligned to mask

    def test_fewest_blocks(self):
        self.assertEqual(masks({"CN"}, UNI), [(0x900, 0xfff)])
        self.assertEqual(masks({"CN", "JP"}, UNI), [(0x900, 0xff0)])     # 0x902-0x90f are unused codes
        self.assertEqual(masks({"FR", "DE", "RU"}, UNI), [(0xb00, 0xf00)])   # may include unused codes


if __name__ == "__main__":
    unittest.main()
