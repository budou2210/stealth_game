"""画面の文字（操作説明・出現のお知らせ）が難易度に合っているかのテスト。"""

import pytest

from stealth_game.difficulty import DIFFICULTIES, HARD, HELL, NORMAL, VERY_HARD


def started(game_class, cfg):
    game = game_class()
    game.start_game(cfg)
    return game


@pytest.mark.parametrize("cfg", DIFFICULTIES, ids=[cfg.key for cfg in DIFFICULTIES])
def test_controls_list_only_usable_helpers(game_class, cfg):
    game = started(game_class, cfg)
    line = game.controls_line()
    for kind in ("cloak", "flash", "decoy"):
        usable = kind in game.helper_kinds()
        assert (game.text[f"{kind}_controls"] in line) == usable


def test_helper_kinds_per_difficulty(game_class):
    kinds = {cfg.key: started(game_class, cfg).helper_kinds() for cfg in (NORMAL, HARD, VERY_HARD, HELL)}
    assert kinds == {
        "normal": ["cloak", "flash", "decoy"],
        "hard": ["cloak", "decoy"],
        "very_hard": ["cloak", "decoy"],
        "hell": [],
    }


@pytest.mark.parametrize("cfg", [HARD, VERY_HARD], ids=["hard", "very_hard"])
def test_spawn_notice_lists_only_spawned_kinds(game_class, cfg):
    """同時に出たときのお知らせには、出た種類だけが載る（出ないスタンは載らない）。"""
    game = started(game_class, cfg)
    game.player.safe = False
    game.helper_spawn_timers = {kind: 0.0 for kind in game.helper_spawn_timers}
    game.update_helper_spawn(1 / 60)
    assert game.hint_key() == "both_appeared"
    hint = game.hint_line()
    assert game.text["cloak_label"] in hint
    assert game.text["decoy_label"] in hint
    assert game.text["flash_label"] not in hint
    assert game.helper_pickups["flash"] is None


def test_spawn_notice_with_all_kinds(game_class):
    game = started(game_class, NORMAL)
    game.helper_spawn_timers = {kind: 0.0 for kind in game.helper_spawn_timers}
    game.update_helper_spawn(1 / 60)
    hint = game.hint_line()
    assert all(game.text[f"{kind}_label"] in hint for kind in ("cloak", "flash", "decoy"))


def test_noise_range_shown_only_while_running_outside_safe_zone(game_class):
    game = started(game_class, NORMAL)
    game.player.safe = False
    game.player.moving = True
    assert game.noise_range_visible()
    game.player.sneaking = True
    assert not game.noise_range_visible(), "忍び足では足音が出ない"
    game.player.sneaking = False
    game.player.moving = False
    assert not game.noise_range_visible(), "止まっていれば足音は出ない"
    game.player.moving = True
    game.player.safe = True
    assert not game.noise_range_visible(), "安全地帯の中では聞かれない"


def test_noise_range_matches_difficulty(game_class):
    for cfg in (NORMAL, HELL):
        game = started(game_class, cfg)
        outer, muffled = game.noise_radii()
        assert outer == cfg.hear_radius
        assert muffled == cfg.hear_radius / 2, "壁越しだと半分の距離まで"


def test_noise_range_setting_toggles(game_class):
    game = started(game_class, NORMAL)
    game.player.safe = False
    game.player.moving = True
    assert game.show_noise_range, "最初はオン"
    game.toggle_noise_range()
    assert not game.noise_range_visible()
    game.toggle_noise_range()
    assert game.noise_range_visible()


def test_noise_range_setting_in_menu(game_class):
    game = game_class()
    game.open_menu()
    on = game.text["noise_range_setting"].format(state=game.text["setting_on"])
    off = game.text["noise_range_setting"].format(state=game.text["setting_off"])
    game.update_menu_text()
    assert on in game.menu_text.setText.call_args[0][0]
    game.down = {"noise_range"}
    game.is_down = lambda name: name in game.down
    game.poll_action_keys()  # メニューでFを押す
    assert not game.show_noise_range
    assert off in game.menu_text.setText.call_args[0][0]
    game.poll_action_keys()  # 押しっぱなしでは切り替わらない
    assert not game.show_noise_range


def test_exit_color_follows_collected_items(game_class):
    """出口は、ゲームを始める前と集め終わる前は赤、全部集めたら緑（見た目の更新で変える）。"""
    from stealth_game.theme import EXIT_CLOSED_COLOR, EXIT_OPEN_COLOR

    game = game_class()
    game.update_visuals(0.0)
    assert game.exit_np.setColor.call_args.args == EXIT_CLOSED_COLOR, "始める前（アイテムの配置がない）は赤"
    game.start_game(NORMAL)
    game.update_visuals(0.0)
    assert game.exit_np.setColor.call_args.args == EXIT_CLOSED_COLOR
    game.items_collected = set(range(len(game.item_cells)))
    game.update_visuals(0.0)
    assert game.exit_np.setColor.call_args.args == EXIT_OPEN_COLOR
