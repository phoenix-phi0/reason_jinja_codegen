def kth_value(values, k, order):
    """k-th element (1-based) of values in 'largest' (descending) or 'smallest' (ascending) order; None if k < 1 or k > len(values). Duplicates count separately."""
    if order not in ('largest', 'smallest'):
        raise ValueError('order must be largest or smallest')
    if k < 1 or k > len(values):
        return None
    ordered = sorted(values, reverse=(order == 'largest'))
    return ordered[k - 1]
