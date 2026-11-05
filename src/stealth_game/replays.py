"""ベスト記録のリプレイの保存と読み込み。

リプレイは「始めた時点の乱数の状態」と「1コマごとの時間の長さ・押していたキー」の記録。
同じ乱数の状態から、同じ時間の長さ・同じキーで1コマずつ進めると、記録したときとまったく同じ展開になる。

保存先はベストタイムと同じフォルダの replays/<難易度のkey>.json.gz（ベストを更新したときだけ書き換える）。
ゲームの調整（警備員の速さなど）を変えると、古いリプレイは途中から動きが合わなくなる。
"""

import gzip
import json
from pathlib import Path

from .records import data_dir

REPLAY_VERSION = 1
REPLAYS_DIR_NAME = "replays"
HELD_KEYS = ("up", "down", "left", "right", "sneak")  # 押している間ずっと効くキー
PRESS_KEYS = ("decoy", "cloak", "flash")  # 押した瞬間に効くキー（お助けアイテム）


def replay_path(key):
    return data_dir() / REPLAYS_DIR_NAME / f"{key}.json.gz"


def encode_inputs(held, presses):
    """そのコマの入力を1つの数にする（押していたキーと、押した瞬間のキーをビットで表す）。"""
    code = 0
    for i, name in enumerate(HELD_KEYS):
        if name in held:
            code |= 1 << i
    for i, name in enumerate(PRESS_KEYS):
        if name in presses:
            code |= 1 << (len(HELD_KEYS) + i)
    return code


def decode_inputs(code):
    """encode_inputs の逆。(押していたキー, 押した瞬間のキー)。"""
    held = frozenset(name for i, name in enumerate(HELD_KEYS) if code & (1 << i))
    presses = frozenset(name for i, name in enumerate(PRESS_KEYS) if code & (1 << (len(HELD_KEYS) + i)))
    return held, presses


def compress_codes(codes):
    """同じ入力が続く部分を [入力, 続いたコマ数] にまとめる。"""
    out = []
    for code in codes:
        if out and out[-1][0] == code:
            out[-1][1] += 1
        else:
            out.append([code, 1])
    return out


def expand_codes(runs):
    codes = []
    for code, count in runs:
        codes.extend([code] * count)
    return codes


def to_state(data):
    """JSON から読んだ乱数の状態（リスト）を random.setstate に渡せる形（タプル）に戻す。"""
    version, internal, gauss = data
    return version, tuple(internal), gauss


def save_replay(path, replay):
    """保存する。書き込めなくてもゲームは止めない（Falseを返す）。"""
    path = Path(path)
    data = {
        "version": REPLAY_VERSION,
        "difficulty": replay["difficulty"],
        "time": replay["time"],
        "random_state": replay["random_state"],
        "dts": replay["dts"],
        "inputs": compress_codes(replay["codes"]),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(json.dumps(data).encode("utf-8")))
    except OSError as error:
        print(f"リプレイを保存できませんでした: {error}")
        return False
    return True


def load_replay(path):
    """リプレイを読む。ファイルがない・壊れている・形式が違うときは None。"""
    try:
        data = json.loads(gzip.decompress(Path(path).read_bytes()).decode("utf-8"))
        if data.get("version") != REPLAY_VERSION:
            return None
        codes = expand_codes(data["inputs"])
        dts = [float(dt) for dt in data["dts"]]
        if len(codes) != len(dts):
            return None
        return {
            "difficulty": data["difficulty"],
            "time": float(data["time"]),
            "random_state": to_state(data["random_state"]),
            "dts": dts,
            "codes": codes,
        }
    except (OSError, ValueError, KeyError, TypeError, EOFError):
        return None
