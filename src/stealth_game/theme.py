"""見た目の設定（色・フォント・カメラ・描画）。"""

from .layout import LEVEL_BOUNDS, MAP_H, MAP_W

WALL_HEIGHT = 1.6
CONE_RAYS = 16

# 全体表示のカメラ。注視点と、そこからカメラへ向かう方向（距離は自動で決める）
OVERVIEW_LOOK = ((LEVEL_BOUNDS[0] + LEVEL_BOUNDS[2]) / 2, (LEVEL_BOUNDS[1] + LEVEL_BOUNDS[3]) / 2, 0.0)
OVERVIEW_DIRECTION = (0.0, -MAP_H / 10, MAP_H * 1.3)
# 視点。Tabを押すごとに 全体 → 中間 → 近い → 全体 … と切り替わる（開始時は全体）
CAMERA_MODES = ("overview", "middle", "near")
NEAR_CAMERA_OFFSET = (0.0, -9.0, 22.0)  # 近い視点：プレイヤーから見たカメラの位置
NEAR_LOOK_AHEAD = 1.5  # 近い視点：プレイヤーより少し奥（画面の上側）を見る
MIDDLE_CAMERA_SCALE = 1.8  # 中間視点：近い視点の距離をこの倍率で離す（1区画20×20が収まるくらい）
HUD_MARGIN = 0.02  # 警戒度メーターとマップの間に空けるすき間（画面の高さ2に対する割合）
INITIAL_CAMERA_POS = (MAP_W / 2, MAP_H / 2 - MAP_H / 10, MAP_H * 1.3)
INITIAL_CAMERA_LOOK = (MAP_W / 2, MAP_H / 2, 0)

# 見た目の色
WALL_COLOR = (0.36, 0.40, 0.55, 1)
FLOOR_COLORS = ((0.14, 0.15, 0.20, 1), (0.17, 0.18, 0.24, 1))
WANDERER_PATROL_COLOR = (0.65, 0.35, 0.90, 1)
SAFE_FLOOR_COLOR = (0.13, 0.24, 0.20, 1)
SAFE_DOOR_COLOR = (0.75, 0.45, 0.20, 1)
DECOY_PICKUP_COLOR = (0.30, 0.90, 1.00, 1)
CLOAK_PICKUP_COLOR = (0.95, 0.95, 1.00, 1)
DECOY_PLACED_COLOR = (0.60, 0.95, 1.00, 1)
DECOY_RING_COLOR = (0.40, 0.90, 1.00)
FLASH_PICKUP_COLOR = (1.00, 0.45, 0.75, 1)
FLASH_RING_COLOR = (1.00, 1.00, 0.90)
STUN_COLOR = (0.80, 0.80, 0.70, 1)  # 目がくらんでいる鬼の体の色
# 足音の範囲。外側＝見通しがあれば聞こえる範囲（壁で切れる。警告テープ風の黄黒の縞）、
# 内側＝壁越しでも必ず聞こえる範囲（赤い円）
NOISE_STRIPE_COLORS = ((1.00, 0.85, 0.10, 0.45), (0.05, 0.05, 0.05, 0.45))
NOISE_STRIPE_PERIOD = 1.4  # 縞1組（黄＋黒）の幅に当たる x+y の長さ
NOISE_INNER_COLOR = (1.00, 0.12, 0.08, 0.38)
NOISE_RAYS = 72  # 壁で切れる形を作るために伸ばす線の本数
NOISE_BIN = "noise_range"  # 足音の範囲を描く順番を固定する描画グループの名前
NOISE_BIN_SORT = 25  # 描画グループの順番（床・壁の "opaque" が20、半透明の "transparent" が30）
EXCLAIM_COLOR = (1.00, 0.90, 0.15, 1)
EXCLAIM_BLINK_COLOR = (1.00, 1.00, 1.00, 1)
EXCLAIM_CARD_COLOR = (0.85, 0.08, 0.08, 0.95)  # 「！」の後ろの赤い札
EXCLAIM_FRAME_COLOR = (1.00, 1.00, 1.00, 1)  # 札の白い縁取り
EXCLAIM_FOLLOW_ALPHA = 0.45  # 中間・近い視点での「！」の不透明度（大きく映って邪魔なので透かす）
MENU_TEXT_BG = (0.02, 0.03, 0.06, 0.82)  # 難易度選択の文字の背景（半透明の黒）
PAUSE_DIM_COLOR = (0.0, 0.0, 0.0, 0.5)  # 一時停止中に画面全体へかける暗さ
CONTROLS_SCALE = 0.036  # 画面下の操作説明の文字の大きさ（入りきらないときはこれより小さくする）
CONTROLS_MARGIN = 0.05  # 操作説明の左右の余白
STATE_COLORS = {
    "patrol": (0.25, 0.50, 0.95, 1),
    "search": (1.00, 0.65, 0.10, 1),
    "spotted": (0.95, 0.35, 0.25, 1),
    "chase": (0.90, 0.15, 0.15, 1),
}
CONE_COLORS = {
    "patrol": (1.0, 1.0, 0.3),
    "search": (1.0, 0.6, 0.1),
    "spotted": (1.0, 0.3, 0.1),
    "chase": (1.0, 0.1, 0.1),
}

FONT_CANDIDATES = [
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/YuGothM.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
]
