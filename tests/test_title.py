"""タイトル画面のテスト。"""

import pytest

from stealth_game.difficulty import NORMAL


def new_game(game_class):
    game = game_class()
    game.down = set()
    game.is_down = lambda name: name in game.down
    return game


def press(game, *keys):
    game.down = set(keys)
    game.step(1 / 60)
    game.down = set()
    game.step(1 / 60)


def test_starts_on_title_and_enter_opens_menu(game_class):
    game = new_game(game_class)
    assert game.state == "title"
    game.step(1 / 60)
    assert game.wanted_bgm() == "title"
    press(game, "confirm")
    assert game.state == "menu", "Enterで難易度選択へ（まだゲームは始まらない）"
    press(game, "confirm")
    assert game.state == "play"


def test_other_keys_do_nothing_on_title(game_class):
    game = new_game(game_class)
    game.restart_game()  # R
    game.choose_difficulty(0)  # 1キー
    game.move_menu(1)  # ↓
    press(game, "pause", "decoy", "cloak", "flash")
    assert game.state == "title"


def test_title_only_at_launch(game_class):
    """難易度選択に戻る（M）・クリアの後は、タイトル画面ではなく難易度選択に戻る。"""
    game = new_game(game_class)
    press(game, "confirm")
    game.start_game(NORMAL)
    game.open_menu()
    assert game.state == "menu"


@pytest.mark.parametrize(
    ("window", "image", "expected"),
    [
        (2.0, 1.0, (1.0, 2.0)),  # 画面の方が横長：横を合わせ、上下を切る
        (1.0, 2.0, (2.0, 1.0)),  # 画面の方が縦長：縦を合わせ、左右を切る
        (1.5, 1.5, (1.0, 1.0)),
    ],
)
def test_cover_scale(window, image, expected):
    from stealth_game.app.title import cover_scale  # Panda3Dを差し替えた後で読み込む

    assert cover_scale(window, image) == pytest.approx(expected)
