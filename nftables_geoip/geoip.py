"""GeoLite2 City CSV -> network records (SPEC 1.1)."""
from __future__ import annotations

import csv
import socket
from operator import itemgetter
from pathlib import Path
from typing import Iterator, NamedTuple

LOCATIONS = "GeoLite2-City-Locations-en.csv"
BLOCKS = {4: "GeoLite2-City-Blocks-IPv4.csv", 6: "GeoLite2-City-Blocks-IPv6.csv"}
ADDRESS = {4: (socket.AF_INET, 32), 6: (socket.AF_INET6, 128)}   # socket family, bits


class Network(NamedTuple):
    family: int            # 4 or 6
    start: int             # first address, inclusive
    end: int               # last address, inclusive
    country: str           # ISO 3166-1 alpha-2, "" if unknown
    continent: str         # continent code from the database, "" if unknown
    lat: float | None
    lon: float | None


def _float(s: str) -> float | None:
    return float(s) if s else None


def check_dir(directory: str | Path) -> Path:
    d = Path(directory)
    missing = [name for name in (LOCATIONS, *BLOCKS.values()) if not (d / name).is_file()]
    if missing:
        raise FileNotFoundError(f"{d}: missing {', '.join(missing)}")
    return d


def _rows(path: Path, *columns: str) -> Iterator[tuple[str, ...]]:
    """Yield the given columns of each row, located by the header."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = csv.reader(f)
        yield from map(itemgetter(*map(next(rows).index, columns)), rows)


def read_networks(directory: str | Path) -> Iterator[Network]:
    d = check_dir(directory)
    locations = {gid: (country, continent) for gid, country, continent in
                 _rows(d / LOCATIONS, "geoname_id", "country_iso_code", "continent_code")}
    for family, name in BLOCKS.items():
        af, bits = ADDRESS[family]
        for network, gid, registered, lat, lon in _rows(
                d / name, "network", "geoname_id", "registered_country_geoname_id",
                "latitude", "longitude"):
            country, continent = locations.get(gid, ("", ""))
            if not country:
                country, continent = locations.get(registered, ("", ""))
            addr, _, prefix = network.partition("/")
            start = int.from_bytes(socket.inet_pton(af, addr))
            end = start | (1 << bits - int(prefix)) - 1
            yield Network(family, start, end, country, continent, _float(lat), _float(lon))
