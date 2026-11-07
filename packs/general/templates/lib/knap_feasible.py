def knap_feasible(items, target, once):
    """Whether target can be formed exactly (each item at most once if once)."""
    if target < 0:
        return False
    can = [True] + [False] * target
    for v in items:
        rng = range(target, v - 1, -1) if once else range(v, target + 1)
        for s in rng:
            if can[s - v]:
                can[s] = True
    return can[target]
