"""Code layout: country range, continent blocks, ordering and code assignment (SPEC 3)."""
from __future__ import annotations

import itertools
from dataclasses import dataclass

from . import pathsearch
from .countries import Country, great_circle_km
from .links import Links

GEO_WEIGHT = 1.5          # distance cost per 1000 km
CABLE_WEIGHT = 1.0        # per shared cable
BORDER_WEIGHT = 1.0       # for a border
REFINE_ROUNDS = 5


class LayoutError(ValueError):
    pass


@dataclass
class Layout:
    block_size: int                          # continent block size S
    blocks: dict[str, tuple[int, int]]       # continent -> (first, last), inclusive, in code order
    codes: dict[str, int]                    # country -> code
    order: list[str]                         # countries sorted by code


def parse_countries(text: str) -> tuple[int, int]:
    """`LO-HI` -> (LO, N). The range must be an aligned power-of-two block (SPEC 3.1)."""
    try:
        lo_text, hi_text = text.split("-")
        lo, hi = int(lo_text, 0), int(hi_text, 0)
    except ValueError:
        raise LayoutError(f"country range {text!r} must be LO-HI, e.g. 0x800-0xfff") from None
    size = hi - lo + 1
    if lo < 0 or size <= 0 or size & (size - 1) or lo % size:
        raise LayoutError(f"country range {text} is not an aligned power-of-two block")
    return lo, size


def choose_block_size(group_sizes: list[int], size: int) -> int:
    """The largest power of two S with countries per continent <= S and N / S >= continents (SPEC 3.2)."""
    s = size
    while s >= 1:
        if max(group_sizes) <= s and size // s >= len(group_sizes):
            return s
        s //= 2
    raise LayoutError(f"{len(group_sizes)} continents do not fit in a country range of size {size}")


def cost_matrix(ids: list[str], countries: dict[str, Country], links: Links | None) -> list[list[float]]:
    """C[i][j] = 1.5 * distance / 1000 - W[i][j] (SPEC 3.3)."""
    n = len(ids)
    idx = {c: i for i, c in enumerate(ids)}
    W = [[0.0] * n for _ in range(n)]
    if links is not None:
        for cable in links.cables:
            members = sorted(idx[c] for c in cable if c in idx)
            for a, b in itertools.combinations(members, 2):
                W[a][b] += CABLE_WEIGHT
                W[b][a] += CABLE_WEIGHT
        for a, b in links.borders:
            if a in idx and b in idx:
                W[idx[a]][idx[b]] += BORDER_WEIGHT
                W[idx[b]][idx[a]] += BORDER_WEIGHT
    pts = [(countries[c].lat, countries[c].lon) for c in ids]
    C = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            v = GEO_WEIGHT * great_circle_km(pts[i], pts[j]) / 1000.0 - W[i][j]
            C[i][j] = C[j][i] = v
    return C


def _arrange(paths: dict[str, list[int]], C) -> tuple[tuple[str, ...], tuple[bool, ...]]:
    """Order of the continent blocks and direction of each block (SPEC 3.4 step 2)."""
    groups = sorted(paths)
    best = None
    for perm in itertools.permutations(groups):
        # state: whether the current block is reversed -> (cost, chosen directions)
        states = {False: (0.0, ()), True: (0.0, ())}
        for k, g in enumerate(perm):
            nxt = {}
            for flip in (False, True):
                head = paths[g][-1] if flip else paths[g][0]
                if k == 0:
                    nxt[flip] = (0.0, (flip,))
                    continue
                options = []
                for prev_flip, (cost, flips) in states.items():
                    p = paths[perm[k - 1]]
                    tail = p[0] if prev_flip else p[-1]
                    options.append((round(cost + C[tail][head], 9), flips + (flip,)))
                nxt[flip] = min(options)
            states = nxt
        cost, flips = min(states.values())
        score = (cost, perm, flips)
        if best is None or score < best:
            best = score
    return best[1], best[2]


def _oriented(path: list[int], flip: bool) -> list[int]:
    return path[::-1] if flip else path


def place(seq: list[int], lo: int, size: int, C) -> list[int]:
    """Place the countries of seq in order into the aligned block [lo, lo + size) so that
    every aligned sub-block holds a contiguous stretch of seq (SPEC 3.5). Each halving
    cuts at the weakest link between neighbours, biased towards the middle.
    Requires 1 <= len(seq) <= size."""
    n = len(seq)
    if n == 1:
        return [lo]
    half = size // 2
    inner = range(max(1, n - half), min(n - 1, half) + 1)
    floor = min(C[seq[k - 1]][seq[k]] for k in inner)

    def score(k: int) -> tuple:
        weakness = C[seq[k - 1]][seq[k]] - floor
        balance = 2 * min(k, n - k) / n
        return (round(weakness * balance, 9), -abs(2 * k - n), -k)
    cut = max(inner, key=score)
    return place(seq[:cut], lo, half, C) + place(seq[cut:], lo + half, half, C)


def layout(countries: dict[str, Country], links: Links | None, lo: int, size: int) -> Layout:
    ids = sorted(countries)
    if not ids:
        raise LayoutError("no countries in the data")
    members: dict[str, list[int]] = {}
    for i, c in enumerate(ids):
        members.setdefault(countries[c].continent, []).append(i)
    block = choose_block_size([len(m) for m in members.values()], size)
    C = cost_matrix(ids, countries, links)
    key = lambda seq: tuple(ids[i] for i in seq)   # noqa: E731  ties broken by country code

    paths = {g: pathsearch.solve(m, C, key=key) for g, m in members.items()}
    perm, flips = _arrange(paths, C)
    for _ in range(REFINE_ROUNDS):                           # anchored refinement
        changed = False
        for k, g in enumerate(perm):
            left = _oriented(paths[perm[k - 1]], flips[k - 1])[-1] if k > 0 else None
            right = _oriented(paths[perm[k + 1]], flips[k + 1])[0] if k + 1 < len(perm) else None
            current = _oriented(paths[g], flips[k])
            better = pathsearch.solve(members[g], C, left, right,
                                      initial=current, key=key)
            if pathsearch.path_cost(better, C, left, right) < \
                    pathsearch.path_cost(current, C, left, right) - pathsearch.EPS:
                paths[g] = _oriented(better, flips[k])
                changed = True
        new_perm, new_flips = _arrange(paths, C)
        if not changed and (new_perm, new_flips) == (perm, flips):
            break
        perm, flips = new_perm, new_flips

    codes: dict[str, int] = {}
    blocks: dict[str, tuple[int, int]] = {}
    order: list[str] = []
    for k, (g, flip) in enumerate(zip(perm, flips)):
        start = lo + k * block
        blocks[g] = (start, start + block - 1)
        seq = _oriented(paths[g], flip)
        for i, code in zip(seq, place(seq, start, block, C)):
            codes[ids[i]] = code
            order.append(ids[i])
    return Layout(block, blocks, codes, order)
