def grid_component_sizes(grid, open_chars, diagonal):
    """Sizes of the connected regions of cells whose character is in open_chars (row-major order of discovery)."""
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    if diagonal:
        steps = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    else:
        steps = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    seen = [[False] * cols for _ in range(rows)]
    sizes = []
    for r in range(rows):
        for c in range(cols):
            if seen[r][c] or grid[r][c] not in open_chars:
                continue
            seen[r][c] = True
            stack = [(r, c)]
            size = 0
            while stack:
                y, x = stack.pop()
                size += 1
                for dy, dx in steps:
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < rows and 0 <= nx < cols and not seen[ny][nx] and grid[ny][nx] in open_chars:
                        seen[ny][nx] = True
                        stack.append((ny, nx))
            sizes.append(size)
    return sizes
