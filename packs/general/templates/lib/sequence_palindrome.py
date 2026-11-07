def sequence_palindrome(values, form, tolerance):
    """Compare a string or list with its reverse. form 'check': True when at most tolerance (None = 0) mirrored pairs differ; 'mismatch_count': number of mirrored pairs (i, n-1-i), i < n-1-i, whose elements differ; 'first_mismatch': smallest such i, or -1. O(n)."""
    n = len(values)
    bad = 0
    first = -1
    for i in range(n // 2):
        if values[i] != values[n - 1 - i]:
            if first < 0:
                first = i
            bad += 1
    if form == 'check':
        return bad <= (tolerance or 0)
    if form == 'mismatch_count':
        return bad
    if form == 'first_mismatch':
        return first
    raise ValueError('unknown form')
