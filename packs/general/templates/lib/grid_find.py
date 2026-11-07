def grid_find(grid, ch):
    """First (row, col) holding ch in row-major order, or None."""
    for r, row in enumerate(grid):
        for c, v in enumerate(row):
            if v == ch:
                return (r, c)
    return None
