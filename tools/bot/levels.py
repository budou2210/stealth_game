"""ボットが遊ぶ難易度。標準は地獄。run.py などの --level で選ぶ（transcend＝超越）。

選んだ難易度は環境変数 BOT_LEVEL に入れる。こうしておくと、同時に走らせる別のプロセスにも伝わる。
結果のフォルダは、プロジェクトのフォルダの bot_results/<難易度>（bot_results/hell、bot_results/transcend）に分ける
（危険度の地図も別々になる）。
"""

import os
from pathlib import Path

from stealth_game.difficulty import DIFFICULTIES

from .options import is_fast

LEVEL_ENV = "BOT_LEVEL"
LEVELS = ("hell", "transcend")  # ボットで試せる難易度
# 超越用の改造（予測の使い回し・視界の計算の丸め・何度も見つかる場所を避ける）を使う難易度。
# 地獄では使わない（地獄は、51.13秒の記録を出したときの動き方のまま）。仕様が違い、地獄では裏目に出たため
TUNED_LEVELS = ("transcend",)
RESULTS_ROOT = Path(__file__).resolve().parents[2] / "bot_results"  # プロジェクトのフォルダ直下


def level_key():
    return os.environ.get(LEVEL_ENV, "hell")


def set_level(key):
    if key not in LEVELS:
        raise ValueError(f"難易度は {', '.join(LEVELS)} のどれか: {key}")
    os.environ[LEVEL_ENV] = key


def level_cfg(key=None):
    key = key or level_key()
    return next(cfg for cfg in DIFFICULTIES if cfg.key == key)


def is_tuned(cfg):
    """その難易度で、超越用の改造を使うか。"""
    return cfg.key in TUNED_LEVELS


def danger_source(results):
    """危険度の地図を読むファイル。--fast で、まだ自分の地図がないときは、ふだんの結果の地図から始める
    （これまでの挑戦で分かった危ない場所を、最初から使えるように）。書き込むのは、いつも results の地図。"""
    path = results / "danger.json"
    if not path.exists() and is_fast():
        normal = RESULTS_ROOT / level_key() / "danger.json"
        if normal.exists():
            return normal
    return path


def results_for(base=RESULTS_ROOT, key=None):
    """結果のフォルダ。--fast のときは別のフォルダ（bot_results/hell_fast など）にして、記録を混ぜない。"""
    key = key or level_key()
    return base / (f"{key}_fast" if is_fast() else key)
