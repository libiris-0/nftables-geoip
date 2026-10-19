"""Command line: build, compile and query."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .build import load_universe, run_build
from .layout import LayoutError
from .links import LinksError
from .nft import write_script
from .rules import Evaluator, RuleError, compile_rules, masks, parse, runs


def warn(messages) -> None:
    for m in messages:
        print(f"warning: {m}", file=sys.stderr)


def cmd_build(a) -> int:
    r = run_build(a.geoip, a.countries, a.out, a.links)
    lay = r.layout
    print(f"{len(r.countries)} countries, continent block size {lay.block_size}", file=sys.stderr)
    for g, (lo, hi) in lay.blocks.items():
        print(f"  {g}  {lo:#x}-{hi:#x}", file=sys.stderr)
    print(f"ipmap4: {r.ranges[4]} ranges, ipmap6: {r.ranges[6]} ranges", file=sys.stderr)
    warn(r.warnings)
    return 0


def cmd_compile(a) -> int:
    if not a.table.strip():
        raise ValueError("--table must not be empty")
    rules = Path(a.rules).read_text(encoding="utf-8")
    uni = load_universe(a.build)
    res = compile_rules(rules, uni)
    counts = write_script(a.output, a.table, a.build, uni, res)
    print(", ".join(f"{name}: {n} elements" for name, n in counts.items()), file=sys.stderr)
    for n in res.notes:
        print(f"note: {n}", file=sys.stderr)
    warn(res.warnings)
    return 0


def cmd_query(a) -> int:
    uni = load_universe(a.build)
    text = Path(a.rules).read_text(encoding="utf-8") if a.rules else ""
    ev = Evaluator(uni, parse(text + f"\n_query_ = {a.expr}\n"))
    selected = ev.region("_query_")
    covered = runs(selected, uni)
    covering = masks(selected, uni)
    print(f"{len(selected)} countries, {len(covered)} ranges, {len(covering)} masks")
    print("ranges: " + " ".join(f"{lo:#x}-{hi:#x}" if hi != lo else f"{lo:#x}" for lo, hi in covered))
    print("masks: " + " ".join(f"{v:#x}/{m:#x}" for v, m in covering))
    print("countries: " + " ".join(sorted(selected, key=uni.code)))
    warn(ev.warnings)
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python3 -m nftables_geoip")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the country codes and IP maps")
    b.add_argument("--geoip", required=True, help="GeoLite2 City CSV directory")
    b.add_argument("--countries", required=True, help="country range, e.g. 0x800-0xfff")
    b.add_argument("--links", help="links file links.txt")
    b.add_argument("--out", required=True, help="build directory")
    c = sub.add_parser("compile", help="compile a rules file into an nft script")
    c.add_argument("build", help="build directory")
    c.add_argument("rules", help="rules file")
    c.add_argument("--table", required=True, help="table holding the three maps, e.g. \"inet filter\"")
    c.add_argument("-o", "--output", required=True, help="output nft script")
    q = sub.add_parser("query", help="show the countries, ranges and masks an expression selects")
    q.add_argument("build", help="build directory")
    q.add_argument("--rules", help="rules file whose definitions the expression may use")
    q.add_argument("expr")
    return p


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    commands = {"build": cmd_build, "compile": cmd_compile, "query": cmd_query}
    try:
        return commands[a.cmd](a)
    except BrokenPipeError:
        return 0
    except (RuleError, LayoutError, LinksError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
