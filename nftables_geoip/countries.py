"""Networks -> countries: continent, representative point and statistics (SPEC 2)."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from .geoip import Network

CONTINENTS = ("AF", "AN", "AS", "EU", "NA", "OC", "SA")
UNKNOWN = "ZZ"


@dataclass
class Country:
    code: str
    continent: str = UNKNOWN
    lat: float = 0.0
    lon: float = 0.0
    ipv4: int = 0
    ipv6_64: int = 0
    networks: int = 0


@dataclass
class _Acc:
    ipv4: int = 0
    ipv6_64: int = 0
    networks: int = 0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    continents: Counter = field(default_factory=Counter)


def country_of(net: Network) -> str:
    return net.country or UNKNOWN


def aggregate(networks: Iterable[Network]) -> tuple[dict[str, Country], list[str]]:
    """Group networks by country; return (country code -> Country, warnings)."""
    acc: defaultdict[str, _Acc] = defaultdict(_Acc)
    for net in networks:
        a = acc[country_of(net)]
        size = net.end - net.start + 1
        weight = size if net.family == 4 else max(1, size >> 64)
        if net.family == 4:
            a.ipv4 += size
        else:
            a.ipv6_64 += weight
        a.networks += 1
        if net.continent:
            a.continents[net.continent] += weight
        if net.lat is not None and net.lon is not None:
            la, lo = math.radians(net.lat), math.radians(net.lon)
            a.x += math.cos(la) * math.cos(lo)
            a.y += math.cos(la) * math.sin(lo)
            a.z += math.sin(la)

    countries: dict[str, Country] = {}
    warnings: list[str] = []
    for code in sorted(acc):
        a = acc[code]
        c = Country(code, ipv4=a.ipv4, ipv6_64=a.ipv6_64, networks=a.networks)
        if code != UNKNOWN and a.continents:
            (c.continent, top), = a.continents.most_common(1)
            total = sum(a.continents.values())
            if top < 0.99 * total:
                warnings.append(f"{code}: networks span several continents {dict(a.continents)}, using {c.continent}")
            if c.continent not in CONTINENTS:
                warnings.append(f"{code}: unknown continent code {c.continent!r}, using {UNKNOWN}")
                c.continent = UNKNOWN
        elif code != UNKNOWN:
            warnings.append(f"{code}: no continent code in the data, using {UNKNOWN}")
        if a.x or a.y or a.z:
            c.lat = math.degrees(math.atan2(a.z, math.hypot(a.x, a.y)))
            c.lon = math.degrees(math.atan2(a.y, a.x))
        else:
            warnings.append(f"{code}: no coordinates, placed at (0, 0)")
        countries[code] = c
    if UNKNOWN in countries:
        warnings.append(f"{countries[UNKNOWN].networks} networks have no country, assigned to {UNKNOWN}")
    return countries, warnings


def great_circle_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742.0 * math.asin(math.sqrt(min(1.0, h)))
