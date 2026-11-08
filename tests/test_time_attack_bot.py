"""タイムアタックの攻略ボット（tools/bot/time_attack.py）のテスト。"""

import itertools
import math
import random

from stealth_game.constants import PLAYER_RADIUS
from stealth_game.difficulty import TIME_ATTACK
from stealth_game.world import World
from tools.bot.planner import decode_keys, encode_keys
from tools.bot.sim import Sim
from stealth_game.ghost import graph_for, near_best_orders, solve_order
from stealth_game.route_graph import Graph, Point
from tools.bot.time_attack import refine, replay_time, solve


def random_instance(n, seed):
    rng = random.Random(seed)
    points = [(rng.uniform(0, 40), rng.uniform(0, 40)) for _ in range(n + 2)]  # スタート・アイテム・出口
    d = lambda a, b: math.dist(points[a], points[b])  # noqa: E731
    start_to_item = [d(0, i + 1) for i in range(n)]
    item_to_item = [[d(i + 1, j + 1) for j in range(n)] for i in range(n)]
    item_to_exit = [d(i + 1, n + 1) for i in range(n)]
    return start_to_item, item_to_item, item_to_exit


def length(order, start_to_item, item_to_item, item_to_exit):
    total = start_to_item[order[0]] + item_to_exit[order[-1]]
    return total + sum(item_to_item[a][b] for a, b in zip(order, order[1:]))


def test_held_karp_matches_all_orders():
    """動的計画法の最短距離が、全部の並べ方を試した最短と一致する。"""
    for seed in range(5):
        inst = random_instance(7, seed)
        brute = min(length(o, *inst) for o in itertools.permutations(range(7)))
        _, shortest = solve_order(*inst)
        assert math.isclose(shortest, brute)


def test_near_best_orders_lists_exactly_the_short_orders():
    """限界以下の順番を、もれなく・余分なく・短い順に挙げる。"""
    inst = random_instance(6, 11)
    cost, shortest = solve_order(*inst)
    limit = shortest * 1.1
    found = near_best_orders(cost, inst[0], inst[1], limit, count=10_000)
    expected = sorted(length(o, *inst) for o in itertools.permutations(range(6)) if length(o, *inst) <= limit + 1e-9)
    assert [round(d, 6) for d, _ in found] == [round(d, 6) for d in expected]
    for d, order in found:
        assert math.isclose(d, length(order, *inst))


def test_bot_clears_and_record_replays():
    """ボットがクリアでき、残した入力をシミュレーターで最初から流すと同じタイムでクリアする。"""
    result = solve(3, candidates=5, refine_seconds=0, exact_samples=0)
    assert result["outcome"] == "win"
    assert sorted(result["order"]) == list(range(8))
    sim = Sim(3, cfg=TIME_ATTACK)
    for keys in decode_keys(result["keys"]):
        sim.step(keys)
    assert sim.state == "win"
    assert math.isclose(sim.elapsed, result["time"], abs_tol=1e-3)


def test_segment_check_matches_fine_sampling():
    """見通しの判定（列ごとの正確な判定）が、線分の上に細かく点を打って調べた結果と一致する。"""
    graph = Graph(World(), PLAYER_RADIUS)
    rng = random.Random(0)
    for _ in range(400):
        x0, y0, x1, y1 = (rng.uniform(0, 40) for _ in range(4))
        if rng.random() < 0.5:
            x1, y1 = x0 + rng.uniform(-3, 3), y0 + rng.uniform(-3, 3)
        n = int(math.hypot(x1 - x0, y1 - y0) / 0.005) + 2
        sampled = all(graph.point_free(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(n + 1))
        assert graph.segment_free(x0, y0, x1, y1) == sampled


def test_graph_distance_never_beats_straight_line():
    """地図の上の最短距離は、壁を無視したオクタイル距離より短くならず、見通せる2点ではそれと等しい。"""
    world = World()
    graph = graph_for(world)
    a, b, c = Point(graph, 2.5, 2.5), Point(graph, 37.5, 37.5), Point(graph, 5.5, 2.5)
    d, _ = a.distance_to(graph, b)
    assert d >= 35 * math.sqrt(2) - 1e-9
    assert math.isclose(a.distance_to(graph, c)[0], 3.0)


def test_refine_never_gets_slower_and_lower_bound_holds():
    """仕上げで遅くならず、仕上げた記録も最初から流すと同じタイムでクリアする。厳密な下限はタイム以下。"""
    world = World()
    result = solve(2, candidates=3, refine_seconds=0, world=world, exact_samples=0)
    log = decode_keys(result["keys"])
    better = refine(2, world, log, 1.0, random.Random(0))
    assert len(better) <= len(log)
    assert math.isclose(replay_time(2, encode_keys(better), world), len(better) / 30, abs_tol=1e-6)
    assert result["lower_bound"] <= result["time"]
