"""一時停止と、ベストタイムの記録・表示のテスト。"""

from stealth_game.difficulty import HARD, NORMAL
from stealth_game.records import load_records, records_path


def started(game_class, cfg=NORMAL):
    game = game_class()
    game.down = set()
    game.is_down = lambda name: name in game.down
    game.start_game(cfg)
    return game


def press(game, *keys):
    """キーを押した瞬間の1フレームを進め、離した状態の1フレームも進める。"""
    game.down = set(keys)
    game.step(1 / 60)
    game.down = set()
    game.step(1 / 60)


def written_texts(game):
    """画面の文字欄に書かれた文字の一覧。

    テストでは文字欄（OnscreenText）が全部同じ偽物になるので、どの欄に書かれたかは区別しない。
    """
    return [c.args[0] for c in game.message_text.setText.call_args_list if c.args]


def guard_positions(game):
    return [(g.x, g.y, g.heading) for g in game.guards]


def test_pause_freezes_everything(game_class):
    game = started(game_class)
    for _ in range(30):
        game.step(1 / 60)
    game.message_text.setText.reset_mock()
    press(game, "pause")
    assert game.state == "paused"
    assert game.text["paused"] in written_texts(game)
    elapsed, guards = game.elapsed, guard_positions(game)
    game.down = {"right", "decoy"}  # 一時停止中は移動もアイテムも受け付けない
    for _ in range(60):
        game.step(1 / 60)
    assert game.elapsed == elapsed
    assert guard_positions(game) == guards
    assert game.placed_decoys == []
    press(game, "pause")
    assert game.state == "play"
    for _ in range(5):
        game.step(1 / 60)
    assert game.elapsed > elapsed, "再開すると時間が進む"


def test_pause_only_during_play(game_class):
    game = game_class()
    game.down = set()
    game.is_down = lambda name: name in game.down
    game.open_menu()
    press(game, "pause")
    assert game.state == "menu", "難易度選択の画面では一時停止しない"
    game.start_game(NORMAL)
    game.state = "win"
    press(game, "pause")
    assert game.state == "win"


def test_restart_and_menu_from_pause(game_class):
    game = started(game_class)
    game.toggle_pause()
    game.restart_game()
    assert game.state == "play"
    game.toggle_pause()
    game.open_menu()
    assert game.state == "menu"


def win(game, elapsed):
    """クリアさせて、そのときに出た文字を返す。"""
    game.elapsed = elapsed
    game.message_text.setText.reset_mock()
    game.taskMgr.doMethodLater.reset_mock()
    game.on_win()
    for call in game.taskMgr.doMethodLater.call_args_list:  # 新記録の表示（ジングルと同時）まで進める
        call.args[1](None)
    return "\n".join(written_texts(game))


def test_best_time_is_saved_and_shown(game_class):
    game = started(game_class, HARD)
    message = win(game, 200.0)
    assert game.state == "win"
    assert game.text["new_record"] in message
    assert load_records(records_path()) == {"hard": 200.0}

    game.start_game(HARD)
    message = win(game, 250.0)
    assert message == game.text["win_done"].format(time=250.0), "新記録でないときは、タイムと操作だけ"
    assert load_records(records_path()) == {"hard": 200.0}, "遅いタイムでは書き換えない"

    game.start_game(HARD)
    win(game, 150.0)
    assert load_records(records_path()) == {"hard": 150.0}

    fresh = game_class()  # 起動し直しても記録が残り、難易度選択の画面に出る
    assert fresh.best_times == {"hard": 150.0}
    fresh.message_text.setText.reset_mock()
    fresh.open_menu()
    menu = "\n".join(written_texts(fresh))
    assert fresh.text["best_label"].format(time=150.0) in menu
    assert menu.count(fresh.text["best_label"].format(time=150.0)) == 1, "記録のある難易度だけに出す"
