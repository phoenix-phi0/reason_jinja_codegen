def knap_count_ways(items, target, once, ordered, mod):
    """Number of ways to form target: multisets (ordered=False) or sequences (ordered=True, unlimited only);
    each list position at most once if once. mod is None or the modulus.
    Precondition: with unlimited use, item values are distinct (deduplicate first)."""
    if target < 0:
        return 0
    ways = [1] + [0] * target
    if ordered:
        for s in range(1, target + 1):
            for v in items:
                if v <= s:
                    ways[s] += ways[s - v]
            if mod:
                ways[s] %= mod
    else:
        for v in items:
            rng = range(target, v - 1, -1) if once else range(v, target + 1)
            for s in rng:
                ways[s] += ways[s - v]
                if mod:
                    ways[s] %= mod
    return ways[target] % mod if mod else ways[target]
