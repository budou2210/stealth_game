"""ベストタイムの保存・読み込みのテスト。"""

from pathlib import Path

from stealth_game.records import load_records, records_path, save_records, update_best


def test_path_follows_override(records_dir):
    assert records_path() == records_dir / "records.json"


def test_missing_or_broken_file_gives_empty(records_dir):
    path = records_dir / "records.json"
    assert load_records(path) == {}
    records_dir.mkdir()
    path.write_text("{ broken", encoding="utf-8")
    assert load_records(path) == {}


def test_save_and_load_round_trip(records_dir):
    path = records_dir / "records.json"
    assert save_records(path, {"hard": 283.6, "easy": 95.25})
    assert load_records(path) == {"hard": 283.6, "easy": 95.25}


def test_update_best_only_when_faster():
    records = {}
    assert update_best(records, "normal", 120.0), "初めてのクリアは新記録"
    assert not update_best(records, "normal", 130.0)
    assert not update_best(records, "normal", 120.0), "同じタイムは新記録にしない"
    assert update_best(records, "normal", 110.5)
    assert records == {"normal": 110.5}


def test_default_location_is_project_saves(monkeypatch):
    """ふだんはプロジェクトのフォルダの saves/ に保存する（.gitignore で GitHub には上げない）。"""
    monkeypatch.delenv("STEALTH_GAME_DATA_DIR")
    root = Path(__file__).resolve().parents[1]
    assert records_path() == root / "saves" / "records.json"
    assert "saves/" in (root / ".gitignore").read_text(encoding="utf-8").splitlines()
