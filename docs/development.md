# 開発者向けメモ

プレイヤー向けの説明は [README.md](../README.md)、仕様の一覧・設計方針・保留中の案は [design.md](design.md) を参照。

Panda3D + Python のステルスゲーム。警備員は自作のA*（4方向・マンハッタン距離・`heapq`）で動く。

## 起動

```bash
uv run stealth-game
```

`uv run python -m stealth_game` でも起動できる。

## テスト

```bash
uv run pytest
```

**プロジェクトのフォルダ（`stealth_game`）で実行する。** `src` などの下のフォルダで `uv run pytest` とだけ打つと、
そのフォルダの中だけを探して「collected 0 items」になる（そのときは `uv run pytest ../tests` のように場所を指定する）。

ウィンドウやGPUがなくても動く（ゲーム全体のテストはPanda3Dを差し替えて動かす）。30秒ほどで終わる。

| ファイル | 確かめること |
|---|---|
| `tests/test_pathfinding.py` | A*が壁や安全地帯を通らず、最短の経路を返す |
| `tests/test_world.py` | マップがつながっている、視線・当たり判定 |
| `tests/test_guard.py` | 鬼の視界・足音・警戒・スタン・挟み撃ちの役割 |
| `tests/test_items.py` | アイテムが各区画に散らばって置かれる |
| `tests/test_difficulty.py` | 難易度の数値が `docs/design.md` の仕様表どおり |
| `tests/test_hud.py` | 操作説明・出現のお知らせ・足音の範囲の表示と設定 |
| `tests/test_records.py` | ベストタイムの保存・読み込み・更新の判定 |
| `tests/test_pause_and_best.py` | 一時停止で全部止まること、クリア時のベストタイムの記録と表示 |
| `tests/test_game_simulation.py` | 難易度ごとにボットで30秒遊ばせ、鬼の動きが以前と同じか（指紋で比較） |

数値やAIを**意図して**変えたときは、`test_difficulty.py` の表や `test_game_simulation.py` の指紋が失敗する。
失敗メッセージに新しい指紋が出るので、それで書き換える。

## 構成

```
src/stealth_game/
├── __init__.py      入口 main()・遊び方の説明
├── __main__.py      python -m stealth_game 用
├── constants.py     ゲームの調整値（速度・距離・時間・お助けアイテム）
├── layout.py        マップの配置データ（壁・扉・スタート・出口・鬼の順路）
├── theme.py         見た目（色・フォント・カメラ）
├── difficulty.py    難易度（Difficulty と EASY〜HELL）
├── texts.py         画面の文言（日本語／英語）
├── grid.py          セルと座標の変換・マンハッタン距離
├── mapgen.py        マップ生成（鏡写しで2×2に並べる）
├── world.py         World（当たり判定・視線・A*のコスト）
├── pathfinding.py   自作A*
├── player.py        Player
├── guard.py         Guard（鬼のAI）
├── items.py         アイテムの配置
├── records.py       ベストタイムの保存・読み込み
├── render/          Panda3Dのメッシュ作成・全体表示カメラの計算
└── app/             ゲーム本体（StealthGame）と機能ごとのMixin
    ├── game.py      StealthGame：進行・捕獲・応援/挟み撃ちの調整・メインループ
    ├── input.py     キー入力
    ├── camera.py    視点とカメラ
    ├── visuals.py   見た目の作成・更新（足音の範囲の表示を含む）
    ├── hud.py       文字・警戒度メーター
    ├── menu.py      難易度選択と設定
    └── helpers.py   お助けアイテム
```

Panda3Dに依存するのは `render/` と `app/` だけ。ほかのモジュール（ロジック）はPanda3Dなしで読み込める。
