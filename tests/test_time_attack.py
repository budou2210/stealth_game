"""タイムアタック（鬼もお助けアイテムも出さず、アイテム8個を集めて出口までのタイムを競う）のテスト。"""

import random

from stealth_game.difficulty import DIFFICULTIES, MENU_LEVELS, TIME_ATTACK
from stealth_game.layout import PLAYER_START
from stealth_game.records import load_records, records_path
from stealth_game.replays import load_replay, replay_path


def started(game_class):
    game = game_class()
    game.down = set()
    game.is_down = lambda name: name in game.down
    game.start_game(TIME_ATTACK)
    return game


def test_menu_lists_time_attack_last():
    assert MENU_LEVELS == DIFFICULTIES + [TIME_ATTACK]
    assert TIME_ATTACK not in DIFFICULTIES, "鬼の動きの指紋テストなど、難易度だけのテストには入れない"


def test_no_guards_helpers_or_devices(game_class):
    game = started(game_class)
    assert game.guards == []
    assert game.helper_kinds() == []
    assert not game.cameras and not game.timed_doors and not game.noisy_floors
    assert len(game.item_cells) == 8
    game.helper_spawn_timers = {kind: 0.0 for kind in game.helper_spawn_timers}
    for _ in range(120):
        game.step(1 / 60)
    assert all(cell is None for cell in game.helper_pickups.values())
    game.update_hud()  # 鬼がいなくても警戒度の計算で落ちない


def test_items_are_random_each_time(game_class):
    random.seed(1)
    first = started(game_class).item_cells
    random.seed(2)
    second = started(game_class).item_cells
    assert first != second


def test_doors_never_close_and_no_safe_zone(game_class):
    game = started(game_class)
    game.player.x, game.player.y = 20.5, 20.5  # 安全地帯から遠く離れる
    game.update_safe_zone()
    assert not game.world.doors_closed
    game.player.x, game.player.y = PLAYER_START[0] + 0.5, PLAYER_START[1] + 0.5
    game.update_safe_zone()
    assert not game.player.safe
    assert game.hint_key() == "exit_hint"


def test_pause_is_disabled(game_class):
    game = started(game_class)
    game.down = {"pause"}
    game.step(1 / 60)
    game.down = set()
    game.step(1 / 60)
    assert game.state == "play"
    assert game.elapsed > 0


def test_hud_and_menu_texts(game_class):
    game = started(game_class)
    line = game.controls_line()
    assert line == f"{game.text['time_attack_controls_move']}  {game.text['time_attack_controls_system']}"
    assert "Shift" not in line and "P:" not in line and "F:" not in line
    assert game.lives_status() == ""
    assert game.lives_label(TIME_ATTACK) == ""
    game.message_text.setText.reset_mock()
    game.open_menu()
    menu = game.menu_text.setText.call_args.args[0]
    assert f"{len(MENU_LEVELS)}. {game.text['time_attack']}" in menu
    assert game.text["no_lives_label"] not in menu.splitlines()[-2]


def test_number_key_seven_starts_time_attack(game_class):
    game = game_class()
    game.open_menu()
    game.choose_difficulty(len(MENU_LEVELS) - 1)
    assert game.difficulty is TIME_ATTACK


def test_best_time_and_replay_are_saved(game_class):
    game = started(game_class)
    for _ in range(30):
        game.step(1 / 60)
    game.on_win()
    assert load_records(records_path()) == {"time_attack": game.elapsed}
    replay = load_replay(replay_path("time_attack"))
    assert replay is not None and replay["difficulty"] == "time_attack"
    game.open_menu()
    game.menu_index = MENU_LEVELS.index(TIME_ATTACK)
    assert game.has_best_replay(TIME_ATTACK)
    game.play_best_replay()
    assert game.replay is not None and game.difficulty is TIME_ATTACK
    game.toggle_pause()
    assert game.state == "paused", "ベスト記録の再生は止められる"


def test_menu_shows_time_attack_description(game_class):
    game = game_class()
    game.open_menu()
    menu = game.menu_text.setText.call_args.args[0]
    assert game.text["time_attack_desc"] and game.text["time_attack_desc"] in menu
