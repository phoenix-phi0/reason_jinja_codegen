def interval_merge(pairs, reach):
    """Merge intervals sorted by start: the next one joins when its start < current end + reach."""
    merged = []
    for s, e in sorted(pairs):
        if merged and s < merged[-1][1] + reach:
            if e > merged[-1][1]:
                merged[-1][1] = e
        else:
            merged.append([s, e])
    return merged
