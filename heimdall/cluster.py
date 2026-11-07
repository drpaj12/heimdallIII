"""k-means and affinity propagation on small feature tables (standard library only, fixed seed)."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from typing import Any

Vec = Sequence[float]
SEED = 20261106
KS = (2, 4, 8, 16, 32)
AP_CAP = 400
SIL_CAP = 1500


def sqd(a: Vec, b: Vec) -> float:
    return sum((x - y) * (x - y) for x, y in zip(a, b, strict=True))


def kmeans(
    pts: Sequence[Vec], weights: Sequence[float], k: int, seed: int = SEED, iters: int = 60
) -> list[int]:
    """Weighted Lloyd k-means with k-means++ start. Returns a label per point; k <= len(pts)."""
    n = len(pts)
    rnd = random.Random(seed + k)
    first = rnd.randrange(n)
    cent = [list(pts[first])]
    d2 = [sqd(p, cent[0]) for p in pts]
    while len(cent) < k:
        w = [d * wt for d, wt in zip(d2, weights, strict=True)]
        tot = sum(w)
        if tot <= 0:
            break
        r = rnd.random() * tot
        acc, pick = 0.0, n - 1
        for i, x in enumerate(w):
            acc += x
            if acc >= r and x > 0:
                pick = i
                break
        cent.append(list(pts[pick]))
        d2 = [min(d, sqd(p, cent[-1])) for d, p in zip(d2, pts, strict=True)]
    labels = [0] * n
    for _ in range(iters):
        changed = False
        for i, p in enumerate(pts):
            best = min(range(len(cent)), key=lambda c: (sqd(p, cent[c]), c))
            if best != labels[i] or _ == 0:
                changed = changed or best != labels[i]
                labels[i] = best
        dim = len(pts[0])
        sums = [[0.0] * dim for _ in cent]
        wsum = [0.0] * len(cent)
        for p, lab, wt in zip(pts, labels, weights, strict=True):
            wsum[lab] += wt
            row = sums[lab]
            for j in range(dim):
                row[j] += wt * p[j]
        for c in range(len(cent)):
            if wsum[c] > 0:
                cent[c] = [v / wsum[c] for v in sums[c]]
        if not changed and _ > 0:
            break
    return _compact(labels)


def _compact(labels: Sequence[int]) -> list[int]:
    """Renumber labels 0.. in order of first appearance."""
    m: dict[int, int] = {}
    return [m.setdefault(x, len(m)) for x in labels]


def silhouette(pts: Sequence[Vec], weights: Sequence[float], labels: Sequence[int]) -> float:
    """Mean silhouette over (a sample of) the points, weighted by multiplicity. -1 if < 2 clusters."""
    ks = sorted(set(labels))
    if len(ks) < 2:
        return -1.0
    idx = list(range(len(pts)))
    if len(idx) > SIL_CAP:
        idx = random.Random(SEED).sample(idx, SIL_CAP)
    members: dict[int, list[int]] = {k: [] for k in ks}
    for i in idx:
        members[labels[i]].append(i)
    num = den = 0.0
    for i in idx:
        mean: dict[int, float] = {}
        for k, mem in members.items():
            tot = sum(weights[j] for j in mem if j != i)
            if tot > 0:
                mean[k] = sum(math.sqrt(sqd(pts[i], pts[j])) * weights[j] for j in mem if j != i) / tot
        own = labels[i]
        if own not in mean:
            s = 0.0  # a singleton scores 0
        else:
            others = [v for k, v in mean.items() if k != own]
            if not others:
                s = 0.0
            else:
                a, b = mean[own], min(others)
                s = (b - a) / max(a, b) if max(a, b) > 0 else 0.0
        num += s * weights[i]
        den += weights[i]
    return num / den if den else -1.0


def affinity(
    pts: Sequence[Vec],
    weights: Sequence[float],
    damping: float = 0.9,
    iters: int = 200,
    stable: int = 15,
) -> list[int]:
    """Affinity propagation (Frey and Dueck 2007): similarity = -squared distance, preference = median
    similarity. The points are distinct vectors; `weights` (multiplicity) is accepted for the caller's
    ordering and does not enter the messages. Returns the cluster number per point."""
    n = len(pts)
    if n == 1:
        return [0]
    s = [[-sqd(pts[i], pts[j]) for j in range(n)] for i in range(n)]
    off = sorted(s[i][j] for i in range(n) for j in range(n) if i != j)
    pref = off[len(off) // 2]
    for i in range(n):
        s[i][i] = pref
    r = [[0.0] * n for _ in range(n)]
    a = [[0.0] * n for _ in range(n)]
    last: list[int] = []
    same = 0
    for _ in range(iters):
        for i in range(n):
            row = [a[i][k] + s[i][k] for k in range(n)]
            top = max(range(n), key=lambda k: row[k])
            first = row[top]
            second = max((row[k] for k in range(n) if k != top), default=first)
            for k in range(n):
                new = s[i][k] - (second if k == top else first)
                r[i][k] = damping * r[i][k] + (1 - damping) * new
        for k in range(n):
            pos = [max(0.0, r[i][k]) for i in range(n)]
            total = sum(pos) - pos[k] + r[k][k]
            for i in range(n):
                if i == k:
                    new = total - r[k][k]
                else:
                    new = min(0.0, total - pos[i])
                a[i][k] = damping * a[i][k] + (1 - damping) * new
        ex = [k for k in range(n) if a[k][k] + r[k][k] > 0]
        if ex == last and ex:
            same += 1
            if same >= stable:
                break
        else:
            same = 0
        last = ex
    ex = [k for k in range(n) if a[k][k] + r[k][k] > 0]
    if not ex:
        ex = [min(range(n), key=lambda k: sum(-s[k][j] for j in range(n)))]
    lab = [min(ex, key=lambda e: (sqd(pts[i], pts[e]), e)) for i in range(n)]
    for e in ex:
        lab[e] = e
    return _compact(lab)


def distinct(rows: Sequence[Vec]) -> tuple[list[Vec], list[float], list[int]]:
    """Distinct vectors, their multiplicity and the index of each row's vector."""
    seen: dict[tuple[float, ...], int] = {}
    pts: list[Vec] = []
    cnt: list[float] = []
    of: list[int] = []
    for row in rows:
        key = tuple(round(v, 6) for v in row)
        j = seen.get(key)
        if j is None:
            j = seen[key] = len(pts)
            pts.append(key)
            cnt.append(0.0)
        cnt[j] += 1.0
        of.append(j)
    return pts, cnt, of


def run_kmeans(rows: Sequence[Vec]) -> dict[str, Any]:
    """k-means for every k in KS (capped by the number of distinct vectors); default = best silhouette."""
    pts, cnt, of = distinct(rows)
    runs: list[dict[str, Any]] = []
    sils: list[float] = []
    for k in KS:
        if k > len(pts):
            continue
        lab = kmeans(pts, cnt, k)
        sil = round(silhouette(pts, cnt, lab), 4)
        sils.append(sil)
        runs.append({"k": k, "silhouette": sil, "labels": [lab[j] for j in of]})
    best = max(range(len(runs)), key=lambda i: (sils[i], -i)) if runs else -1
    return {"distinct": len(pts), "runs": runs, "default": best}


def run_affinity(rows: Sequence[Vec]) -> dict[str, Any]:
    """Affinity propagation on the distinct vectors (at most AP_CAP most frequent; the rest join the
    nearest exemplar of the clustered ones)."""
    pts, cnt, of = distinct(rows)
    capped = len(pts) > AP_CAP
    order = sorted(range(len(pts)), key=lambda j: (-cnt[j], j))[:AP_CAP] if capped else list(range(len(pts)))
    sub = [pts[j] for j in order]
    sub_lab = affinity(sub, [cnt[j] for j in order])
    lab = [-1] * len(pts)
    for j, lb in zip(order, sub_lab, strict=True):
        lab[j] = lb
    if capped:
        exemplars: dict[int, int] = {}
        for j, lb in zip(order, sub_lab, strict=True):
            exemplars.setdefault(lb, j)
        for j in range(len(pts)):
            if lab[j] < 0:
                lab[j] = min(exemplars.items(), key=lambda kv: (sqd(pts[j], pts[kv[1]]), kv[0]))[0]
    labels = [lab[j] for j in of]
    return {
        "distinct": len(pts),
        "capped": capped,
        "cap": AP_CAP,
        "clustered": len(order),
        "k": len(set(labels)),
        "labels": labels,
    }
