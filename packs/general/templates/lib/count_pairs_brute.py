def count_pairs_brute(values, predicate):
    """Pairs i < j with predicate(values[i], values[j]). O(n^2); the fallback when no faster function applies."""
    good = 0
    for i in range(len(values)):
        a = values[i]
        for j in range(i + 1, len(values)):
            if predicate(a, values[j]):
                good += 1
    return good
