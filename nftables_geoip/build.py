"""build: GeoIP data + links file + country range -> build directory (SPEC 4)."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .countries import Country, aggregate
from .geoip import check_dir, read_networks
from .ipmap import IPMapBuilder, read_ipmap, write_ipmap
from .layout import Layout, layout, parse_countries
from .links import read_links
from .rules import Universe

COUNTRIES = "countries.csv"
IPMAPS = {4: "ipmap4.csv", 6: "ipmap6.csv"}


@dataclass
class BuildResult:
    layout: Layout
    countries: dict[str, Country]
    ranges: dict[int, int]                   # family -> number of ranges
    dropped: int
    warnings: list[str]


def run_build(geoip: str | Path, countries_range: str, out: str | Path,
              links: str | Path | None = None) -> BuildResult:
    lo, size = parse_countries(countries_range)
    check_dir(geoip)
    builder = IPMapBuilder()

    def networks():
        for net in read_networks(geoip):
            builder.add(net)
            yield net

    countries, warnings = aggregate(networks())
    link_data = read_links(links, set(countries)) if links is not None else None
    lay = layout(countries, link_data, lo, size)
    maps, dropped = builder.ranges(lay.codes)
    if dropped:
        warnings.append(f"overlapping networks dropped: {dropped}")

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / COUNTRIES, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["code", "country", "continent", "ipv4", "ipv6_64", "networks", "lat", "lon"])
        for code in lay.order:
            c = countries[code]
            w.writerow([f"{lay.codes[code]:#x}", code, c.continent, c.ipv4, c.ipv6_64,
                        c.networks, f"{c.lat:.4f}", f"{c.lon:.4f}"])
    for family, name in IPMAPS.items():
        write_ipmap(out / name, family, maps[family])
    return BuildResult(lay, countries, {f: len(r) for f, r in maps.items()}, dropped, warnings)


def load_universe(build_dir: str | Path) -> Universe:
    countries = {}
    with open(Path(build_dir) / COUNTRIES, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            countries[row["country"]] = (row["continent"], int(row["code"], 0))
    return Universe(countries)


def ipmap_rows(build_dir: str | Path, family: int):
    return read_ipmap(Path(build_dir) / IPMAPS[family])
