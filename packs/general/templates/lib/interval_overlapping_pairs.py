def interval_overlapping_pairs(pairs, reach):
    """Number of pairs i < j with max(s_i, s_j) < min(e_i, e_j) + reach, assuming s < e + reach for every interval.
    Sort by start; for each interval count later starts below its end + reach (binary search): O(n log n)."""
    from bisect import bisect_left
    ordered = sorted(pairs)
    starts = [s for s, _ in ordered]
    total = 0
    for i, (_, e) in enumerate(ordered):
        total += max(0, bisect_left(starts, e + reach) - (i + 1))
    return total
