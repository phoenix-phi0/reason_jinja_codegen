def fold_integers(values, op):
    """Reduce a list of integers with gcd, lcm, bit_and, bit_or or bit_xor; None for an empty list."""
    import math
    import operator
    steps = {
        'gcd': math.gcd,
        'lcm': math.lcm,
        'bit_and': operator.and_,
        'bit_or': operator.or_,
        'bit_xor': operator.xor,
    }
    if op not in steps:
        raise ValueError('unknown operation')
    step = steps[op]
    magnitude = op in ('gcd', 'lcm')
    acc = None
    for v in values:
        if type(v) is not int:
            raise ValueError('integers only')
        if acc is None:
            acc = abs(v) if magnitude else v
        else:
            acc = step(acc, v)
    return acc
