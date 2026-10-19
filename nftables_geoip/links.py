"""The links file links.txt (SPEC 1.2)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

KINDS = ("cable", "border")
COUNTRY = re.compile(r"[A-Z]{2}")


class LinksError(ValueError):
    pass


@dataclass
class Links:
    cables: list[frozenset[str]] = field(default_factory=list)
    borders: set[tuple[str, str]] = field(default_factory=set)   # ordered pairs (a, b), a < b


def parse_links(text: str, present: set[str], where: str = "links.txt") -> Links:
    """Parse a links file, keeping only the countries in present."""
    links = Links()
    seen_ids: dict[str, int] = {}
    for lineno, raw in enumerate(text.splitlines(), 1):
        fields = raw.split("#", 1)[0].split()
        if not fields:
            continue
        here = f"{where}:{lineno}"
        kind, _, ident = fields[0].partition(":")
        if kind not in KINDS:
            raise LinksError(f"{here}: unknown kind {kind!r}, must be cable or border")
        if ident:
            if ident in seen_ids:
                raise LinksError(f"{here}: id {ident!r} already used on line {seen_ids[ident]}")
            seen_ids[ident] = lineno
        bad = [c for c in fields[1:] if not COUNTRY.fullmatch(c)]
        if bad:
            raise LinksError(f"{here}: not country codes: {' '.join(bad)}")
        countries = set(fields[1:])
        if len(countries) < 2:
            raise LinksError(f"{here}: at least two countries are required")
        if kind == "border" and len(countries) != 2:
            raise LinksError(f"{here}: a border line must name exactly two countries")
        countries &= present
        if len(countries) < 2:
            continue
        if kind == "cable":
            links.cables.append(frozenset(countries))
        else:
            a, b = sorted(countries)
            links.borders.add((a, b))
    return links


def read_links(path: str | Path, present: set[str]) -> Links:
    p = Path(path)
    return parse_links(p.read_text(encoding="utf-8"), present, str(p))
