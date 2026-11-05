"""ボットが遊ぶ難易度。標準は地獄。run.py などの --level で選ぶ（transcend＝超越）。

選んだ難易度は環境変数 BOT_LEVEL に入れる。こうしておくと、同時に走らせる別のプロセスにも伝わる。
結果のフォルダは、難易度ごとに results/<難易度>（results/hell、results/transcend）に分ける（危険度の地図も別々になる）。
"""

import os

from stealth_game.difficulty import DIFFICULTIES

LEVEL_ENV = "BOT_LEVEL"
LEVELS = ("hell", "transcend")  # ボットで試せる難易度


def level_key():
    return os.environ.get(LEVEL_ENV, "hell")


def set_level(key):
    if key not in LEVELS:
        raise ValueError(f"難易度は {', '.join(LEVELS)} のどれか: {key}")
    os.environ[LEVEL_ENV] = key


def level_cfg(key=None):
    key = key or level_key()
    return next(cfg for cfg in DIFFICULTIES if cfg.key == key)


def results_for(base, key=None):
    key = key or level_key()
    return base / key
