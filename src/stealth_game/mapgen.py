"""マップ生成（元の区画を鏡写しで2×2に並べ、境目に扉を開ける）。"""

from collections import deque

from .layout import (
    BASE_GUARD_ROUTES,
    BASE_SIZE,
    BASE_WALL_RECTS,
    BASE_WANDERER_SPAWNS,
    MAIN_START_ROOM_CELL,
    MAP_H,
    MAP_W,
    QUADRANT_GUARDS,
    QUADRANTS,
    SEAM_DOORS_ALONG_X,
    SEAM_DOORS_ALONG_Y,
    START_POCKET_DOORS,
    START_POCKET_RECT,
)


def fill_rect(walls, x1, y1, x2, y2, value=1):
    for y in range(y1, y2 + 1):
        for x in range(x1, x2 + 1):
            walls[y][x] = value


def mirror_value(value, size, mirrored):
    return size - 1 - value if mirrored else value


def mirror_cell(cell, qx, qy):
    return mirror_value(cell[0], MAP_W, qx), mirror_value(cell[1], MAP_H, qy)


def mirror_rect(rect, qx, qy):
    x1, y1, x2, y2 = rect
    mx1, mx2 = sorted((mirror_value(x1, MAP_W, qx), mirror_value(x2, MAP_W, qx)))
    my1, my2 = sorted((mirror_value(y1, MAP_H, qy), mirror_value(y2, MAP_H, qy)))
    return mx1, my1, mx2, my2


def open_neighbors(walls, x, y):
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < MAP_W and 0 <= ny < MAP_H and not walls[ny][nx]:
            yield nx, ny


def prune_unreachable(walls, start):
    """スタートから行けない床は壁にして、閉じた空間をなくす。"""
    seen = {start}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        frontier = [n for n in open_neighbors(walls, x, y) if n not in seen]
        seen.update(frontier)
        queue.extend(frontier)
    for y in range(MAP_H):
        for x in range(MAP_W):
            if not walls[y][x] and (x, y) not in seen:
                walls[y][x] = 1


def carve_seam_doors(walls):
    seam_lo, seam_hi = BASE_SIZE - 1, BASE_SIZE  # 境目の壁は2マス厚
    for y0 in SEAM_DOORS_ALONG_Y:
        for y in (y0, MAP_H - 2 - y0):
            fill_rect(walls, seam_lo, y, seam_hi, y + 1, 0)
    for x0 in SEAM_DOORS_ALONG_X:
        for x in (x0, MAP_W - 2 - x0):
            fill_rect(walls, x, seam_lo, x + 1, seam_hi, 0)


def build_walls():
    walls = [[0] * MAP_W for _ in range(MAP_H)]
    for qx, qy in QUADRANTS:
        for rect in BASE_WALL_RECTS:
            fill_rect(walls, *mirror_rect(rect, qx, qy))
    carve_seam_doors(walls)
    for x, y in START_POCKET_DOORS:
        walls[y][x] = 0
    prune_unreachable(walls, MAIN_START_ROOM_CELL)
    return walls


def pocket_cells():
    x1, y1, x2, y2 = START_POCKET_RECT
    return {(x, y) for y in range(y1, y2 + 1) for x in range(x1, x2 + 1)}


def build_guard_routes():
    return [
        [mirror_cell(cell, qx, qy) for cell in BASE_GUARD_ROUTES[i]]
        for (qx, qy), (route_ids, _) in QUADRANT_GUARDS.items()
        for i in route_ids
    ]


def build_wanderer_spawns():
    return [
        mirror_cell(BASE_WANDERER_SPAWNS[i], qx, qy)
        for (qx, qy), (_, spawn_ids) in QUADRANT_GUARDS.items()
        for i in spawn_ids
    ]
