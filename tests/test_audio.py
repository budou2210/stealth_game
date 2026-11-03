"""BGMと効果音を鳴らす場面のテスト（音は偽物に差し替えて、鳴らした記録だけを見る）。"""

from unittest.mock import MagicMock

from stealth_game.app.audio import BGM_FILES, CHASE_BGM_HOLD, SOUND_FILES
from stealth_game.constants import CLOAK_WARN_TIME
from stealth_game.difficulty import NORMAL
from stealth_game.guard import Guard


def with_fake_sounds(game):
    game.sounds = {name: MagicMock() for name in SOUND_FILES}
    game.bgm = {name: MagicMock() for name in BGM_FILES}
    game.loops_playing = set()
    game.bgm_name = None
    game.bgm_playing = False
    return game


def new_game(game_class):
    game = with_fake_sounds(game_class())
    game.down = set()
    game.is_down = lambda name: name in game.down
    return game


def started(game_class, cfg=NORMAL):
    game = new_game(game_class)
    game.start_game(cfg)
    return game


def played(game, name):
    return game.sounds[name].play.call_count


def test_missing_files_are_skipped(game_class):
    game = game_class()
    assert game.load_audio("no_such_file.ogg") is None
    game.sounds["item"] = None
    game.play_sound("item")  # ファイルがなくても止まらない
    game.set_loop("item", True)


def test_menu_sounds(game_class):
    game = new_game(game_class)
    game.open_menu()
    game.move_menu(1)
    assert played(game, "cursor") == 1
    game.choose_difficulty(None)
    assert played(game, "confirm") == 1
    assert game.state == "play"


def test_item_and_exit_open(game_class):
    game = started(game_class)
    for i, cell in enumerate(game.item_cells[:-1]):
        game.items_collected.add(i)
    game.player.x, game.player.y = (c + 0.5 for c in game.item_cells[-1])
    game.collect_items()
    assert played(game, "item") == 1
    assert played(game, "exit_open") == 1, "8個目で出口が開く音"


def test_denied_when_nothing_to_use(game_class):
    game = started(game_class)
    game.use_cloak()
    game.use_flash()
    game.place_decoy()
    assert played(game, "denied") == 3


def test_helpers(game_class):
    game = started(game_class)
    game.player.safe = False
    game.held = {"cloak": 1, "flash": 1, "decoy": 1}
    game.use_cloak()
    assert played(game, "denied") == 0
    assert not any(s.play.called for s in game.sounds.values()), "透明化を使うときは無音"
    game.use_flash()
    assert played(game, "flash") == 1
    floor = next(c for c in game.world.guard_cells if c not in game.world.safe_cells)
    game.player.x, game.player.y = floor[0] + 0.5, floor[1] + 0.5
    game.place_decoy()
    assert played(game, "decoy_place") == 1
    game.update_placed_decoys(5.0)
    assert played(game, "decoy_fire") == 1


def test_cloak_warning_only_in_last_seconds(game_class):
    game = started(game_class)
    game.cloak_timer = CLOAK_WARN_TIME + 1
    game.update_audio(0.0)
    assert "cloak_warning" not in game.loops_playing
    game.cloak_timer = CLOAK_WARN_TIME - 0.5
    game.update_audio(0.0)
    assert "cloak_warning" in game.loops_playing
    game.cloak_timer = 0.0
    game.update_audio(0.0)
    assert "cloak_warning" not in game.loops_playing


def test_footsteps_while_running(game_class):
    game = started(game_class)
    game.player.moving, game.player.sneaking = True, False
    game.update_audio(0.0)
    assert "footstep" in game.loops_playing
    game.player.sneaking = True
    game.update_audio(0.0)
    assert "footstep" not in game.loops_playing


def test_whistle_when_spotted(game_class):
    game = started(game_class)
    game.play_event_sounds()
    assert played(game, "spotted") == 0
    game.guards[0].spot(game.player)
    game.play_event_sounds()
    assert played(game, "spotted") == 1


def test_bgm_switches_with_chase_and_pause(game_class):
    game = new_game(game_class)
    game.open_menu()
    game.update_audio(1 / 60)
    assert game.bgm["title"].play.called
    game.start_game(NORMAL)
    game.update_audio(1 / 60)
    assert game.bgm["sneak"].play.called
    assert game.bgm["title"].stop.called

    game.guards[0].state = Guard.CHASE
    game.update_audio(1 / 60)
    assert game.bgm_name == "chase" and game.bgm["chase"].play.called
    game.guards[0].state = Guard.PATROL
    game.update_audio(CHASE_BGM_HOLD / 2)
    assert game.bgm_name == "chase", "追跡が終わってもしばらくは追跡の曲のまま"
    game.bgm["sneak"].setTime.reset_mock()
    game.update_audio(CHASE_BGM_HOLD)
    assert game.bgm_name == "sneak"
    game.bgm["sneak"].setTime.assert_called_once_with(game.bgm_positions["sneak"])

    game.toggle_pause()
    game.update_audio(0.0)
    assert not game.bgm_playing
    game.toggle_pause()
    game.update_audio(1 / 60)
    assert game.bgm_playing


def run_scheduled(game):
    """run_later で予約した処理（ジングルと画面の切り替え）を、待たずに実行する。"""
    for call in game.taskMgr.doMethodLater.call_args_list:
        delay, function, name = call.args
        function(None)
    game.taskMgr.doMethodLater.reset_mock()


def test_win_jingles_and_new_record_screen(game_class):
    game = started(game_class)
    game.update_audio(1 / 60)
    game.message_text.setText.reset_mock()
    game.on_win()
    assert played(game, "clear") == 1
    assert played(game, "new_record") == 0, "新記録のジングルはクリアのジングルの後"
    assert game.message_text.setText.call_args.args[0] == game.text["win"].format(time=game.elapsed)
    game.update_audio(1 / 60)
    assert not game.bgm_playing, "クリアしたらBGMを止める"
    run_scheduled(game)
    assert played(game, "new_record") == 1
    assert game.message_text.setText.call_args.args[0] == game.text["new_record"], "新記録の文字はジングルと同時"


def test_game_over_screen_follows_jingle(game_class):
    game = started(game_class)
    game.update_audio(1 / 60)
    game.lives = 1
    game.on_caught()
    assert game.state == "lose"
    assert played(game, "caught") == 1
    assert played(game, "lose") == 0
    assert game.message_text.setText.call_args.args[0] == game.text["lose"].format(lives=0)
    run_scheduled(game)
    assert played(game, "lose") == 1
    assert game.message_text.setText.call_args.args[0] == game.text["game_over"]


def test_restart_cancels_scheduled_jingles(game_class):
    game = started(game_class)
    game.lives = 1
    game.on_caught()
    game.taskMgr.remove.reset_mock()
    game.restart_game()
    game.taskMgr.remove.assert_called()


def test_bgm_stops_when_caught(game_class):
    game = started(game_class)
    game.guards[0].state = Guard.CHASE
    game.update_audio(1 / 60)
    assert game.bgm_name == "chase" and game.bgm_playing
    game.on_caught()  # 普通はライフ2なので、まだゲームオーバーではない
    assert game.state == "caught"
    game.guards[0].state = Guard.PATROL
    game.update_audio(1 / 60)
    assert not game.bgm_playing, "捕まったら、追跡の曲でも一旦止める"
    game.update_caught(10.0)
    game.update_audio(1 / 60)
    assert game.bgm_name == "sneak" and game.bgm_playing, "スタート部屋に戻ったらすぐ潜入の曲"
