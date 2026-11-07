"""1回の挑戦を、別のプロセスで行うための関数（run.py が複数の挑戦を同時に走らせるとき用）。"""

import time

from stealth_game.world import World

from .danger import layout_score
from .planner import Bot, encode_keys
from .sim import Sim

_world = None


def attempt(seed, danger_map, max_compute_seconds=None, variant=0, best_order=None):
    """seed の配置で1回挑戦し、結果・通ったマス・入力の記録を返す。max_compute_seconds＝計算時間の上限（秒）。"""
    global _world
    if _world is None:
        _world = World()
    sim = Sim(seed, world=_world)
    score = layout_score(danger_map, sim.item_cells, _world)
    started = time.perf_counter()
    bot = Bot(sim, danger_map, variant, best_order)
    result = bot.play(max_compute_seconds=max_compute_seconds)
    result["layout_score"] = round(score, 3)
    result["compute_seconds"] = round(time.perf_counter() - started, 1)
    result["variant"] = variant
    if best_order is not None:
        result["best_order"] = best_order
    return result, bot.visited, encode_keys(bot.log)
