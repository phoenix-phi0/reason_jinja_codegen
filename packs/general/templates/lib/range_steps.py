def range_steps(total, lo, hi, mod, form):
    """Ordered sequences of integer parts, each in lo..hi, that sum to total.

    form 'count': number of sequences (modulo mod when mod is not None); total 0 gives 1,
    negative total gives 0, hi < lo gives 0 for a positive total.
    form 'min_terms': fewest parts, None if impossible.
    form 'feasible': whether some sequence exists.
    Sliding-window prefix sums: O(total) for count, O(1) otherwise.
    """
    if form not in ('count', 'min_terms', 'feasible'):
        raise ValueError('unknown form')
    if lo < 1:
        raise ValueError('smallest part must be positive')
    if total < 0:
        return 0 if form == 'count' else (None if form == 'min_terms' else False)
    if form != 'count':
        if total == 0:
            best = 0
        elif hi < lo:
            best = None
        else:
            m = -(-total // hi)
            best = m if m * lo <= total else None
        return best if form == 'min_terms' else best is not None
    if total == 0:
        return 1 % mod if mod else 1
    if hi < lo:
        return 0
    pre = [0] * (total + 1)
    pre[0] = 1 % mod if mod else 1
    w = 0
    for i in range(1, total + 1):
        j = i - lo
        if j < 0:
            w = 0
        else:
            w = pre[j]
            low = i - hi - 1
            if low >= 0:
                w -= pre[low]
            if mod:
                w %= mod
        pre[i] = (pre[i - 1] + w) % mod if mod else pre[i - 1] + w
    return w
