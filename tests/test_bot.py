"""攻略ボット（tools/bot）のテスト。"""

import random

import pytest

from stealth_game.difficulty import HELL, TRANSCEND

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


@pytest.mark.parametrize("cfg, seed", [(HELL, 3), (HELL, 8), (HELL, 21), (TRANSCEND, 3), (TRANSCEND, 8)],
                         ids=["hell-3", "hell-8", "hell-21", "transcend-3", "transcend-8"])
def test_sim_matches_real_game(game_class, cfg, seed):
    """同じ乱数の種・同じ入力なら、シミュレーターと本物のゲームで警備員の動きがフレームごとに一致する
    （超越では、扉の開け閉め・鳴る床・監視カメラも一致する）。"""
    from tools.bot.sim import Sim

    frames = 900
    game = game_class()
    game.keys = set()
    game.is_down = lambda name: name in game.keys
    game.open_menu()
    random.seed(seed)
    game.start_game(cfg)
    real = []
    for frame in range(frames):
        game.keys = scripted_keys(frame)
        game.update_play(DT)
        real.append((round(game.player.x, 6), round(game.player.y, 6), game.state, guard_trace(game.guards),
                     game.world.timed_closed, game.camera_alarms, game.floor_under))
        if game.state != "play":
            break

    assert len(real) > 200, "短すぎて比べたことにならない"
    sim = Sim(seed, cfg)
    assert sim.item_cells == game.item_cells
    assert sim.noisy_floors == game.noisy_floors
    for frame, expected in enumerate(real):
        sim.step(scripted_keys(frame))
        got = (round(sim.player.x, 6), round(sim.player.y, 6), sim.state, guard_trace(sim.guards),
               sim.world.timed_closed, sim.camera_alarms, sim.floor_under)
        assert got == expected, f"{frame}コマ目で本物とずれた"


def test_snapshot_replays_the_same_future():
    """保存した状態から何度やり直しても、同じ入力なら同じ未来になる（乱数の状態も戻る）。"""
    from tools.bot.sim import Sim

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


# --- 記録の再生（replay.py） ------------------------------------------------

def make_record(seed, frames):
    from tools.bot.planner import encode_keys

    return {"seed": seed, "keys": encode_keys([frozenset(scripted_keys(f)) for f in range(frames)])}


def new_replay(game_class, record):
    from tools.bot.play_record import Replay

    replay = Replay(record, 1.0)
    replay.mouseWatcherNode.isButtonDown.return_value = False  # 本物のキーボードは何も押していない
    return replay


def snapshot_of(game):
    return (round(game.player.x, 6), round(game.player.y, 6), game.state, guard_trace(game.guards))


def test_replay_win_is_not_saved_as_best_time(game_class, records_dir):
    from stealth_game.records import load_records, records_path

    replay = new_replay(game_class, make_record(8, 30))
    replay.elapsed = 123.0
    replay.message_text.setText.reset_mock()
    replay.on_win()
    assert replay.state == "win"
    assert replay.best_times == {}
    assert load_records(records_path()) == {}, "ボットの記録はベストタイムに残さない"
    message = replay.message_text.setText.call_args.args[0]
    assert "M:" not in message


def test_replay_restart_starts_over_from_first_frame(game_class):
    replay = new_replay(game_class, make_record(8, 200))
    items = list(replay.item_cells)
    for _ in range(150):
        replay.advance()
    first_pass = snapshot_of(replay)
    replay.restart_game()  # R
    assert replay.frame == 0 and replay.state == "play"
    assert replay.item_cells == items, "同じ配置で始め直す"
    for _ in range(150):
        replay.advance()
    assert snapshot_of(replay) == first_pass, "やり直しても記録どおりに動く"


def test_replay_ignores_m(game_class):
    replay = new_replay(game_class, make_record(8, 30))
    replay.ignore.assert_any_call("m")
    assert "M:" not in replay.controls_line()


def test_replay_pause_keeps_record_in_sync(game_class):
    straight = new_replay(game_class, make_record(8, 200))
    for _ in range(160):
        straight.advance()

    paused = new_replay(game_class, make_record(8, 200))
    for _ in range(80):
        paused.advance()
    paused.toggle_pause()  # P
    assert "M:" not in paused.message_text.setText.call_args.args[0]
    frame = paused.frame
    for _ in range(40):
        paused.advance()
    assert paused.frame == frame, "一時停止中は記録の入力も止まる"
    paused.toggle_pause()
    for _ in range(80):
        paused.advance()
    assert snapshot_of(paused) == snapshot_of(straight)


def test_replay_pressing_p_keeps_record_in_sync(game_class):
    """P キーで止めて再開しても、記録どおりに進む（キーを押したコマで、記録の入力を飛ばしたり余分に進んだりしない）。"""
    straight = new_replay(game_class, make_record(8, 200))
    for _ in range(160):
        straight.advance()

    paused = new_replay(game_class, make_record(8, 200))
    real = paused.is_down
    paused.p_down = False
    paused.is_down = lambda name: (name == "pause" and paused.p_down) or real(name)
    for _ in range(80):
        paused.advance()
    for _ in range(2):  # 止める・再開する
        paused.p_down = True
        paused.advance()
        paused.p_down = False
        for _ in range(40):
            paused.advance()
        if paused.state == "paused":
            frame = paused.frame
    assert frame == 80, "止めたコマでは、記録の入力を使わない"
    for _ in range(40):
        paused.advance()
    assert snapshot_of(paused) == snapshot_of(straight)


def test_rewind_keeps_only_the_successful_branch():
    """巻き戻した後の記録を最初から再生すると、ボットの今の状態とぴったり一致する（失敗した流れが混ざらない）。"""
    from tools.bot.danger import DangerMap
    from tools.bot.planner import Bot
    from tools.bot.sim import Sim

    bot = Bot(Sim(8), DangerMap())
    bot.save_checkpoint()
    for frame in range(150):
        bot.apply(frozenset(scripted_keys(frame)))
    bot.save_checkpoint()
    checkpoint_time = bot.sim.elapsed
    for frame in range(150, 400):  # この流れは捨てられる
        bot.apply(frozenset({"right"}))
    bot.sim.elapsed += 40  # 行き詰まったことにする（30秒より前の保存点へ戻る）
    assert bot.rewind("stuck")
    assert bot.sim.elapsed == checkpoint_time
    assert len(bot.log) == 150
    assert bot.hold_slots == 1, "やり直すときは少し待ってから動く"
    for frame in range(150, 300):
        bot.apply(frozenset(scripted_keys(frame)))

    fresh = Sim(8)
    for keys in bot.log:
        fresh.step(keys)
    assert snapshot_of(fresh) == snapshot_of(bot.sim)


def test_heads_for_exit_when_all_items_were_taken_without_a_race():
    """競走を経ずに8個とも集めてしまっても止まらず、出口へ向かう入力を返す。"""
    from tools.bot.danger import DangerMap
    from tools.bot.planner import Bot
    from tools.bot.sim import Sim

    bot = Bot(Sim(8), DangerMap())
    bot.sim.items_collected = set(range(len(bot.sim.item_cells)))
    keys = bot.decide()
    assert keys or bot.race_keys, "出口へ向かう入力がある"


def test_best_order_is_never_longer_than_nearest_first():
    """F1（順番を全部比べる）は、近い順より道のりが長くならず、全部のアイテムを1回ずつ回る。"""
    from tools.bot.danger import DangerMap
    from tools.bot.planner import Bot
    from tools.bot.sim import Sim

    for seed in (8, 410, 1329):
        near = Bot(Sim(seed), DangerMap(), best_order=False)
        best = Bot(Sim(seed), DangerMap(), best_order=True)
        assert sorted(best.order) == list(range(len(best.sim.item_cells)))
        assert best.route_length(best.order[:-1], best.order[-1]) <= near.route_length(near.order[:-1], near.order[-1]) + 1e-9
