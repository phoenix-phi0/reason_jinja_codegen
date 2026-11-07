def bracket_scan(tokens, pairs, mode):
    """Stack scan of a token sequence against bracket pairs [[open, close], ...]; other tokens are ignored.
    mode 'balanced': True when every bracket is closed by its partner in proper nesting.
    mode 'max_depth': deepest nesting level, or -1 when not balanced.
    mode 'error_index': -1 when balanced, else the index of the first closing bracket that has no
    matching opener on top of the stack, else the index of the most recent unclosed opener."""
    if mode not in ('balanced', 'max_depth', 'error_index'):
        raise ValueError('unknown mode')
    closer_of = {}
    opener_of = {}
    for o, c in pairs:
        closer_of[o] = c
        opener_of[c] = o
    expected = []
    positions = []
    deepest = 0
    fail = None
    for i, t in enumerate(tokens):
        if t in closer_of:
            expected.append(closer_of[t])
            positions.append(i)
            if len(expected) > deepest:
                deepest = len(expected)
        elif t in opener_of:
            if not expected or expected[-1] != t:
                fail = i
                break
            expected.pop()
            positions.pop()
    ok = fail is None and not expected
    if mode == 'balanced':
        return ok
    if mode == 'max_depth':
        return deepest if ok else -1
    if fail is not None:
        return fail
    if expected:
        return positions[-1]
    return -1
