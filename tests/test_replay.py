"""ベスト記録のリプレイ（記録・保存・再生）のテスト。"""

import random

from stealth_game.difficulty import DIFFICULTIES, HARD, NORMAL
from stealth_game.replays import (
    decode_inputs,
    encode_inputs,
    load_replay,
    replay_path,
    save_replay,
)

# 移動のキーの並び（フレームごとに順に使う）と、毎フレームの時間の長さ（実際のゲームのようにばらつかせる）
PATTERN = [{"right"}] * 40 + [{"up", "sneak"}] * 30 + [{"up", "right"}] * 40 + [set()] * 10 + [{"left"}] * 30
DTS = [1 / 60, 1 / 45, 0.02, 1 / 50]


def snapshot(game):
    return (
        game.state,
        round(game.elapsed, 9),
        (game.player.x, game.player.y),
        [(g.x, g.y, g.heading, g.state) for g in game.guards],
        sorted(game.items_collected),
        list(game.item_cells),
    )


def light(game):
    """描画・音・カメラ・文字の更新を止める（偽物の部品への呼び出し記録が重いため。展開には関係しない）。"""
    for name in ("update_visuals", "update_audio", "update_camera", "update_hud"):
        setattr(game, name, lambda *args: None)
    return game


def recorded_game(game_class, cfg=NORMAL, frames=400, seed=7):
    """決まった入力で frames コマ遊んだゲーム（記録が残っている）。"""
    random.seed(seed)
    game = light(game_class())
    game.down = set()
    game.is_down = lambda name: name in game.down
    game.start_game(cfg)
    for i in range(frames):
        game.down = set(PATTERN[i % len(PATTERN)])
        game.step(DTS[i % len(DTS)])
        if game.state not in ("play", "caught"):
            break
    return game


def replay_game(game_class, replay):
    """再生用のゲーム（本物のキーボードは何も押していない）。"""
    game = light(game_class())
    game.mouseWatcherNode.isButtonDown.return_value = False
    game.replay = replay
    game.start_replay()
    return game


def play_to_end(game, real_dt=0.03, limit=100000):
    for _ in range(limit):
        if game.replay_frame >= len(game.replay["dts"]) or game.state not in ("play", "caught"):
            return
        game.replay_tick(real_dt)


def as_replay(game):
    return dict(game.recording, time=game.elapsed)


def test_inputs_round_trip():
    for held in ({"up"}, {"left", "sneak"}, set()):
        for presses in ({"decoy"}, {"cloak", "flash"}, set()):
            assert decode_inputs(encode_inputs(held, presses)) == (held, presses)


def test_save_and_load(game_class, tmp_path):
    game = recorded_game(game_class, frames=200)
    path = tmp_path / "normal.json.gz"
    assert save_replay(path, as_replay(game))
    loaded = load_replay(path)
    assert loaded["dts"] == game.recording["dts"]  # 時間の長さは丸めずにそのまま残る
    assert loaded["codes"] == game.recording["codes"]
    assert loaded["random_state"] == game.recording["random_state"]


def test_broken_file_is_ignored(tmp_path):
    path = tmp_path / "broken.json.gz"
    path.write_bytes(b"not a replay")
    assert load_replay(path) is None
    assert load_replay(tmp_path / "missing.json.gz") is None


def test_replay_reproduces_the_play(game_class):
    original = recorded_game(game_class)
    expected = snapshot(original)
    game = replay_game(game_class, as_replay(original))
    play_to_end(game)
    assert snapshot(game)[1:] == expected[1:]


def test_pausing_during_replay_does_not_change_the_result(game_class):
    original = recorded_game(game_class, cfg=HARD)
    expected = snapshot(original)
    game = replay_game(game_class, as_replay(original))
    for _ in range(50):
        game.replay_tick(0.03)
    game.toggle_pause()
    frame = game.replay_frame
    for _ in range(20):
        game.replay_tick(0.03)
    assert game.replay_frame == frame  # 一時停止中は記録を使わない
    game.toggle_pause()
    play_to_end(game)
    assert snapshot(game)[1:] == expected[1:]


def test_new_best_saves_replay_and_menu_can_play_it(game_class):
    game = recorded_game(game_class, frames=200)
    game.on_win()  # 初めてのクリアは新記録
    path = replay_path(NORMAL.key)
    assert path.exists()
    assert load_replay(path)["time"] == game.elapsed

    game.open_menu()
    game.menu_index = DIFFICULTIES.index(NORMAL)
    assert game.has_best_replay(NORMAL)
    game.play_best_replay()
    assert game.replay is not None and game.state == "play"


def test_slower_clear_keeps_old_replay(game_class):
    game = recorded_game(game_class, frames=200)
    game.on_win()
    saved = load_replay(replay_path(NORMAL.key))
    slower = recorded_game(game_class, frames=300, seed=8)
    slower.best_times = dict(game.best_times)
    slower.on_win()  # 遅いので新記録ではない
    assert load_replay(replay_path(NORMAL.key))["time"] == saved["time"]


def test_menu_refuses_when_no_replay(game_class):
    game = game_class()
    game.open_menu()
    game.play_best_replay()
    assert game.replay is None and game.state == "menu"


def test_replay_win_does_not_touch_best_time(game_class):
    original = recorded_game(game_class, frames=200)
    game = replay_game(game_class, as_replay(original))
    play_to_end(game)
    game.elapsed = original.elapsed
    game.on_win()
    assert game.best_times == {}  # 再生のクリアはベストタイムに残らない
    assert game.replay_ended


def test_replay_end_without_win_reports_mismatch(game_class):
    original = recorded_game(game_class, frames=200)
    game = replay_game(game_class, as_replay(original))
    game.message_text.setText.reset_mock()
    for _ in range(1000):
        game.replay_tick(0.03)  # 記録が終わってもクリアしていない
        if game.replay_ended:
            break
    texts = [c.args[0] for c in game.message_text.setText.call_args_list if c.args]
    assert game.text["replay_mismatch"] in texts


def test_restart_during_replay_starts_from_beginning(game_class):
    original = recorded_game(game_class, frames=300)
    game = replay_game(game_class, as_replay(original))
    for _ in range(40):
        game.replay_tick(0.03)
    game.restart_game()  # R
    assert game.replay_frame == 0 and game.elapsed == 0.0
    play_to_end(game)
    assert snapshot(game)[1:] == snapshot(original)[1:]


def test_menu_stops_replay(game_class):
    original = recorded_game(game_class, frames=100)
    game = replay_game(game_class, as_replay(original))
    game.open_menu()  # M
    assert game.replay is None


def hold_p(game):
    """P キーだけを本物のキーボードで押せるようにする（game.p_down が True の間、押している）。"""
    real = game.is_down
    game.p_down = False
    game.is_down = lambda name: (name == "pause" and game.p_down) or real(name)


def test_pressing_p_during_replay_does_not_change_the_result(game_class):
    """P キーで止めて再開しても、記録どおりに進む（キーを押したコマで、ゲームが余分に進んだり記録を飛ばしたりしない）。"""
    original = recorded_game(game_class, cfg=HARD)
    expected = snapshot(original)
    game = replay_game(game_class, as_replay(original))
    hold_p(game)
    for _ in range(50):
        game.replay_tick(0.03)
    for _ in range(2):  # 止める・再開する
        game.p_down = True
        game.replay_tick(0.03)
        game.p_down = False
        for _ in range(20):
            game.replay_tick(0.03)
    play_to_end(game)
    assert snapshot(game)[1:] == expected[1:]


def test_pausing_with_p_while_playing_keeps_the_recording_right(game_class):
    """遊んでいる途中に P で止めて再開しても、残った記録を再生すると同じ結果になる。"""
    random.seed(7)
    original = light(game_class())
    original.down = set()
    original.is_down = lambda name: name in original.down
    original.start_game(HARD)
    for i in range(400):
        original.down = set(PATTERN[i % len(PATTERN)])
        if i in (100, 130):
            original.down.add("pause")
        original.step(DTS[i % len(DTS)])
    expected = snapshot(original)
    game = replay_game(game_class, as_replay(original))
    play_to_end(game)
    assert snapshot(game)[1:] == expected[1:]


def test_clear_screen_v_replays_this_run_on_any_difficulty(game_class):
    """どの難易度でも、クリア画面の V で今のプレイを最初から再生し、記録したときと同じ展開になる（ゴーストはない）。"""
    game = recorded_game(game_class, NORMAL, frames=300)
    expected = snapshot(game)
    dts = list(game.recording["dts"])
    game.state = "win"  # この配置でクリアまで遊ぶのは長いので、クリア画面にしてから V を押す
    del game.is_down  # 再生のときは、本物の is_down（記録のキーを返す）に戻す
    game.mouseWatcherNode.isButtonDown.return_value = False
    game.play_best_replay()
    assert game.replay is not None and game.ghost is None
    for dt in dts:
        game.replay_tick(dt)
    # 記録を流し終えると「クリアしないまま記録が終わった」扱いで状態は変わるが、位置・鬼・アイテムは記録したときと同じ
    assert snapshot(game)[1:] == expected[1:]
    assert game.replay_frame == len(dts)
