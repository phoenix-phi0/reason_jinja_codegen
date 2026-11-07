def digit_sums(values):
    """Decimal digit sum of the absolute value of each integer, in order."""
    result = []
    for v in values:
        if not isinstance(v, int):
            raise ValueError("integers only")
        n = -v if v < 0 else v
        total = 0
        while n:
            n, d = divmod(n, 10)
            total += d
        result.append(total)
    return result
