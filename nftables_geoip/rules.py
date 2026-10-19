"""Rule language: parsing, evaluation and compilation into classes (SPEC 5)."""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field

CONTINENT_CODES = ("AF", "AN", "AS", "EU", "NA", "OC", "SA", "ZZ")
COUNTRY = re.compile(r"[A-Z]{2}")
CLASS_MAX = (1 << 32) - 1

_TOKEN = re.compile(r"""
      (?P<arrow>->)
    | (?P<continent>@[A-Za-z]+)
    | (?P<int>0x[0-9a-fA-F]+|\d+)(?![A-Za-z0-9_])
    | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<op>[-+&~()=!])
    """, re.VERBOSE)


class RuleError(ValueError):
    pass


@dataclass(frozen=True)
class Universe:
    """What rules are evaluated against: country -> (continent, code)."""
    countries: dict[str, tuple[str, int]]

    @property
    def all(self) -> frozenset[str]:
        return frozenset(self.countries)

    def continent(self, code: str) -> frozenset[str]:
        return frozenset(c for c, (k, _) in self.countries.items() if k == code)

    def code(self, country: str) -> int:
        return self.countries[country][1]


@dataclass
class Rule:
    tokens: list[tuple[str, str]]
    cls: int
    line: int
    override: bool


@dataclass
class Program:
    definitions: dict[str, tuple[list[tuple[str, str]], int]] = field(default_factory=dict)
    rules: list[Rule] = field(default_factory=list)
    default: int | None = None
    default_line: int = 0


@dataclass
class Compiled:
    classes: dict[str, int]                 # country with a class -> class
    default: int | None
    geoclass: list[tuple[int, int, int]]    # (first, last, class), without the default element
    notes: list[str]
    warnings: list[str]


def tokenize(line: str, lineno: int) -> list[tuple[str, str]]:
    tokens, pos = [], 0
    while True:
        while pos < len(line) and line[pos].isspace():
            pos += 1
        if pos >= len(line):
            return tokens
        m = _TOKEN.match(line, pos)
        if not m:
            raise RuleError(f"line {lineno}: unrecognised {line[pos:]!r}")
        tokens.append((m.lastgroup, m.group(m.lastgroup)))
        pos = m.end()


def parse(text: str) -> Program:
    prog = Program()
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        toks = tokenize(line, lineno)
        if len(toks) >= 2 and toks[0][0] == "name" and toks[1] == ("op", "="):
            name = toks[0][1]
            if COUNTRY.fullmatch(name) or name == "default":
                raise RuleError(f"line {lineno}: {name!r} cannot be a region name")
            if name in prog.definitions:
                raise RuleError(f"line {lineno}: {name} is already defined")
            if len(toks) == 2:
                raise RuleError(f"line {lineno}: missing expression after {name} =")
            prog.definitions[name] = (toks[2:], lineno)
            continue
        override = toks[-1:] == [("op", "!")]
        if override:
            toks = toks[:-1]
        if len(toks) < 3 or toks[-2] != ("arrow", "->") or toks[-1][0] != "int" \
                or ("arrow", "->") in toks[:-2]:
            raise RuleError(f"line {lineno}: expected 'NAME = EXPR' or 'EXPR -> CLASS [!]'")
        cls, body = int(toks[-1][1], 0), toks[:-2]
        if body == [("name", "default")]:
            if override:
                raise RuleError(f"line {lineno}: default cannot take !")
            if prog.default is not None:
                raise RuleError(f"line {lineno}: default appears twice")
            prog.default, prog.default_line = cls, lineno
        else:
            prog.rules.append(Rule(body, cls, lineno, override))
    return prog


class Evaluator:
    """Evaluate expressions to sets of countries by recursive descent."""

    def __init__(self, uni: Universe, prog: Program):
        self.uni, self.prog = uni, prog
        self.cache: dict[str, frozenset[str]] = {}
        self.stack: list[str] = []
        self.warnings: list[str] = []

    def evaluate(self, tokens, where: str) -> frozenset[str]:
        self._tokens, self._pos, self._where = tokens, 0, where
        value = self._expr()
        if self._pos != len(tokens):
            raise RuleError(f"{where}: unexpected {tokens[self._pos][1]!r}")
        return value

    def _peek(self):
        return self._tokens[self._pos] if self._pos < len(self._tokens) else (None, None)

    def _expr(self) -> frozenset[str]:
        value = self._term()
        while self._peek() in (("op", "+"), ("op", "-")):
            op = self._tokens[self._pos][1]
            self._pos += 1
            rhs = self._term()
            value = value | rhs if op == "+" else value - rhs
        return value

    def _term(self) -> frozenset[str]:
        value = self._factor()
        while self._peek() == ("op", "&"):
            self._pos += 1
            value = value & self._factor()
        return value

    def _factor(self) -> frozenset[str]:
        kind, text = self._peek()
        if kind is None:
            raise RuleError(f"{self._where}: incomplete expression")
        self._pos += 1
        if (kind, text) == ("op", "~"):
            return self.uni.all - self._factor()
        if (kind, text) == ("op", "("):
            value = self._expr()
            if self._peek() != ("op", ")"):
                raise RuleError(f"{self._where}: missing ')'")
            self._pos += 1
            return value
        if kind == "continent":
            if text[1:] not in CONTINENT_CODES:
                raise RuleError(f"{self._where}: unknown continent {text}")
            return self.uni.continent(text[1:])
        if kind == "name":
            return self.resolve(text)
        raise RuleError(f"{self._where}: unexpected {text!r}")

    def resolve(self, name: str) -> frozenset[str]:
        if COUNTRY.fullmatch(name):
            if name not in self.uni.countries:
                self.warnings.append(f"{self._where}: {name} is not in this build")
                return frozenset()
            return frozenset({name})
        if name not in self.prog.definitions:
            raise RuleError(f"{self._where}: undefined name {name!r}")
        if name in self.cache:
            return self.cache[name]
        if name in self.stack:
            raise RuleError("circular reference: " + " -> ".join(self.stack + [name]))
        self.stack.append(name)
        saved = (self._tokens, self._pos, self._where)
        tokens, line = self.prog.definitions[name]
        value = self.evaluate(tokens, f"line {line}")
        self._tokens, self._pos, self._where = saved
        self.stack.pop()
        self.cache[name] = value
        return value

    def region(self, name: str) -> frozenset[str]:
        self._tokens, self._pos, self._where = [], 0, "query"
        return self.resolve(name)


def check_class(cls: int, line: int) -> None:
    if not 1 <= cls <= CLASS_MAX:
        raise RuleError(f"line {line}: class {cls:#x} is not between 1 and 0xffffffff")


def compile_rules(text: str, uni: Universe) -> Compiled:
    prog = parse(text)
    ev = Evaluator(uni, prog)
    for name in prog.definitions:
        ev.region(name)                      # check unreferenced definitions too
    for rule in prog.rules:
        check_class(rule.cls, rule.line)
    if prog.default is not None:
        check_class(prog.default, prog.default_line)

    assigned: dict[str, int] = {}
    by_line: dict[str, int] = {}
    notes: list[str] = []
    conflicts: list[str] = []
    for rule in prog.rules:
        selected = ev.evaluate(rule.tokens, f"line {rule.line}")
        if not selected:
            ev.warnings.append(f"line {rule.line}: the rule selects no countries")
        clashes: dict[int, list[str]] = {}
        for c in sorted(selected):
            if c in assigned and assigned[c] != rule.cls:
                clashes.setdefault(by_line[c], []).append(c)
            assigned[c] = rule.cls
            by_line[c] = rule.line
        for line, cs in sorted(clashes.items()):
            if rule.override:
                notes.append(f"line {rule.line} overrides line {line}: {' '.join(cs)}")
            else:
                shown = " ".join(cs[:8]) + (f" ({len(cs)} in total)" if len(cs) > 8 else "")
                conflicts.append(f"line {rule.line} overlaps line {line}: {shown}")
        if rule.override and not clashes:
            ev.warnings.append(f"line {rule.line} has ! but overrides no countries")
    if conflicts:
        raise RuleError("rules with different classes overlap: " + "; ".join(conflicts)
                        + ". Subtract the overlap from the later rule, or end it with ! to override.")
    if prog.default is not None:
        for c in uni.countries:
            assigned.setdefault(c, prog.default)
    else:
        missing = len(uni.countries) - len(assigned)
        if missing:
            ev.warnings.append(f"no default: {missing} countries have no class, and their addresses are left out of geo4 and geo6")
    geoclass = class_ranges(assigned, uni)
    if prog.default is not None:
        geoclass = [r for r in geoclass if r[2] != prog.default]
    return Compiled(assigned, prog.default, geoclass, notes, ev.warnings)


def class_ranges(assigned: dict[str, int], uni: Universe) -> list[tuple[int, int, int]]:
    """Class ranges between the lowest and highest country code (SPEC 6.2 steps 1 and 2).

    An unused code takes the value of the nearest country below it. A country without
    a class, and the unused codes that follow it, take no value."""
    by_code = {code: assigned.get(c) for c, (_, code) in uni.countries.items()}
    ranges: list[list[int]] = []
    current = None
    for code in range(min(by_code), max(by_code) + 1):
        if code in by_code:
            current = by_code[code]
        if current is None:
            continue
        if ranges and ranges[-1][2] == current and ranges[-1][1] + 1 == code:
            ranges[-1][1] = code
        else:
            ranges.append([code, code, current])
    return [tuple(r) for r in ranges]


def masks(selected: frozenset[str] | set[str], uni: Universe) -> list[tuple[int, int]]:
    """The fewest aligned blocks covering selected, as (value, mask) (SPEC 7)."""
    codes = sorted(code for _, code in uni.countries.values())
    floor, w = codes[0], codes[-1].bit_length()
    full = (1 << w) - 1
    wanted = sorted(uni.code(c) for c in selected)
    blocked = sorted(code for c, (_, code) in uni.countries.items() if c not in selected)

    def count(items: list[int], lo: int, hi: int) -> int:     # number of items in [lo, hi)
        return bisect.bisect_left(items, hi) - bisect.bisect_left(items, lo)

    out: list[tuple[int, int]] = []

    def visit(lo: int, size: int) -> None:
        if not count(wanted, lo, lo + size):
            return
        if not count(blocked, lo, lo + size) and lo >= floor:
            out.append((lo, full ^ (size - 1)))
            return
        visit(lo, size // 2)
        visit(lo + size // 2, size // 2)

    visit(0, 1 << w)
    return out


def runs(selected: frozenset[str] | set[str], uni: Universe) -> list[tuple[int, int]]:
    """The fewest ranges covering selected; a range may include unused codes."""
    out: list[list[int]] = []
    inside = False
    for code, c in sorted((code, c) for c, (_, code) in uni.countries.items()):
        if c in selected:
            if inside:
                out[-1][1] = code
            else:
                out.append([code, code])
            inside = True
        else:
            inside = False
    return [tuple(r) for r in out]
