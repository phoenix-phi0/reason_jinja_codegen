def pair_extreme(values, op, which):
    n = len(values)
    if n < 2:
        return None
    want_max = which == 'max'
    if op == 'sum':
        s = sorted(values)
        return s[-1] + s[-2] if want_max else s[0] + s[1]
    if op == 'abs_difference':
        s = sorted(values)
        if want_max:
            return s[-1] - s[0]
        return min(s[i + 1] - s[i] for i in range(n - 1))
    if op not in ('difference', 'reverse_difference'):
        raise ValueError('unknown pair operation: ' + str(op))
    # work with b - a (later minus earlier); a - b is its negation, so max and min swap
    reverse = op == 'reverse_difference'
    need_max = want_max if reverse else not want_max
    low = high = values[0]
    best = None
    for b in values[1:]:
        cand = b - low if need_max else b - high
        if best is None or (cand > best if need_max else cand < best):
            best = cand
        if b < low:
            low = b
        if b > high:
            high = b
    return best if reverse else -best
