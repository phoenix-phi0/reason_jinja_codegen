def interval_covered_length(pairs, reach, lo, hi):
    """Total length of points covered by between lo and hi intervals (lo >= 1; hi None = no upper limit);
    interval [s, e] covers [s, e + reach)."""
    if lo < 1:
        raise ValueError('lo must be at least 1')
    events = []
    for s, e in pairs:
        events.append((s, 1))
        events.append((e + reach, -1))
    events.sort()
    depth = 0
    prev = None
    covered = 0
    for x, delta in events:
        if prev is not None and depth >= lo and (hi is None or depth <= hi):
            covered += x - prev
        depth += delta
        prev = x
    return covered
