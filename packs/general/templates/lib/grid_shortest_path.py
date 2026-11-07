def grid_shortest_path(grid, open_chars, start, goal, diagonal):
    """Fewest moves from start to goal through cells in open_chars (BFS); None if unreachable, or if start/goal
    is missing, outside the grid (negative indices included) or not open."""
    from collections import deque
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    if start is None or goal is None:
        return None
    start, goal = tuple(start), tuple(goal)
    if not (0 <= start[0] < rows and 0 <= start[1] < cols and 0 <= goal[0] < rows and 0 <= goal[1] < cols):
        return None
    if grid[start[0]][start[1]] not in open_chars or grid[goal[0]][goal[1]] not in open_chars:
        return None
    if diagonal:
        steps = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    else:
        steps = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    dist = {start: 0}
    queue = deque([start])
    while queue:
        y, x = queue.popleft()
        if (y, x) == goal:
            return dist[(y, x)]
        for dy, dx in steps:
            ny, nx = y + dy, x + dx
            if 0 <= ny < rows and 0 <= nx < cols and (ny, nx) not in dist and grid[ny][nx] in open_chars:
                dist[(ny, nx)] = dist[(y, x)] + 1
                queue.append((ny, nx))
    return None
