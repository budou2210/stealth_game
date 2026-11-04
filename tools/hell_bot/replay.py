"""ボットの挑戦の記録を、本物のゲーム画面で再生する。

使い方（プロジェクトのフォルダで）:
    uv run python -m tools.hell_bot.replay tools/hell_bot/results/wins/seed_123.json
    uv run python -m tools.hell_bot.replay <記録のファイル> --speed 2   （2倍速）

同じ乱数の種・同じ入力・同じコマの間隔（1/30秒）で進めるので、ボットが試したとおりの動きになる。
再生中も Tab（視点）と F（足音の範囲）は使える。Esc で終了。
"""

import argparse
import json
import random
from pathlib import Path

from direct.task import Task
from panda3d.core import ClockObject

from stealth_game.app.game import StealthGame
from stealth_game.difficulty import HELL

from .planner import decode_keys
from .sim import DT

RECORDED = {"up", "down", "left", "right", "sneak"}  # 記録から押すキー（それ以外は本物のキーボード）


class Replay(StealthGame):
    def __init__(self, record, speed):
        super().__init__()
        self.recorded_keys = decode_keys(record["keys"])
        self.frame = 0
        self.current = frozenset()
        self.speed = speed
        self.pending = 0.0
        self.taskMgr.remove("update")
        self.open_menu()
        random.seed(record["seed"])
        self.start_game(HELL)
        self.taskMgr.add(self.replay_update, "replay")

    def is_down(self, name):
        if name in RECORDED:
            return name in self.current
        return super().is_down(name)

    def replay_update(self, task):
        self.pending += min(ClockObject.getGlobalClock().getDt(), 0.1) * self.speed
        while self.pending >= DT:
            self.pending -= DT
            if self.frame < len(self.recorded_keys) and self.state == "play":
                self.current = self.recorded_keys[self.frame]
                self.frame += 1
            else:
                self.current = frozenset()
            self.step(DT)
        return Task.cont


def main():
    parser = argparse.ArgumentParser(description="ボットの記録を本物のゲーム画面で再生する")
    parser.add_argument("record", type=Path, help="記録のファイル（results/wins/ や results/runs/ の .json）")
    parser.add_argument("--speed", type=float, default=1.0, help="再生の速さ（2なら2倍速）")
    args = parser.parse_args()
    record = json.loads(args.record.read_text(encoding="utf-8"))
    Replay(record, args.speed).run()


if __name__ == "__main__":
    main()
