def matrix_diagonal_sums(mat, center):
    """Return [main, anti]: sums of cells (i, i) and (i, cols-1-i) for i < min(rows, cols).
    center says what happens to the cell lying on both diagonals: 'both', 'main_only', 'anti_only' or 'skip'."""
    if center not in ('both', 'main_only', 'anti_only', 'skip'):
        raise ValueError('unknown center mode')
    rows = len(mat)
    cols = len(mat[0]) if rows else 0
    main = 0
    anti = 0
    for i in range(min(rows, cols)):
        j = cols - 1 - i
        shared = i == j
        if not (shared and center in ('anti_only', 'skip')):
            main += int(mat[i][i])
        if not (shared and center in ('main_only', 'skip')):
            anti += int(mat[i][j])
    return [main, anti]
