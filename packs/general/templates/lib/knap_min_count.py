def knap_min_count(items, target, once):
    """Fewest items summing exactly to target (each item at most once if once); None if impossible."""
    if target < 0:
        return None
    inf = float('inf')
    best = [0] + [inf] * target
    for v in items:
        rng = range(target, v - 1, -1) if once else range(v, target + 1)
        for s in rng:
            if best[s - v] + 1 < best[s]:
                best[s] = best[s - v] + 1
    return best[target] if best[target] != inf else None
