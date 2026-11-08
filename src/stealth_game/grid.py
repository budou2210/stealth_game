"""マス目（セル）と座標の変換・距離。"""

import math


def cell_center(cell):
    return cell[0] + 0.5, cell[1] + 0.5


def world_to_cell(x, y):
    return int(math.floor(x)), int(math.floor(y))


def box_corners(x, y, radius):
    """中心 (x, y)・半分の幅 radius の四角形の4隅。当たり判定は、この4隅が入るマスで調べる。"""
    return ((x - radius, y - radius), (x + radius, y - radius), (x - radius, y + radius), (x + radius, y + radius))


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])
