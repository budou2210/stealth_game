# 開発者向けメモ

プレイヤー向けの説明は [README.md](../README.md)、仕様の一覧・設計方針・保留中の案は [design.md](design.md) を参照。

スニーキューブ（SNEAKUBE）は、Panda3D + Python のステルスゲーム。警備員は自作のA*（4方向・マンハッタン距離・`heapq`）で動く。

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

ウィンドウやGPUがなくても動く（ゲーム全体のテストはPanda3Dを差し替えて動かす）。1分半ほどで終わる。
テストでは、マップの壁の見た目の組み立て（`build_level`）を省いている（偽物の部品だと1回約1.6秒かかるため。`tests/conftest.py`）。

| ファイル | 確かめること |
|---|---|
| `tests/test_pathfinding.py` | A*が壁や安全地帯を通らず、最短の経路を返す |
| `tests/test_world.py` | マップがつながっている、視線・当たり判定 |
| `tests/test_guard.py` | 鬼の視界・足音・警戒・スタン・挟み撃ちの役割 |
| `tests/test_items.py` | アイテムが各区画に散らばって置かれる |
| `tests/test_difficulty.py` | 難易度の数値が `docs/design.md` の仕様表どおり |
| `tests/test_hud.py` | 操作説明・出現のお知らせ・足音の範囲の表示と設定 |
| `tests/test_records.py` | ベストタイムの保存・読み込み・更新の判定 |
| `tests/test_devices.py` | 超越の仕掛け：置き場所、見張り番の向き、カメラの視界と呼び出し、扉の開け閉め（人が乗っている間は閉めない）、鳴る床の範囲と鳴り方 |
| `tests/test_replay.py` | ベスト記録のリプレイ：保存・読み込み、記録と再生で展開が同じになる（一時停止・やり直しを挟んでも）、ベスト更新のときだけ保存 |
| `tests/test_pause_and_best.py` | 一時停止で全部止まること、クリア時のベストタイムの記録と表示 |
| `tests/test_audio.py` | BGMの切り替え・効果音を鳴らす場面（音は偽物に差し替える） |
| `tests/test_title.py` | 起動時のタイトル画面、Enterで難易度選択へ進むこと、画像の広げ方 |
| `tests/test_game_simulation.py` | 難易度ごとにボットで30秒遊ばせ、鬼の動きが以前と同じか（指紋で比較） |
| `tests/test_bot.py` | 攻略ボットのシミュレーターが本物と同じ動きになる、記録の再生 |
| `tests/test_time_attack.py` | タイムアタック：鬼・お助けアイテム・仕掛けが出ない、扉が閉まらない、一時停止できない、表示、記録とリプレイ |
| `tests/test_ghost.py` | ゴースト：ゲーム内の小さな進め方（`Run`）が本物と一致、クリア画面・難易度選択の V での再生、位置のつなぎ方、記録の並べ替え |
| `tests/test_time_attack_bot.py` | タイムアタックのボット：順番の動的計画法が全部の並べ方と一致、見通しの判定、仕上げで遅くならない |
| `tests/test_exact_route.py` | 選んだ順番の最短の道と厳密な下限（`tools/bot/exact_route.py`）、足切り、順番の比べ方 |

数値やAIを**意図して**変えたときは、`test_difficulty.py` の表や `test_game_simulation.py` の指紋が失敗する。
失敗メッセージに新しい指紋が出るので、それで書き換える。

### ゲーム全体を動かして確かめるとき

- Panda3Dを使わずに動かすには、`panda3d`と`direct`を`sys.modules[...] = MagicMock()`で差し替え、`ShowBase`をスタブにしてから`stealth_game.app.game`を読み込む（`tests/conftest.py` の `game_class` がこれをしている）。`StealthGame`を作り、`is_down`をボットの入力に差し替えて`update_play(1/60)`などを回す。
  - `update_visuals`はMagicMockの呼び出し記録でメモリを大量に使うので、長時間回すときは外す。
- 挙動比較: 乱数の種とボットの動きを固定し、警備員の位置・状態・経路をフレームごとに比べる（リファクタリング前後で動きが変わっていないかの確認に使う）。
- 実際のPanda3Dでの起動確認は `window-type offscreen` で可能。オフスクリーンでは`mouseWatcherNode`がないので、`bind_events`と`is_down`を差し替える。`base.win.saveScreenshot()` で画面を撮れる。
- 日本語キーボードでは `\` キーが「¥」になり、音の罠のキーとして反応しないことがある（Space でも置ける）。

## 構成

```
src/stealth_game/
├── __init__.py      入口 main()・遊び方の説明
├── __main__.py      python -m stealth_game 用
├── constants.py     ゲームの調整値（速度・距離・時間・お助けアイテム）
├── layout.py        マップの配置データ（壁・扉・スタート・出口・鬼の順路）
├── theme.py         見た目（色・フォント・カメラ）
├── difficulty.py    難易度（Difficulty と EASY〜TRANSCEND、TIME_ATTACK。メニューの並びは MENU_LEVELS）
├── texts.py         画面の文言（日本語／英語）
├── grid.py          セルと座標の変換・マンハッタン距離
├── mapgen.py        マップ生成（鏡写しで2×2に並べる）
├── world.py         World（当たり判定・視線・A*のコスト）
├── pathfinding.py   自作A*
├── player.py        Player
├── guard.py         Guard（鬼のAI）
├── items.py         アイテムの配置
├── records.py       ベストタイムの保存・読み込み
├── replays.py       ベスト記録のリプレイの保存・読み込み
├── devices.py       超越の仕掛け（見張り番の持ち場・監視カメラ・時間で開け閉めする扉・鳴る床の置き場所と動き）
├── ghost.py         タイムアタックのゴースト（ボットが順番・道を決めて動かす。ゲーム内の小さな進め方 Run・記録の並べ替え）
├── route_graph.py   壁の角だけを中継点にした地図（可視グラフ）と最短距離（ゴースト・ボット用）
├── route_order.py   アイテムを回る順番の動的計画法（ゴースト・ボット用）
├── assets/sounds/   BGM・効果音のファイル（魔王魂。一覧は docs/design.md）
├── assets/images/   タイトル画面の画像
├── render/          Panda3Dのメッシュ作成・全体表示カメラの計算
└── app/             ゲーム本体（StealthGame）と機能ごとのMixin
    ├── game.py      StealthGame：進行・捕獲・応援/挟み撃ちの調整・メインループ
    ├── input.py     キー入力
    ├── camera.py    視点とカメラ
    ├── visuals.py   見た目の作成・更新（足音の範囲の表示を含む）
    ├── hud.py       文字・警戒度メーター
    ├── menu.py      難易度選択と設定
    ├── helpers.py   お助けアイテム
    ├── audio.py     BGMと効果音（ファイルの一覧・音量・鳴らす場面）
    ├── replay.py    ベスト記録のリプレイ（プレイ中の記録と、難易度選択の画面からの再生）
    ├── devices.py   超越の仕掛けの進行（Panda3Dを使わない。ボットのシミュレーターも借りる）
    ├── ghost.py     タイムアタックのリプレイに重ねるゴーストの表示
    └── title.py     タイトル画面（起動したときだけ出す）
```

Panda3Dに依存するのは `render/` と `app/` だけ。ほかのモジュール（ロジック）はPanda3Dなしで読み込める。

## 攻略ボット（tools/bot/）

地獄・超越をクリアできることを確かめ、クリアの様子を見るための自動プレイ。タイムアタックの最速の道を探すボット（`time_attack.py`）もある。
使い方とコマンドの一覧は [tools/bot/README.md](../tools/bot/README.md)。

- タイムアタックのボットのうち、ゲーム内のゴーストも使う部分は `src/stealth_game/ghost.py`・`route_graph.py`・`route_order.py`、
  ボットのコマンドだけが使う部分（選んだ順番の最短の道・厳密な下限は `exact_route.py`、別の動かし方は `ta_drive.py`）は `tools/bot/` にある。

- 画面なしのシミュレーター（`sim.py`）は `StealthGame` の処理を借りて動く。ゲーム本体の処理を変えたら `tests/test_bot.py`（シミュレーターと本物の一致）も通ることを確かめる。
- 記録は「乱数の種＋1コマずつの入力」なので、ゲームの動きが変わると古い記録は再生でずれる。
- 結果（プロジェクトのフォルダの `bot_results/<難易度>/`）は .gitignore で外してある。
