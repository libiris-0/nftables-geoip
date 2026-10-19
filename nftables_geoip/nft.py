"""compile output: an nft script replacing the three maps (SPEC 6.2)."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, TextIO

from .build import ipmap_rows
from .rules import Compiled, Universe

CHUNK = 20000                                # maximum elements per add element
MAPS = {4: "geo4", 6: "geo6"}


def _key(lo: str, hi: str) -> str:
    return lo if lo == hi else f"{lo}-{hi}"


def write_map(f: TextIO, table: str, name: str, elements: Iterable[str]) -> int:
    """Write flush map and batched add element commands; return the number of elements."""
    f.write(f"flush map {table} {name}\n")
    batch: list[str] = []
    total = 0

    def flush() -> None:
        f.write(f"add element {table} {name} {{\n")
        f.write(",\n".join(batch))
        f.write("\n}\n")

    for element in elements:
        batch.append(f"  {element}")
        total += 1
        if len(batch) == CHUNK:
            flush()
            batch = []
    if batch:
        flush()
    return total


def write_script(path: str | Path, table: str, build_dir: str | Path, uni: Universe,
                 compiled: Compiled) -> dict[str, int]:
    """Write the nft script; return the number of elements in each map."""
    classed = {uni.code(c) for c in compiled.classes}

    def addresses(family: int):
        for lo, hi, code in ipmap_rows(build_dir, family):
            if code in classed:
                yield f"{_key(lo, hi)} : {code:#x}"

    def classes():
        for lo, hi, cls in compiled.geoclass:
            yield f"{_key(f'{lo:#x}', f'{hi:#x}')} : {cls:#x}"
        if compiled.default is not None:
            yield f"* : {compiled.default:#x}"

    counts = {}
    with open(path, "w", encoding="utf-8") as f:
        for family, name in MAPS.items():
            counts[name] = write_map(f, table, name, addresses(family))
        counts["geoclass"] = write_map(f, table, "geoclass", classes())
    return counts
