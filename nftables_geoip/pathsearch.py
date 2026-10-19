"""Minimum-cost open paths over a symmetric cost matrix (SPEC 3.4 step 1).

Used to order the countries of one continent. Either end of a path may attach to a
fixed anchor, which counts towards the cost but never moves. The search is deterministic.
"""
from __future__ import annotations

from typing import Sequence

Matrix = Sequence[Sequence[float]]
EPS = 1e-9


def path_cost(seq: Sequence[int], C: Matrix, left: int | None = None,
              right: int | None = None) -> float:
    nodes = [n for n in (left, *seq, right) if n is not None]
    return sum(C[a][b] for a, b in zip(nodes, nodes[1:]))


# The search runs on a matrix with one extra node, the free end, that costs nothing to
# reach. A path end without an anchor is attached to it.

def _two_opt(seq: list[int], C: Matrix, left: int, right: int) -> bool:
    """Apply the first reversal of seq[i..j] that lowers the cost; return whether one was found."""
    path = [left, *seq, right]
    for i in range(1, len(seq)):
        for j in range(i + 1, len(seq) + 1):
            old = C[path[i - 1]][path[i]] + C[path[j]][path[j + 1]]
            new = C[path[i - 1]][path[j]] + C[path[i]][path[j + 1]]
            if new < old - EPS:
                seq[i - 1:j] = seq[i - 1:j][::-1]
                return True
    return False


def _or_opt(seq: list[int], C: Matrix, left: int, right: int) -> bool:
    """Apply the first move that lowers the cost: a segment of 1 to 3 nodes, possibly reversed, moved anywhere."""
    for length in (1, 2, 3):
        for i in range(len(seq) - length + 1):
            seg = seq[i:i + length]
            both = (seg, seg[::-1])
            rest = [left, *seq[:i], *seq[i + length:], right]
            before, after = rest[i], rest[i + 1]
            gain = C[before][seg[0]] + C[seg[-1]][after] - C[before][after]
            for k, (p, q) in enumerate(zip(rest, rest[1:])):
                for s in both:
                    cost = C[p][s[0]] + C[s[-1]][q] - C[p][q]
                    if cost < gain - EPS:
                        seq[:] = rest[1:k + 1] + s + rest[k + 1:-1]
                        return True
    return False


def _local_search(seq: Sequence[int], C: Matrix, left: int, right: int) -> list[int]:
    """Repeat 2-opt and or-opt until neither improves the path."""
    seq = list(seq)
    while _two_opt(seq, C, left, right) or _or_opt(seq, C, left, right):
        pass
    return seq


def greedy(start: int, nodes: Sequence[int], C: Matrix) -> list[int]:
    """Nearest-neighbour path from start; ties go to the lowest node."""
    path, todo = [start], set(nodes) - {start}
    while todo:
        last = path[-1]
        nxt = min(todo, key=lambda x: (C[last][x], x))
        path.append(nxt)
        todo.remove(nxt)
    return path


def solve(nodes: Sequence[int], C: Matrix, left: int | None = None,
          right: int | None = None, initial: Sequence[int] | None = None,
          key=None) -> list[int]:
    """Run a local search from a greedy path out of every node (and from initial); return
    the cheapest path.
    Ties are broken by key(seq), by default the node numbers."""
    nodes = sorted(nodes)
    if len(nodes) <= 1:
        return list(nodes)
    key = key or (lambda s: tuple(s))
    candidates = [greedy(s, nodes, C) for s in nodes]
    if initial is not None:
        candidates.append(list(initial))
    free = len(C)
    D = [list(row) + [0.0] for row in C] + [[0.0] * (free + 1)]
    ends = (free if left is None else left, free if right is None else right)
    best = None
    for cand in candidates:
        seq = _local_search(cand, D, *ends)
        score = (round(path_cost(seq, C, left, right), 9), key(seq))
        if best is None or score < best[0]:
            best = (score, seq)
    return best[1]
