def count_pairs_sum_bound(values, cmp, lim):
    """Pairs i < j with values[i] + values[j] cmp lim, integers only (ValueError otherwise). Sorting + two pointers: O(n log n)."""
    if not isinstance(lim, int) or not all(isinstance(v, int) for v in values):
        raise ValueError('integer values and bound required')
    s = sorted(values)
    size = len(s)
    total = size * (size - 1) // 2

    def le(n):
        c = 0
        i, j = 0, size - 1
        while i < j:
            if s[i] + s[j] <= n:
                c += j - i
                i += 1
            else:
                j -= 1
        return c

    return {'lt': lambda: le(lim - 1), 'le': lambda: le(lim), 'gt': lambda: total - le(lim), 'ge': lambda: total - le(lim - 1),
            'eq': lambda: le(lim) - le(lim - 1), 'ne': lambda: total - (le(lim) - le(lim - 1))}[cmp]()
