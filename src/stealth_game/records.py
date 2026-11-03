"""難易度ごとのベストタイムの保存と読み込み。

保存先はユーザーごとのデータフォルダ（ゲームのフォルダの中には置かない）。
- Windows: %APPDATA%\\stealth_game\\records.json
- Mac: ~/Library/Application Support/stealth_game/records.json
- Linux: $XDG_DATA_HOME（なければ ~/.local/share）/stealth_game/records.json
環境変数 STEALTH_GAME_DATA_DIR を指定すると、そのフォルダに保存する（テスト用）。
"""

import json
import os
import sys
from pathlib import Path

APP_DIR_NAME = "stealth_game"
RECORDS_FILE_NAME = "records.json"


def data_dir():
    override = os.environ.get("STEALTH_GAME_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_DIR_NAME


def records_path():
    return data_dir() / RECORDS_FILE_NAME


def load_records(path):
    """{難易度のkey: ベストタイム(秒)} を返す。ファイルがない・壊れているときは空。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    best = data.get("best_times", {}) if isinstance(data, dict) else {}
    return {key: float(t) for key, t in best.items() if isinstance(t, (int, float)) and t > 0}


def save_records(path, records):
    """保存する。書き込めなくてもゲームは止めない（Falseを返す）。"""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"best_times": records}, indent=2), encoding="utf-8")
    except OSError as error:
        print(f"ベストタイムを保存できませんでした: {error}")
        return False
    return True


def update_best(records, key, time):
    """timeがその難易度のベストより速ければ記録を書き換えてTrue（初めてのクリアも新記録）。"""
    best = records.get(key)
    if best is not None and time >= best:
        return False
    records[key] = time
    return True
