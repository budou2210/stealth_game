"""自作A*のテスト。"""

import heapq
import random

from stealth_game.grid import manhattan
from stealth_game.pathfinding import astar


def dijkstra_cost(world, start, goal):
    """答え合わせ用：A*と同じ移動規則での最小コスト（行けなければNone）。"""
    best = {start: 0}
    heap = [(0, start)]
    while heap:
        cost, cell = heapq.heappop(heap)
        if cell == goal:
            return cost
        if cost > best[cell]:
            continue
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = cell[0] + dx, cell[1] + dy
            if world.is_forbidden_for_guard(nx, ny):
                continue
            new_cost = cost + world.costs[ny][nx]
            if new_cost < best.get((nx, ny), new_cost + 1):
                best[(nx, ny)] = new_cost
                heapq.heappush(heap, (new_cost, (nx, ny)))
    return None


def path_cost(world, path):
    return sum(world.costs[y][x] for x, y in path[1:])


def assert_valid_path(world, path, start, goal):
    assert path[0] == start
    assert path[-1] == goal
    for a, b in zip(path, path[1:]):
        assert manhattan(a, b) == 1, "隣のマスへ1歩ずつ進む"
        assert not world.is_forbidden_for_guard(*b), "壁や安全地帯は通らない"


def test_path_is_valid_and_shortest(world):
    rng = random.Random(0)
    for _ in range(40):
        start, goal = rng.sample(world.guard_cells, 2)
        path = astar(world, start, goal)
        assert_valid_path(world, path, start, goal)
        assert path_cost(world, path) == dijkstra_cost(world, start, goal)


def test_start_equals_goal(world):
    cell = world.guard_cells[0]
    assert astar(world, cell, cell) == [cell]


def test_goal_in_wall_or_safe_zone_is_unreachable(world):
    start = world.guard_cells[0]
    wall = next((x, y) for y in range(len(world.walls)) for x in range(len(world.walls[0])) if world.walls[y][x])
    assert astar(world, start, wall) == []
    safe = next(iter(world.safe_cells))
    assert astar(world, start, safe) == []


def test_extra_cost_makes_a_detour(world):
    """挟み撃ち用の追加コストを付けたマスは、遠回りしてでも避ける。"""
    rng = random.Random(1)
    for _ in range(20):
        start, goal = rng.sample(world.guard_cells, 2)
        plain = astar(world, start, goal)
        if len(plain) < 8:
            continue
        busy = set(plain[2:-2])
        detour = astar(world, start, goal, lambda c: 50 if c in busy else 0)
        assert_valid_path(world, detour, start, goal)
        assert len(busy & set(detour)) < len(busy)
        return
    raise AssertionError("回り道を試せる経路が見つからなかった")
