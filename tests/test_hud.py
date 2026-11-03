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
