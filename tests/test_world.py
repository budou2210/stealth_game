"""マップ生成と World（当たり判定・視線）のテスト。"""

from collections import deque

import pytest

from stealth_game.grid import cell_center
from stealth_game.layout import (
    EXIT_CELL,
    MAP_H,
    MAP_W,
    PLAYER_START,
    START_POCKET_DOORS,
)
from stealth_game.mapgen import build_guard_routes, build_wanderer_spawns


def reachable(world, start):
    seen = {start}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if n not in seen and not world.is_wall(*n):
                seen.add(n)
                queue.append(n)
    return seen


def test_every_floor_cell_is_reachable_from_start(world):
    seen = reachable(world, PLAYER_START)
    assert set(world.floor_cells) <= seen
    assert EXIT_CELL in seen


def test_doors_close_the_safe_room(world):
    world.doors_closed = True
    seen = reachable(world, PLAYER_START)
    assert EXIT_CELL not in seen, "扉が閉まると安全地帯から出られない"
    assert all(world.is_wall(*door) for door in START_POCKET_DOORS)


def test_start_is_safe_and_exit_is_floor(world):
    assert PLAYER_START in world.safe_cells
    assert not world.is_wall(*EXIT_CELL)
    assert EXIT_CELL not in world.safe_cells


def test_guard_layout():
    routes = build_guard_routes()
    spawns = build_wanderer_spawns()
    assert len(routes) == 10, "青（順路型）は10人"
    assert len(spawns) == 6, "紫（徘徊型）は6人"


def test_guard_layout_is_on_guard_floor(world):
    cells = set(world.guard_cells)
    for route in build_guard_routes():
        assert set(route) <= cells
    assert set(build_wanderer_spawns()) <= cells


def test_outside_map_is_wall_except_pocket(world):
    assert world.is_wall(-1, 10)
    assert world.is_wall(MAP_W, 10)
    assert world.is_wall(10, MAP_H)
    assert not world.is_wall(*PLAYER_START)


def test_costs_are_positive_integers(world):
    for row in world.costs:
        assert all(isinstance(c, int) and c >= 1 for c in row)


def find_straight_run(world, length):
    """横一列に length マス続く床（壁際でない）を探す。"""
    for y in range(MAP_H):
        for x in range(MAP_W - length):
            cells = [(x + i, y) for i in range(length)]
            if all(not world.is_wall(*c) for c in cells):
                return cells
    raise AssertionError("まっすぐな通路が見つからない")


def find_wall_between(world):
    """床・壁・床と横に並んだ場所を探す。"""
    for y in range(MAP_H):
        for x in range(1, MAP_W - 1):
            if world.is_wall(x, y) and not world.is_wall(x - 1, y) and not world.is_wall(x + 1, y):
                return (x - 1, y), (x + 1, y)
    raise AssertionError("1マスの壁が見つからない")


def test_line_of_sight(world):
    run = find_straight_run(world, 5)
    a, b = cell_center(run[0]), cell_center(run[-1])
    assert world.has_line_of_sight(*a, *b)
    left, right = find_wall_between(world)
    assert not world.has_line_of_sight(*cell_center(left), *cell_center(right))


def test_diagonal_wall_gap_blocks_sight(world):
    """斜めに並んだ2つの壁の角のすき間は、視線を通さない。"""
    run = find_straight_run(world, 3)
    (x, y) = run[0]
    for dy in (1, -1):  # 上か下の列も床なら、そこに斜めの壁を作る
        if all(not world.is_wall(x + i, y + dy) for i in range(3)):
            break
    else:
        raise AssertionError("2×2の床が見つからない")
    world.walls[y][x + 1] = 1
    world.walls[y + dy][x] = 1
    a = cell_center((x, y))
    b = cell_center((x + 1, y + dy))
    assert not world.has_line_of_sight(*a, *b)
    world.walls[y + dy][x] = 0  # 片方だけなら、角をかすめて見える
    assert world.has_line_of_sight(*a, *b)


def test_visible_outline_stops_at_walls(world):
    """足音の範囲（外側）の形：見通しのよい向きは半径まで伸び、壁のある向きは壁で止まる。"""
    left, _ = find_wall_between(world)
    x, y = cell_center(left)
    outline = world.visible_outline(x, y, 6.0, 4)  # 東・北・西・南・東
    assert len(outline) == 5
    assert outline[0] == pytest.approx(outline[-1])
    east_x, _ = outline[0]
    assert east_x - x == pytest.approx(0.5), "すぐ右の壁で止まる"
    run = find_straight_run(world, 8)
    x, y = cell_center(run[0])
    east_x, _ = world.visible_outline(x, y, 6.0, 4)[0]
    assert east_x - x == pytest.approx(6.0), "壁がなければ半径いっぱいまで"


def test_is_blocked_by_wall(world):
    left, _ = find_wall_between(world)
    x, y = cell_center(left)
    assert not world.is_blocked(x, y, 0.3)
    assert world.is_blocked(x + 0.4, y, 0.3), "右隣の壁に体がめり込む位置"
