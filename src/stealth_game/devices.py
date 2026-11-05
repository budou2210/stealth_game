"""地獄より上の難易度（超越）の仕掛け（ロジックのみ。描画はapp側）。

- 見張り番：動かずに、その場で向きだけを順に変える鬼（guard.py の Guard に look を渡して作る）
- 監視カメラ：壁の角に付いて首を振る。映ると、近くの鬼が映った場所を調べに来る
- 時間で開け閉めする扉：区画どうしの境目の真ん中の扉。決まった周期で開け閉めする
- 鳴る床：乗ると音が出て、近くの鬼が調べに来る。候補の中から、ゲームごとにランダムに選ぶ

どれも、見つかっていない間はプレイヤーの動きと関係なく時刻だけで決まる（鳴る床は踏んだときだけ）。
そのため、ボットは先読みして避けられる。
"""

import math
import random

from .constants import (
    CAMERA_HALF_ANGLE,
    CAMERA_PERIOD,
    CAMERA_SWEEP,
    CAMERA_VIEW_RANGE,
    DOOR_OPEN_RATE,
    DOOR_PERIOD,
)
from .grid import cell_center
from .layout import BASE_SIZE, MAP_H, MAP_W, QUADRANTS, SEAM_DOORS_ALONG_X, SEAM_DOORS_ALONG_Y
from .mapgen import mirror_cell, mirror_rect

# 見張り番の持ち場（元の区画のセル）と、見る向きの順番（度。元の区画での向き）
BASE_SENTRY_POST = (10, 10)
BASE_SENTRY_LOOK = (0, 90, 180, 270)

# 監視カメラ（元の区画）：付ける角のセルと、首を振る中心の向き（度）。上段の右の部屋の、中央寄りの角
BASE_CAMERA = ((18, 18), 225)

# 時間で開け閉めする扉：境目の扉のうち、真ん中のもの（縦の境目の y=9、横の境目の x=8 と、その鏡写し）
TIMED_SEAM_Y = 9
TIMED_SEAM_X = 8

# 鳴る床の候補になる、部屋の扉（元の区画。両端を含む (x1, y1, x2, y2)）と、スタート部屋の扉かどうか。
# スタート部屋（左下）の扉は、鏡写しで出口の部屋の扉にもなる。どちらも候補から外す
BASE_ROOM_DOORS = [
    ((7, 3, 7, 4), True),  # 左下の部屋の東
    ((3, 7, 4, 7), True),  # 左下の部屋の北
    ((11, 3, 11, 4), False),  # 右下の部屋の西
    ((14, 7, 15, 7), False),  # 右下の部屋の北
    ((10, 15, 10, 16), False),  # 上段の左右の部屋の間
    ((4, 12, 5, 12), False),  # 上段の天井（左）
    ((14, 12, 15, 12), False),  # 上段の天井（右）
]
START_QUADRANTS = {(0, 0), (1, 1)}  # スタート部屋・出口の部屋がある区画


def mirror_heading(degrees, qx, qy):
    """元の区画での向き（度）を、鏡写しの区画での向き（ラジアン）にする。"""
    angle = math.radians(degrees)
    x, y = math.cos(angle), math.sin(angle)
    if qx:
        x = -x
    if qy:
        y = -y
    return math.atan2(y, x)


def rect_cells(rect):
    x1, y1, x2, y2 = rect
    return frozenset((x, y) for x in range(x1, x2 + 1) for y in range(y1, y2 + 1))


# --- 見張り番 -----------------------------------------------------------
def build_sentry_posts():
    """[(持ち場のセル, 見る向きの列（ラジアン）)]。区画ごとに1人。"""
    return [
        (mirror_cell(BASE_SENTRY_POST, qx, qy), tuple(mirror_heading(d, qx, qy) for d in BASE_SENTRY_LOOK))
        for qx, qy in QUADRANTS
    ]


# --- 監視カメラ -----------------------------------------------------------
class SecurityCamera:
    def __init__(self, cell, center, phase):
        """cell: 付ける角のセル。center: 首を振る中心の向き（ラジアン）。phase: 首振りのずれ（周期の割合）。"""
        cx, cy = cell_center(cell)
        back = center + math.pi  # 角（壁）の側へ寄せて付ける
        self.cell = cell
        self.x = cx + 0.45 * math.cos(back)
        self.y = cy + 0.45 * math.sin(back)
        self.center = center
        self.phase = phase

    def heading_at(self, t):
        return self.center + CAMERA_SWEEP * math.sin(2 * math.pi * (t / CAMERA_PERIOD + self.phase))

    def view_range_for(self, player, cfg):
        return CAMERA_VIEW_RANGE * (cfg.sneak_view_rate if player.sneaking else 1.0)

    def sees(self, world, player, cfg, t):
        """時刻 t にプレイヤーが映っているか（鬼の視界と同じく、忍び足だと距離が縮み、壁で遮られる）。"""
        if player.safe or player.invisible:
            return False
        dist = math.hypot(player.x - self.x, player.y - self.y)
        if dist > self.view_range_for(player, cfg):
            return False
        angle = math.atan2(player.y - self.y, player.x - self.x)
        diff = (angle - self.heading_at(t) + math.pi) % (2 * math.pi) - math.pi
        if abs(diff) > CAMERA_HALF_ANGLE:  # 鬼と違い、すぐそばでも視界の外なら気づかない
            return False
        return world.has_line_of_sight(self.x, self.y, player.x, player.y)


def build_cameras():
    """区画ごとに1台。首振りのタイミングは、台ごとに周期の4分の1ずつずらす。"""
    cell, center = BASE_CAMERA
    return [
        SecurityCamera(mirror_cell(cell, qx, qy), mirror_heading(center, qx, qy), i / len(QUADRANTS))
        for i, (qx, qy) in enumerate(QUADRANTS)
    ]


# --- 時間で開け閉めする扉 ----------------------------------------------------
class TimedDoor:
    def __init__(self, cells, phase):
        self.cells = frozenset(cells)
        self.phase = phase  # 周期のずれ（割合）
        self.closed = False

    def wants_closed(self, t):
        """時刻 t に閉まっているはずか（周期の前半は開き、後半は閉まる）。"""
        return (t / DOOR_PERIOD + self.phase) % 1.0 >= DOOR_OPEN_RATE

    def seconds_until_close(self, t):
        """時刻 t から、次に閉まる時刻までの秒数（閉まっている間は0）。"""
        frac = (t / DOOR_PERIOD + self.phase) % 1.0
        return max(0.0, (DOOR_OPEN_RATE - frac) * DOOR_PERIOD)

    def bounds(self):
        """扉のセル全体を囲む四角 (x1, y1, x2, y2)（x2, y2 は端のセルの外側の座標）。"""
        xs = [x for x, _ in self.cells]
        ys = [y for _, y in self.cells]
        return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def seam_door_cells():
    """区画どうしの境目の扉（2×2マス）を {(向き, 元の位置, 鏡写しか): セルの集まり} で返す。"""
    lo, hi = BASE_SIZE - 1, BASE_SIZE
    doors = {}
    for y0 in SEAM_DOORS_ALONG_Y:
        for mirrored, y in ((False, y0), (True, MAP_H - 2 - y0)):
            doors[("y", y0, mirrored)] = rect_cells((lo, y, hi, y + 1))
    for x0 in SEAM_DOORS_ALONG_X:
        for mirrored, x in ((False, x0), (True, MAP_W - 2 - x0)):
            doors[("x", x0, mirrored)] = rect_cells((x, lo, x + 1, hi))
    return doors


def build_timed_doors():
    """境目の真ん中の扉4つ。開け閉めのタイミングは、扉ごとに周期の4分の1ずつずらす。"""
    doors = seam_door_cells()
    keys = [("y", TIMED_SEAM_Y, False), ("x", TIMED_SEAM_X, False), ("y", TIMED_SEAM_Y, True),
            ("x", TIMED_SEAM_X, True)]
    return [TimedDoor(doors[key], i / len(keys)) for i, key in enumerate(keys)]


# --- 鳴る床 -------------------------------------------------------------
def noisy_floor_candidates(world):
    """鳴る床を置ける場所（扉の幅いっぱいのセルの集まり）。スタート部屋・出口の部屋の扉と、時間で開け閉めする扉は除く。"""
    candidates = []
    for qx, qy in QUADRANTS:
        for rect, start_room in BASE_ROOM_DOORS:
            if start_room and (qx, qy) in START_QUADRANTS:
                continue
            candidates.append(rect_cells(mirror_rect(rect, qx, qy)))
    for (axis, base, _), cells in sorted(seam_door_cells().items()):
        if (axis, base) not in (("y", TIMED_SEAM_Y), ("x", TIMED_SEAM_X)):
            candidates.append(cells)
    return [c for c in candidates if all(not world.walls[y][x] for x, y in c)]


def pick_noisy_floors(world, count):
    """候補からcount個をランダムに選ぶ（ゲームを始めるたびに変わる）。"""
    candidates = noisy_floor_candidates(world)
    return random.sample(candidates, min(count, len(candidates)))
