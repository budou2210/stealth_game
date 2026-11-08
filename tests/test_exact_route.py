"""選んだ順番での本当の最短の道（stealth_game/exact_route.py）のテスト。"""

import itertools
import math

from stealth_game.constants import ITEM_PICKUP_DISTANCE, PLAYER_RUN_SPEED
from stealth_game.difficulty import TIME_ATTACK
from stealth_game.exact_route import (
    EXIT_DISTANCE,
    INSIDE,
    STRICT_RADIUS,
    circle_samples,
    exact_map,
    solve_exact,
    strict_lower_bound,
)
from stealth_game.grid import cell_center
from stealth_game.layout import EXIT_CELL, PLAYER_START
from stealth_game.route_graph import Point
from stealth_game.world import World
from tools.bot.planner import decode_keys
from tools.bot.sim import Sim
from tools.bot.time_attack import solve

STEP = PLAYER_RUN_SPEED / 30  # 1コマで進める、8方向の移動での長さの最大


def test_circle_samples_are_free_and_include_cut_points():
    """候補の点はどれも通れる場所にあり、壁にかかる円では、切れ目のすぐそばにも候補がある。"""
    world = World()
    graph = exact_map(world).graph
    for cell in [(1, 1), (2, 8), (8, 2), (18, 18), (21, 3)]:
        cx, cy = cell_center(cell)
        points, widest = circle_samples(graph, cx, cy, 0.7, 60)
        assert points and widest <= 2 * math.pi / 60 + 1e-9
        assert all(graph.point_free(x, y) for x, y in points)
        for x, y in points:
            assert math.isclose(math.hypot(x - cx, y - cy), 0.7)
    # 角の部屋 (1, 1) の円は壁にかかる：周の上で、候補のすぐ外側（同じ半径・少しずれた角度）が壁になる点がある
    cx, cy = cell_center((1, 1))
    points, _ = circle_samples(graph, cx, cy, 0.7, 60)
    angles = [math.atan2(y - cy, x - cx) for x, y in points]
    blocked_next = [a for a in angles
                    if not graph.point_free(cx + 0.7 * math.cos(a + 1e-4), cy + 0.7 * math.sin(a + 1e-4))
                    or not graph.point_free(cx + 0.7 * math.cos(a - 1e-4), cy + 0.7 * math.sin(a - 1e-4))]
    assert blocked_next, "切れ目の点が候補に入っていない"


def test_dynamic_programming_matches_trying_every_combination():
    """表を埋めて求めた最短が、候補の点の組み合わせを全部試して、地図の上の最短距離を足した最小と一致する。"""
    world = World()
    graph = exact_map(world).graph
    items = Sim(1, cfg=TIME_ATTACK, world=world).item_cells
    order = [0, 1]
    result = solve_exact(world, items, order, samples=12)
    start = Point(graph, *cell_center(PLAYER_START))
    layers = []
    for cell, radius in [(items[0], ITEM_PICKUP_DISTANCE), (items[1], ITEM_PICKUP_DISTANCE), (EXIT_CELL, EXIT_DISTANCE)]:
        cx, cy = cell_center(cell)
        points, _ = circle_samples(graph, cx, cy, radius - INSIDE, 12)
        layers.append([Point(graph, x, y) for x, y in points])
    first = [start.distance_to(graph, a)[0] for a in layers[0]]
    mid = [[a.distance_to(graph, b)[0] for b in layers[1]] for a in layers[0]]
    last = [[b.distance_to(graph, c)[0] for c in layers[2]] for b in layers[1]]
    brute = min(
        first[i] + mid[i][j] + last[j][k]
        for i, j, k in itertools.product(range(len(layers[0])), range(len(layers[1])), range(len(layers[2])))
    )
    assert math.isclose(result["length"], brute, rel_tol=1e-9)
    # たどり直した道の長さも同じ
    path = result["path"]
    walked = sum(max(abs(a[0] - b[0]), abs(a[1] - b[1])) + (math.sqrt(2) - 1) * min(abs(a[0] - b[0]), abs(a[1] - b[1]))
                 for a, b in zip(path, path[1:]))
    assert math.isclose(walked, result["length"], rel_tol=1e-9)
    assert all(graph.segment_free(*a, *b) for a, b in zip(path, path[1:]))


def test_slack_brackets_the_true_shortest():
    """候補の数を変えても、どちらの結果も「求めた長さ − 保証の幅」が相手の求めた長さを超えない。"""
    world = World()
    items = Sim(2, cfg=TIME_ATTACK, world=world).item_cells
    order = [0, 1, 2, 3, 6, 4, 5, 7]
    coarse = solve_exact(world, items, order, samples=60)
    fine = solve_exact(world, items, order, samples=360)
    assert coarse["slack"] > fine["slack"]
    assert coarse["length"] - coarse["slack"] <= fine["length"] + 1e-9
    assert fine["length"] - fine["slack"] <= coarse["length"] + 1e-9


def test_bot_never_beats_the_frame_lower_bound():
    """ボットの記録のコマ数は、その順番でのコマ数の下限以上で、記録は最初から流すとクリアする。
    種104は、計画では5→0の順なのに、途中で0のそばを通って先に拾う配置（実際に拾った順番で下限を測る）。"""
    world = World()
    for seed in (0, 5, 104):
        result = solve(seed, candidates=3, refine_seconds=0, world=world, exact_samples=120)
        assert result["outcome"] == "win"
        assert result["min_frames"] <= result["frames"]
        assert result["exact_length"] - result["exact_slack"] <= result["frames"] * STEP + 1e-9
        sim = Sim(seed, cfg=TIME_ATTACK, world=world)
        for keys in decode_keys(result["keys"]):
            sim.step(keys)
        assert sim.state == "win"


def test_every_frame_moves_along_a_line_free_for_the_strict_size():
    """1コマの動きのまっすぐな線は、体の大きさ STRICT_RADIUS の地図ではいつも通れる（下限の前提）。
    壁に沿って滑る動きや、角をかすめる斜めの動きを含むように、壁に向かって押し続ける入力も試す。"""
    world = World()
    graph = exact_map(world, STRICT_RADIUS).graph
    result = solve(3, candidates=2, refine_seconds=0, world=world, exact_samples=0)
    logs = [decode_keys(result["keys"])]
    for keys in ({"up", "right"}, {"down", "right"}, {"up", "left"}, {"down", "left"}):
        logs.append([frozenset({"right"})] * 40 + [frozenset(keys)] * 200 + [frozenset({"up"})] * 100)
    for log in logs:
        sim = Sim(3, cfg=TIME_ATTACK, world=world)
        for keys in log:
            x, y = sim.player.x, sim.player.y
            sim.step(keys)
            assert graph.segment_free(x, y, sim.player.x, sim.player.y)
            if sim.done:
                break


def test_strict_lower_bound_is_below_the_bot_and_the_order_bound():
    world = World()
    for seed in (1, 4):
        result = solve(seed, candidates=3, refine_seconds=0, world=world, exact_samples=120)
        assert result["lower_bound_frames"] <= result["min_frames"] <= result["frames"]


def test_cutoff_skips_slow_layouts():
    """下限が足切りの秒数以上なら計算しない。足切りを通った配置は、最後まで全部計算する。"""
    world = World()
    frames, _ = strict_lower_bound(world, Sim(1, cfg=TIME_ATTACK, world=world).item_cells)
    cut = solve(1, refine_seconds=0, world=world, exact_samples=0, cutoff=frames / 30)
    assert cut["outcome"] == "cut" and cut["keys"] == []
    passed = solve(1, refine_seconds=0, world=world, exact_samples=120, cutoff=frames / 30 + 0.01)
    assert passed["outcome"] == "win" and passed["min_frames"] is not None, "ボットのタイムが足切り以上でも、最後まで計算する"
