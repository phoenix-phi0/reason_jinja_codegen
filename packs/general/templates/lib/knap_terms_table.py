def knap_terms_table(items, target, limit, once, ordered, mod):
    """ways[j] = number of ways to form target with exactly j items, for j = 0..limit
    (sequences if ordered, otherwise multisets; each position at most once if once; ordered and once together
    raise ValueError). mod is None or the modulus."""
    if ordered and once:
        raise ValueError('ordered sequences with each item used at most once are not supported')
    if limit < 0 or target < 0:
        return []
    dp = [[0] * (target + 1) for _ in range(limit + 1)]
    dp[0][0] = 1
    if ordered:
        for j in range(1, limit + 1):
            for s in range(target + 1):
                for v in items:
                    if v <= s:
                        dp[j][s] += dp[j - 1][s - v]
                if mod:
                    dp[j][s] %= mod
    elif once:
        for v in items:
            for j in range(limit, 0, -1):
                for s in range(target, v - 1, -1):
                    dp[j][s] += dp[j - 1][s - v]
                    if mod:
                        dp[j][s] %= mod
    else:
        for v in items:
            for j in range(1, limit + 1):
                for s in range(v, target + 1):
                    dp[j][s] += dp[j - 1][s - v]
                    if mod:
                        dp[j][s] %= mod
    return [dp[j][target] % mod if mod else dp[j][target] for j in range(limit + 1)]
