def interval_max_overlap(pairs, reach):
    """Maximum number of intervals active at one point; interval [s, e] is active on [s, e + reach)."""
    events = []
    for s, e in pairs:
        events.append((s, 1))
        events.append((e + reach, -1))
    events.sort()
    current = best = 0
    for _, delta in events:
        current += delta
        if current > best:
            best = current
    return best
