"""全体表示カメラの位置の計算（マップがHUDに被らず画面に収まる距離を求める）。"""

import math

from ..layout import LEVEL_BOUNDS
from ..theme import OVERVIEW_DIRECTION, OVERVIEW_LOOK, WALL_HEIGHT


def overview_axes():
    """全体表示カメラの (後ろ向き, 前, 右, 上) の単位ベクトル。lookAtと同じ向き。"""
    dx, dy, dz = OVERVIEW_DIRECTION
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    back = (dx / length, dy / length, dz / length)
    fwd = (-back[0], -back[1], -back[2])
    side = math.hypot(fwd[0], fwd[1])
    right = (fwd[1] / side, -fwd[0] / side, 0.0)
    up = (
        right[1] * fwd[2] - right[2] * fwd[1],
        right[2] * fwd[0] - right[0] * fwd[2],
        right[0] * fwd[1] - right[1] * fwd[0],
    )
    return back, fwd, right, up


def overview_position(distance):
    back = overview_axes()[0]
    return tuple(OVERVIEW_LOOK[i] + back[i] * distance for i in range(3))


def dot3(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def map_fits_on_screen(distance, fov, bottom):
    """マップの8つの角（壁の高さ込み）が、画面内かつbottomより上に映るか。"""
    _, fwd, right, up = overview_axes()
    pos = overview_position(distance)
    tan_h = math.tan(math.radians(fov[0]) / 2)
    tan_v = math.tan(math.radians(fov[1]) / 2)
    for x in (LEVEL_BOUNDS[0], LEVEL_BOUNDS[2]):
        for y in (LEVEL_BOUNDS[1], LEVEL_BOUNDS[3]):
            for z in (0, WALL_HEIGHT):
                rel = (x - pos[0], y - pos[1], z - pos[2])
                depth = dot3(rel, fwd)
                if depth <= 0:
                    return False
                sx = dot3(rel, right) / depth / tan_h
                sz = dot3(rel, up) / depth / tan_v
                if abs(sx) > 1 or not bottom <= sz <= 1:
                    return False
    return True


def overview_distance(fov, bottom):
    """マップがbottomより上に収まる、いちばん近いカメラ距離を二分探索で求める。"""
    near, far = 1.0, 1000.0
    for _ in range(40):
        mid = (near + far) / 2
        if map_fits_on_screen(mid, fov, bottom):
            far = mid
        else:
            near = mid
    return far
