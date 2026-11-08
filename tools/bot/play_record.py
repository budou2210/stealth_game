"""ボットの挑戦の記録を、本物のゲーム画面で再生する。

使い方（プロジェクトのフォルダで）:
    uv run python -m tools.bot.play_record bot_results/hell/wins/seed_123.json
    uv run python -m tools.bot.play_record <記録のファイル> --speed 2   （2倍速）

同じ乱数の種・同じ入力・同じコマの間隔（1/30秒）で進めるので、ボットが試したとおりの動きになる。
再生中に使えるキー: Tab（視点）・F（足音の範囲）・P（一時停止）・R（最初から再生し直す）・Esc（終了）。
M（難易度選択）は使えない。クリアしてもベストタイムには記録しない（ボットの記録なので）。
"""

import argparse
import json
import random
from pathlib import Path

from panda3d.core import ClockObject

from stealth_game.app.game import StealthGame
from stealth_game.difficulty import MENU_LEVELS
from stealth_game.texts import TEXTS

from .planner import decode_keys
from .sim import DT

RECORDED = {"up", "down", "left", "right", "sneak"}  # 記録から押すキー（それ以外は本物のキーボード）

# 再生中の案内（「M: 難易度選択」は出さない）
REPLAY_TEXTS = {
    "ja": {
        "controls": "再生中（ボットの記録）  Tab: 視点切替  F: 足音の範囲  P: 一時停止  R: 最初から再生  Esc: 終了",
        "win": "ミッション成功！ ({time:.1f}秒)\nボットの記録なので、ベストタイムには残りません\nR: 最初から再生  Esc: 終了",
        "game_over": "ゲームオーバー\nR: 最初から再生  Esc: 終了",
        "paused": "一時停止中\nP: 再開  R: 最初から再生\nEsc: 終了",
        "finished": "記録はここまでです\nR: 最初から再生  Esc: 終了",
    },
    "en": {
        "controls": "Replaying bot record  Tab: view  F: noise range  P: pause  R: replay from start  Esc: quit",
        "win": "MISSION COMPLETE! ({time:.1f}s)\nBot record: not saved as a best time\nR: replay from start  Esc: quit",
        "game_over": "GAME OVER\nR: replay from start  Esc: quit",
        "paused": "PAUSED\nP: resume  R: replay from start\nEsc: quit",
        "finished": "End of record\nR: replay from start  Esc: quit",
    },
}


class Replay(StealthGame):
    def __init__(self, record, speed):
        super().__init__()
        self.record_seed = record["seed"]
        self.record_level = record.get("level", "hell")  # 古い記録には難易度がない（地獄）
        self.recorded_keys = decode_keys(record["keys"])
        self.replay_text = REPLAY_TEXTS["ja" if self.text is TEXTS["ja"] else "en"]
        self.speed = speed
        self.taskMgr.remove("update")
        self.open_menu()
        self.start_replay()
        self.taskMgr.add(self.replay_update, "replay")

    def start_replay(self):
        """記録の最初から再生する（同じ種で始めるので、配置も警備員の動きも記録と同じになる）。"""
        self.frame = 0
        self.current = frozenset()
        self.pending = 0.0
        self.finished_shown = False
        random.seed(self.record_seed)
        self.start_game(next(cfg for cfg in MENU_LEVELS if cfg.key == self.record_level))

    # --- ゲームの動きを、再生用に変える部分 -------------------------------
    def bind_events(self):
        super().bind_events()
        self.ignore("m")  # 難易度選択には戻れない（戻ると記録と合わなくなる）

    def restart_game(self):
        """R：最初から再生し直す（ゲームだけを始め直すと、配置が変わり入力も途中から続いてしまう）。"""
        self.start_replay()

    def on_win(self):
        """クリア。ボットの記録なので、ベストタイムには残さない。"""
        self.state = "win"
        self.stop_bgm()
        self.play_sound("clear")
        self.message_text.setText(self.replay_text["win"].format(time=self.elapsed))

    def show_game_over(self):
        self.play_sound("lose")
        self.message_text.setText(self.replay_text["game_over"])

    def toggle_pause(self):
        super().toggle_pause()
        if self.state == "paused":
            self.message_text.setText(self.replay_text["paused"])

    def controls_line(self):
        return self.replay_text["controls"]

    def is_down(self, name):
        if name in RECORDED:
            return name in self.current
        return super().is_down(name)

    # --- 毎フレーム -----------------------------------------------------
    def advance(self):
        """1コマ進める。ゲームが進んだコマだけ記録の入力を1つ使う（一時停止中や、P を押したコマは使わない）。"""
        if self.state == "play" and self.frame < len(self.recorded_keys):
            self.current = self.recorded_keys[self.frame]
        else:
            self.current = frozenset()
        before = self.state
        self.step(DT)
        if before == "play" and self.last_step_played and self.frame < len(self.recorded_keys):
            self.frame += 1
        if self.state == "play" and self.frame >= len(self.recorded_keys) and not self.finished_shown:
            self.finished_shown = True  # 記録が途中で終わっている（行き詰まりであきらめた回など）
            self.message_text.setText(self.replay_text["finished"])

    def replay_update(self, task):
        self.pending += min(ClockObject.getGlobalClock().getDt(), 0.1) * self.speed
        while self.pending >= DT:
            self.pending -= DT
            self.advance()
        return task.cont


def main():
    parser = argparse.ArgumentParser(description="ボットの記録を本物のゲーム画面で再生する")
    parser.add_argument("record", type=Path, help="記録のファイル（bot_results/<難易度>/wins/ や runs/ の .json）")
    parser.add_argument("--speed", type=float, default=1.0, help="再生の速さ（2なら2倍速）")
    args = parser.parse_args()
    record = json.loads(args.record.read_text(encoding="utf-8"))
    Replay(record, args.speed).run()


if __name__ == "__main__":
    main()
