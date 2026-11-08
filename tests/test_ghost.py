"""タイムアタックのゴースト（リプレイに重ねるボットの動き）のテスト。"""

import math
import random

from stealth_game.difficulty import MENU_LEVELS, NORMAL, TIME_ATTACK
from stealth_game.ghost import DT, Run, best_run
from stealth_game.world import World
from tools.bot.sim import Sim


def test_run_matches_the_real_game_step():
    """ゴースト用の小さな進め方（Run）が、本物の処理を借りたシミュレーターと1コマずつ一致する。"""
    world = World()
    sim = Sim(4, cfg=TIME_ATTACK, world=world)
    run = Run(world, sim.item_cells)
    plan = best_run(world, sim.item_cells, candidates=3)
    assert plan["time"] is not None
    for keys in plan["log"]:
        sim.step(keys)
        run.step(keys)
        assert (run.player.x, run.player.y) == (sim.player.x, sim.player.y)
        assert run.items_collected == sim.items_collected
        assert run.done == (sim.state == "win")
    assert sim.state == "win"
    assert math.isclose(sim.elapsed, plan["time"])


def win_with_bot(game_class):
    """タイムアタックを始め、ボットの入力どおりに遊んでクリアしたゲーム。"""
    random.seed(9)
    game = game_class()
    # 描画・音・カメラ・文字の更新を止める（偽物の部品への呼び出し記録がたまると、後のテストまで遅くなるため）。
    # 状態の行の文字（ghost_status）とゴーストの位置（ghost_pose）は、テストの中で直接確かめる
    for name in ("update_visuals", "update_audio", "update_camera", "update_hud"):
        setattr(game, name, lambda *args: None)
    game.down = set()
    game.is_down = lambda name: name in game.down
    game.start_game(TIME_ATTACK)
    plan = best_run(game.world, game.item_cells, candidates=3)
    for keys in plan["log"]:
        game.down = set(keys)
        game.step(DT)
    del game.is_down  # 再生のときは、本物の is_down（記録のキーを返す）に戻す
    game.mouseWatcherNode.isButtonDown.return_value = False
    assert game.state == "win"
    return game


def written(game):
    """文字欄に書かれた文字の全部（テストでは文字欄が全部同じ偽物になるので、どの欄かは区別しない）。"""
    return "\n".join(c.args[0] for c in game.message_text.setText.call_args_list if c.args)


def replay_to_end(game):
    for _ in range(5000):
        if game.state != "play":
            break
        game.replay_tick(DT)
    return game


def test_clear_screen_offers_replay_with_ghost(game_class):
    game = win_with_bot(game_class)
    for call in game.taskMgr.doMethodLater.call_args_list:  # 新記録の表示まで進める
        call.args[1](None)
    assert game.text["ghost_replay_hint"] in written(game)
    elapsed = game.elapsed

    game.play_best_replay()  # クリア画面の V：今のプレイを再生
    assert game.replay is not None and game.state == "play"
    assert game.ghost is not None, "タイムアタックの再生にはゴーストが付く"
    assert game.ghost_status() == game.text["ghost_running_status"]
    replay_to_end(game)
    assert game.state == "win"
    assert math.isclose(game.elapsed, elapsed, abs_tol=1e-6)
    end = written(game)
    assert game.text["ghost_result"].format(bot=game.ghost["time"], diff=game.elapsed - game.ghost["time"]) in end
    assert game.ghost_status() == game.text["ghost_goal_status"].format(time=game.ghost["time"])


def test_menu_replay_has_ghost_and_other_levels_do_not(game_class):
    game = win_with_bot(game_class)
    game.open_menu()
    assert game.ghost is None
    game.menu_index = MENU_LEVELS.index(TIME_ATTACK)
    game.play_best_replay()
    assert game.ghost is not None
    first = game.ghost
    game.restart_game()  # 再生中の R：同じ配置なので、計算し直さずに使い回す
    assert game.ghost is first

    game.open_menu()
    game.start_game(NORMAL)
    game.state = "win"
    game.play_best_replay()
    assert game.replay is not None, "タイムアタック以外のクリア画面でも、V で今のプレイを再生する"
    assert game.ghost is None, "ゴーストはタイムアタックだけ"


def test_ghost_pose_follows_frames(game_class):
    game = win_with_bot(game_class)
    game.play_best_replay()
    poses = game.ghost["poses"]
    for k in (1, 10, 100):
        x, y, _ = game.ghost_pose(k * DT + 1e-9)
        assert math.isclose(x, poses[k - 1][0], abs_tol=1e-6) and math.isclose(y, poses[k - 1][1], abs_tol=1e-6)
    mid = game.ghost_pose(10.5 * DT)
    assert math.isclose(mid[0], (poses[9][0] + poses[10][0]) / 2, abs_tol=1e-6)
    assert game.ghost_pose(10_000)[:2] == poses[-1][:2], "ゴールした後は止まる"


def test_drive_touches_clears_and_matches_the_real_game():
    """「残りの長さが一番短くなる向き」を選ぶ動かし方でもクリアでき、その入力は本物と同じ処理でもクリアする。"""
    from tools.bot.exact_route import solve_exact
    from tools.bot.ta_drive import drive_touches

    world = World()
    sim = Sim(61, cfg=TIME_ATTACK, world=world)
    plan = best_run(world, sim.item_cells, candidates=3)
    exact = solve_exact(world, sim.item_cells, plan["order"], samples=60)
    t, log, _ = drive_touches(world, sim.item_cells, plan["order"], exact["touches"])
    assert t is not None
    for keys in log:
        sim.step(keys)
    assert sim.state == "win" and math.isclose(sim.elapsed, t)


def test_smooth_log_groups_diagonal_and_straight_without_changing_the_time():
    """ボットの記録の、斜めとまっすぐの細かい切り替えをまとめても、コマ数は変わらず、本物と同じ処理でもクリアする。"""
    from stealth_game.ghost import smooth_log
    from tools.bot.planner import decode_keys, encode_keys
    from tools.bot.time_attack import drive_through, solve_exact

    world = World()
    sim = Sim(104, cfg=TIME_ATTACK, world=world)
    order = [0, 5, 4, 1, 3, 2, 6, 7]
    exact = solve_exact(world, sim.item_cells, order, samples=60)
    _, log, _ = drive_through(world, sim.item_cells, order, exact["touches"])  # 並べ替える前の、細かく切り替わる記録
    smoothed = smooth_log(world, sim.item_cells, log)
    assert len(smoothed) == len(log)
    assert len(encode_keys(smoothed)) < len(encode_keys(log)) / 2, "切り替えの回数が半分以下になる"
    for keys in decode_keys(encode_keys(smoothed)):
        sim.step(keys)
    assert sim.state == "win"


def test_smooth_log_on_a_hand_made_zigzag():
    """壁のない場所での「右・右上」のくり返しは、「右上をまとめて → 右をまとめて」になる。"""
    from stealth_game.ghost import Run, smooth_log

    world = World()
    items = Sim(0, cfg=TIME_ATTACK, world=world).item_cells
    right, up_right = frozenset({"right"}), frozenset({"right", "up"})
    lead = [right] * 20  # スタートの小部屋から、左下の部屋の中ほどまで出る
    zig = [right, up_right] * 6
    log = lead + zig
    out = smooth_log(world, items, log + [frozenset()])  # クリアしない記録は、元のまま返る
    assert out == log + [frozenset()]
    run_a, run_b = Run(world, items), Run(world, items)
    for keys in log:
        run_a.step(keys)
    grouped = lead + [up_right] * 6 + [right] * 6
    for keys in grouped:
        run_b.step(keys)
    assert math.isclose(run_a.player.x, run_b.player.x) and math.isclose(run_a.player.y, run_b.player.y)
