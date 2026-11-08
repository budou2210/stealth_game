"""タイムアタックのボット（ゴースト）用：壁の角だけを中継点にした地図（可視グラフ）と、そこでの最短距離。

プレイヤーの当たり判定は「中心から ±0.3 の四角形の4隅が、壁のマスに入るか」（World.is_blocked）。
なので、プレイヤーの中心が通れる場所は「壁のマスを四方に0.3ずつ太らせた四角形」の外側になる。
8方向（斜めも同じ速さ）で動くときの移動距離はオクタイル距離 max(dx,dy) + (√2-1)·min(dx,dy) で、
まっすぐ見通せる2点のあいだは、斜めとまっすぐを細かく混ぜれば、この距離のまま線の上をたどれる。
最短の道が曲がるのは、太らせた壁の出っ張った角だけなので、角（数百個）だけを中継点にすればよい。
細かいマス目（0.1マス刻みで16万点）でダイクストラ法を回すより、ずっと少ない計算で済む。

計算量を減らす工夫：
- 地図（角どうしのつながり）はマップが同じなら全部の配置で同じなので、1回だけ作って使い回す。
- 角を通る道は角に沿って曲がるはずなので、角の「出っ張りの向き」に対して、角を素通りする向きや
  壁に突っ込む向きのつながりは、見通しを調べる前に捨てる（調べる組が約4分の1になる）。
- 見通しは、線分を0.3太らせた形が壁のマスに触れるかを、列ごとにまとめて調べる（線分の長さに比例する手間）。
"""

import heapq
import math

from .constants import PLAYER_RADIUS
from .layout import LEVEL_BOUNDS

SQRT2_1 = math.sqrt(2) - 1
CORNER_GAP = 0.02  # 角の中継点を、太らせた壁からこれだけ離して置く
# 道を引くときは、体を少し大きく見る。斜めとまっすぐを混ぜて線をたどると左右に約0.08揺れるので、
# その分の余裕がないと角にこすれて遅くなる
PLAN_RADIUS = PLAYER_RADIUS + 0.04  # 0.02〜0.12で10配置を比べて、一番速かった大きさ


def octile(ax, ay, bx, by):
    dx, dy = abs(ax - bx), abs(ay - by)
    return max(dx, dy) + SQRT2_1 * min(dx, dy)


class Graph:
    def __init__(self, world, radius=PLAN_RADIUS):
        self.world = world
        self.radius = radius
        x1, y1, x2, y2 = LEVEL_BOUNDS
        self.walls = {
            (x, y) for x in range(x1 - 2, x2 + 2) for y in range(y1 - 2, y2 + 2) if world.is_wall(x, y)
        }
        self.corners = []  # [(x, y, sx, sy)]：sx, sy は、壁から離れる向き（±1）
        for gx in range(x1 - 1, x2 + 2):
            for gy in range(y1 - 1, y2 + 2):
                around = [(a, b) for a in (0, 1) for b in (0, 1) if (gx - 1 + a, gy - 1 + b) in self.walls]
                if len(around) != 1:
                    continue  # 出っ張った角は、4マスのうち1マスだけが壁の点
                a, b = around[0]
                sx, sy = 1 - 2 * a, 1 - 2 * b
                off = radius + CORNER_GAP
                x, y = gx + sx * off, gy + sy * off
                if self.point_free(x, y):
                    self.corners.append((x, y, sx, sy))
        self.edges = [[] for _ in self.corners]  # [(相手の番号, 距離)]
        for i, (ax, ay, asx, asy) in enumerate(self.corners):
            for j in range(i + 1, len(self.corners)):
                bx, by, bsx, bsy = self.corners[j]
                if not tangent(bx - ax, by - ay, asx, asy) or not tangent(ax - bx, ay - by, bsx, bsy):
                    continue
                if self.segment_free(ax, ay, bx, by):
                    d = octile(ax, ay, bx, by)
                    self.edges[i].append((j, d))
                    self.edges[j].append((i, d))

    # --- 当たり判定 -----------------------------------------------------
    def point_free(self, x, y, r=None):
        r = self.radius if r is None else r
        return not any(
            (math.floor(x + dx), math.floor(y + dy)) in self.walls for dx in (-r, r) for dy in (-r, r)
        )

    def segment_free(self, x0, y0, x1, y1, r=None):
        """(x0,y0)→(x1,y1) を、中心から ±r の四角形を引きずって動いたとき、壁のマスに触れないか（正確な判定）。
        r を省くと、道を引くときの大きさ（PLAN_RADIUS）。"""
        r = self.radius if r is None else r
        if x0 > x1:
            x0, y0, x1, y1 = x1, y1, x0, y0
        dx = x1 - x0
        for c in range(math.floor(x0 - r), math.floor(x1 + r) + 1):
            lo, hi = max(c - r, x0), min(c + 1 + r, x1)  # この列（の左右 r 以内）にいる間の中心の x
            if lo > hi:
                continue
            if dx > 1e-12:
                ya, yb = y0 + (y1 - y0) * (lo - x0) / dx, y0 + (y1 - y0) * (hi - x0) / dx
            else:
                ya, yb = y0, y1
            for m in range(math.floor(min(ya, yb) - r), math.floor(max(ya, yb) + r) + 1):
                if (c, m) in self.walls:
                    return False
        return True

    # --- 点をつなぐ・最短距離 -----------------------------------------------
    def attach(self, x, y, among=None):
        """点 (x, y) から見通せる角の一覧 [(番号, 距離)]。among で調べる角を絞れる。"""
        found = []
        for i in among if among is not None else range(len(self.corners)):
            cx, cy, sx, sy = self.corners[i]
            if tangent(x - cx, y - cy, sx, sy) and self.segment_free(x, y, cx, cy):
                found.append((i, octile(x, y, cx, cy)))
        return found

    def field(self, links):
        """links（点から角へのつながり）を起点にしたダイクストラ法。戻り値は (各角までの距離, ひとつ前の角)。"""
        dist = [math.inf] * len(self.corners)
        prev = [-1] * len(self.corners)
        queue = []
        for i, d in links:
            if d < dist[i]:
                dist[i] = d
                heapq.heappush(queue, (d, i))
        while queue:
            d, i = heapq.heappop(queue)
            if d > dist[i]:
                continue
            for j, w in self.edges[i]:
                if d + w < dist[j]:
                    dist[j] = d + w
                    prev[j] = i
                    heapq.heappush(queue, (d + w, j))
        return dist, prev


def tangent(dx, dy, sx, sy):
    """角（壁から離れる向き sx, sy）から (dx, dy) へ向かうつながりが、角に沿って曲がる道になりうるか。
    壁に突っ込む向き（両方とも壁の側）と、角を素通りする向き（両方とも壁と反対の側）は使わない。"""
    return (dx * sx) * (dy * sy) <= 0


class Point:
    """地図につないだ点（スタート・アイテム・出口・アイテムに触れる点など）。"""

    def __init__(self, graph, x, y, among=None):
        self.x, self.y = x, y
        self.links = graph.attach(x, y, among)
        self.dist, self.prev = graph.field(self.links)

    def distance_to(self, graph, other):
        """この点から other までの最短距離と、通る角の番号の並び（この点の側から）。"""
        best, via = math.inf, None
        if graph.segment_free(self.x, self.y, other.x, other.y):
            best, via = octile(self.x, self.y, other.x, other.y), -1
        for i, d in other.links:
            if self.dist[i] + d < best:
                best, via = self.dist[i] + d, i
        if via is None:
            return math.inf, None
        chain = []
        while via != -1:
            chain.append(via)
            via = self.prev[via]
        return best, chain[::-1]
