"""タイムアタックの攻略ボット（tools/bot/time_attack.py）のテスト。"""

import itertools
import math
import random

from stealth_game.difficulty import TIME_ATTACK
from tools.bot.planner import decode_keys
from tools.bot.sim import Sim
from tools.bot.time_attack import near_best_orders, solve, solve_order


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
    result = solve(3, candidates=5)
    assert result["outcome"] == "win"
    assert sorted(result["order"]) == list(range(8))
    sim = Sim(3, cfg=TIME_ATTACK)
    for keys in decode_keys(result["keys"]):
        sim.step(keys)
    assert sim.state == "win"
    assert math.isclose(sim.elapsed, result["time"], abs_tol=1e-3)
