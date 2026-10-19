"""IP ranges -> country codes (SPEC 1.1 and 4)."""
from __future__ import annotations

import csv
import ipaddress
from pathlib import Path
from typing import Iterator

from .countries import country_of
from .geoip import Network

Ranges = list[tuple[int, int, int]]          # (first, last, code), inclusive


class IPMapBuilder:
    """Collect networks, then sort and merge them into ranges (SPEC 4)."""

    def __init__(self):
        self.rows: dict[int, list[tuple[int, int, str]]] = {4: [], 6: []}

    def add(self, net: Network) -> None:
        self.rows[net.family].append((net.start, -net.end, country_of(net)))

    def ranges(self, codes: dict[str, int]) -> tuple[dict[int, Ranges], int]:
        """Return (ranges per family, number of dropped networks).

        Networks are sorted by first address, the larger one first on a tie. A network
        overlapping the previous kept one is dropped. Adjacent networks with the same
        code are merged."""
        out: dict[int, Ranges] = {}
        dropped = 0
        for family, rows in self.rows.items():
            rows.sort()
            merged: list[list[int]] = []
            for start, neg_end, country in rows:
                end, code = -neg_end, codes[country]
                if merged and start <= merged[-1][1]:
                    dropped += 1
                elif merged and merged[-1][2] == code and merged[-1][1] + 1 == start:
                    merged[-1][1] = end
                else:
                    merged.append([start, end, code])
            out[family] = [tuple(r) for r in merged]
        return out, dropped


def address(family: int, n: int) -> str:
    return str(ipaddress.IPv4Address(n) if family == 4 else ipaddress.IPv6Address(n))


def write_ipmap(path: str | Path, family: int, ranges: Ranges) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["start", "end", "code"])
        for start, end, code in ranges:
            w.writerow([address(family, start), address(family, end), f"{code:#x}"])


def read_ipmap(path: str | Path) -> Iterator[tuple[str, str, int]]:
    """Yield (first address, last address, code) for each row."""
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            yield row["start"], row["end"], int(row["code"], 0)
