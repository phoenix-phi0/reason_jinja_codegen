def count_pairs_difference_bound(values, cmp, lim):
    """Pairs i < j with (values[i] - values[j]) cmp lim, cmp in lt le gt ge eq ne; integers only (ValueError otherwise). Fenwick tree: O(n log n)."""
    if not isinstance(lim, int) or not all(isinstance(v, int) for v in values):
        raise ValueError('integer values and bound required')
    from bisect import bisect_left, bisect_right
    vals = sorted(set(values))
    n = len(vals)
    index = {v: i + 1 for i, v in enumerate(vals)}
    tree = [0] * (n + 1)
    good = 0
    for j, b in enumerate(values):
        x = b + lim
        less = 0
        i = bisect_left(vals, x)
        while i > 0:
            less += tree[i]
            i -= i & -i
        leq = 0
        i = bisect_right(vals, x)
        while i > 0:
            leq += tree[i]
            i -= i & -i
        good += {'lt': less, 'le': leq, 'gt': j - leq, 'ge': j - less, 'eq': leq - less, 'ne': j - (leq - less)}[cmp]
        i = index[b]
        while i <= n:
            tree[i] += 1
            i += i & -i
    return good
