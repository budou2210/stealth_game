"""地獄ボット（tools/hell_bot）のテスト。"""

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from stealth_game.difficulty import HELL  # noqa: E402

DT = 1 / 30


def scripted_keys(frame):
    """動きを決めた入力：忍び足で外へ出て、上と右に歩き、ときどき走る。"""
    keys = set()
    phase = (frame // 45) % 4
    keys.add(("right", "up", "right", "down")[phase])
    if frame < 90:
        keys = {"right"}
    if (frame // 60) % 3 != 2:
        keys.add("sneak")
    return keys


def guard_trace(guards):
    return [(round(g.x, 6), round(g.y, 6), round(g.heading, 6), g.state, round(g.alert, 6)) for g in guards]


@pytest.mark.parametrize("seed", [3, 8, 21])
def test_sim_matches_real_game(game_class, seed):
    """同じ乱数の種・同じ入力なら、シミュレーターと本物のゲームで警備員の動きがフレームごとに一致する。"""
    from hell_bot.sim import Sim

    frames = 900
    game = game_class()
    game.keys = set()
    game.is_down = lambda name: name in game.keys
    game.open_menu()
    random.seed(seed)
    game.start_game(HELL)
    real = []
    for frame in range(frames):
        game.keys = scripted_keys(frame)
        game.update_play(DT)
        real.append((round(game.player.x, 6), round(game.player.y, 6), game.state, guard_trace(game.guards)))
        if game.state != "play":
            break

    assert len(real) > 200, "短すぎて比べたことにならない"
    sim = Sim(seed)
    assert sim.item_cells == game.item_cells
    for frame, expected in enumerate(real):
        sim.step(scripted_keys(frame))
        got = (round(sim.player.x, 6), round(sim.player.y, 6), sim.state, guard_trace(sim.guards))
        assert got == expected, f"{frame}コマ目で本物とずれた"


def test_snapshot_replays_the_same_future():
    """保存した状態から何度やり直しても、同じ入力なら同じ未来になる（乱数の状態も戻る）。"""
    from hell_bot.sim import Sim

    sim = Sim(5)
    for frame in range(120):
        sim.step(scripted_keys(frame))
    saved = sim.snapshot()

    def future(start):
        s = start.snapshot()
        for frame in range(120, 400):
            s.step(scripted_keys(frame))
        return s.player.x, s.player.y, s.state, guard_trace(s.guards)

    random.random()  # ほかの場所で乱数を使っても影響しない
    assert future(saved) == future(saved) == future(sim)
