"""ゲームの調整値（速度・距離・時間など）。難易度ごとの値は difficulty.py にある。"""

import math

PLAYER_RUN_SPEED = 4.6
PLAYER_SNEAK_SPEED = 2.2
PLAYER_RADIUS = 0.3

GUARD_PATROL_SPEED = 2.0
GUARD_TURN_RATE = math.radians(300)

NEAR_SENSE_RADIUS = 1.3  # この距離内なら背後でも気づかれる
CHASE_HEAR_RATE = 1.5  # 追跡中は足音をより遠くから聞き取る
SOUND_WALL_MUFFLE = 0.5  # 壁で遮られた足音は、聞こえる距離がこの倍率になる（1.0で壁の影響なし）
DIRECT_PURSUIT_RANGE = 3.0  # この距離内で視界が通れば経路を使わず直接追う
CATCH_DISTANCE = 0.75
FLANK_MIN_DISTANCE = 5.0  # 挟み撃ち：プレイヤーからこれより遠い追っ手（2番手以降）が回り込む
FLANK_GOAL_FREE = 2  # 挟み撃ち：目的地からこのマス数以内は、近い鬼の道でも避けない
RESPOND_REPLAN = (0.25, 0.45)  # 応援で駆けつける途中のA*再計算間隔（遠くにいるので追跡より間引く）

WANDER_MIN_DISTANCE = 8  # 徘徊型：次の目的地は今の場所からこのマス数以上離す
WANDER_MAX_DISTANCE = 24  # 徘徊型：遠すぎる目的地は選ばない（A*の負荷対策）
WANDER_PAUSE_RANGE = (0.5, 1.5)  # 目的地に着いたとき辺りを見回す秒数
FOCUS_REACH = 36  # 難しい：この距離内にある注目地点（プレイヤー等）だけを狙う

ITEMS_PER_QUADRANT = 2  # 4区画で8個
ITEM_MIN_SPACING = 8
ITEM_MIN_DISTANCE_FROM_START = 12
ITEM_MIN_DISTANCE_FROM_EXIT = 8
ITEM_PICKUP_DISTANCE = 0.7
ITEMS_DROPPED_ON_CATCH = 2  # 捕まったとき落とすアイテムの数（持っている数が上限）
CAUGHT_FREEZE_TIME = 1.5  # 捕まってからスタート部屋へ戻るまでの秒数

EXCLAIM_TIME = 1.2  # 「！」を表示しておく秒数
EXCLAIM_SCREEN_SIZE = 0.075  # 追従表示での「！」の大きさ（カメラからの距離に比例させる）
EXCLAIM_OVERVIEW_SIZE = 0.9  # 全体表示での「！」の大きさ（鬼の体と同じくらい）
EXCLAIM_POP_TIME = 0.18  # 出た瞬間に大きく弾んでから元の大きさに戻るまでの秒数
EXCLAIM_BLINK_TIME = 0.6  # 出てからこの秒数の間、文字の色が点滅する

# お助けアイテムは3種類。"cloak"=透明化、"flash"=スタン（閃光で目くらまし）、"decoy"=音の罠
# 並び順は、操作説明・所持数の表示・出現のお知らせの順番になる
HELPER_SPAWN_INTERVAL = 20.0  # 種類ごとに、この秒数おきに1個出る（拾うとその種類を数え直す）
HELPER_MAX_HELD = {"cloak": 1, "flash": 1, "decoy": 2}  # 種類ごとに持てる数（上限まで持っている種類は出ない）
HELPER_SPAWN_DISTANCE = (6, 18)  # 出現位置とプレイヤーとの距離（マス）の範囲
CLOAK_TIME = 10.0  # 透明化が続く秒数
CLOAK_WARN_TIME = 2.0  # 透明化の残りがこの秒数を切ると、プレイヤーが点滅して知らせる
DECOY_FUSE = 3.0  # 設置してから音が鳴るまでの秒数
DECOY_RING_TIME = 0.7  # 音の広がりを表示する秒数
STUN_TIME_SEEN = 10.0  # スタン：プレイヤーを視界に入れていた鬼が動けない秒数
STUN_TIME_NEAR = 5.0  # スタン：見ていなくても周囲にいた鬼が動けない秒数
FLASH_RADIUS = 12.0  # スタンの「周囲」の範囲（音の罠の16より少し狭い。壁越しにも届く）
STUN_SPIN_RATE = math.radians(240)  # 目がくらんでいる間、その場で回る速さ（見た目）

# --- 地獄より上の難易度（超越）の仕掛け。置き場所は devices.py ---
SENTRY_DWELL = 2.5  # 見張り番：1つの向きを見ている秒数（その後、次の向きへ回る）
CAMERA_VIEW_RANGE = 9.0  # 監視カメラの視界の長さ（忍び足なら難易度の忍び足の倍率がかかる）
CAMERA_HALF_ANGLE = math.radians(22)  # 監視カメラの視界の半角
CAMERA_SWEEP = math.radians(40)  # 監視カメラが首を振る幅（中心から片側）
CAMERA_PERIOD = 8.0  # 監視カメラが首を1往復させる秒数
CAMERA_CALL_RADIUS = 16.0  # 監視カメラに映ると、この距離内の鬼が映った場所を調べに来る（壁越しにも届く）
CAMERA_ALARM_COOLDOWN = 3.0  # 一度鳴ったカメラが、次に鳴れるまでの秒数
DOOR_PERIOD = 10.0  # 時間で開け閉めする扉の1周期の秒数
DOOR_OPEN_RATE = 0.5  # 1周期のうち開いている割合（前半が開き、後半が閉まる）
DOOR_WARN_TIME = 1.5  # 閉まるこの秒数前から、開いている扉の枠を点滅させて知らせる
FLOOR_RUN_RADIUS = 16.0  # 鳴る床：走って乗ったときに音が届く距離（音の罠と同じ。壁越しにも届く）
FLOOR_SNEAK_RADIUS = 6.0  # 鳴る床：忍び足で乗ったときに音が届く距離
FLOOR_COOLDOWN = 3.0  # 鳴る床：一度鳴った床が、次に鳴れるまでの秒数
