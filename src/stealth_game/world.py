"""ワールド（マップ・当たり判定・視線）。"""

import math
from collections import deque

from .grid import world_to_cell
from .layout import MAP_H, MAP_W, START_POCKET_DOORS
from .mapgen import build_walls, open_neighbors, pocket_cells


class World:
    """壁の配置と、A*用の移動コスト（すべて1以上の整数）を持つ。"""

    def __init__(self):
        self.walls = build_walls()
        self.pocket = pocket_cells()  # マップの外に出っ張ったスタート地点の床
        self.doors_closed = False  # Trueの間、安全地帯の扉は壁として扱う
        self.timed_closed = frozenset()  # 時間で開け閉めする扉のうち、今閉まっているセル（壁として扱う）
        self.costs = self.build_costs()
        self.floor_cells = [
            (x, y) for y in range(MAP_H) for x in range(MAP_W) if not self.walls[y][x]
        ]
        self.safe_room, self.safe_doors = self.find_safe_zone()
        self.safe_cells = self.safe_room | self.safe_doors
        # 鬼が歩ける床（安全地帯には入れない）
        self.guard_cells = [c for c in self.floor_cells if c not in self.safe_cells]

    def find_safe_zone(self):
        """安全地帯 = 出っ張った小部屋の床と、そこから出る扉のセル。"""
        return set(self.pocket), set(START_POCKET_DOORS)

    def is_wall(self, cx, cy):
        if (cx, cy) in self.pocket:
            return False
        if not (0 <= cx < MAP_W and 0 <= cy < MAP_H):
            return True
        if self.doors_closed and (cx, cy) in self.safe_doors:
            return True
        if self.timed_closed and (cx, cy) in self.timed_closed:
            return True
        return self.walls[cy][cx] == 1

    def is_forbidden_for_guard(self, cx, cy):
        return self.is_wall(cx, cy) or (cx, cy) in self.safe_cells

    def is_in_safe_zone(self, x, y):
        return world_to_cell(x, y) in self.safe_cells

    def is_fully_outside_safe_zone(self, x, y, radius):
        """体（半径radiusの四角形）が安全地帯にまったく掛かっていないか。"""
        corners = ((-radius, -radius), (radius, -radius), (-radius, radius), (radius, radius))
        return all(world_to_cell(x + dx, y + dy) not in self.safe_cells for dx, dy in corners)

    def nearest_cells(self, start, count, exclude):
        """startから近い順に、鬼の歩ける床をcount個返す（excludeは除く）。"""
        found = []
        seen = {start}
        queue = deque([start])
        while queue and len(found) < count:
            cell = queue.popleft()
            if cell not in self.safe_cells and cell not in exclude and not self.is_wall(*cell):
                found.append(cell)
            for n in open_neighbors(self.walls, *cell):
                if n not in seen:
                    seen.add(n)
                    queue.append(n)
        return found

    def is_wall_at(self, x, y):
        cx, cy = world_to_cell(x, y)
        return self.is_wall(cx, cy)

    def is_blocked(self, x, y, radius):
        """半径radiusの円（を囲む四角形）が壁に触れるか。"""
        corners = ((-radius, -radius), (radius, -radius), (-radius, radius), (radius, radius))
        return any(self.is_wall_at(x + dx, y + dy) for dx, dy in corners)

    def first_wall_distance(self, x, y, dx, dy, max_dist):
        """(x,y)から向き(dx,dy)（単位ベクトル）へ進み、最初に壁へ入るまでの距離を返す。

        通るマスを1つずつ正確にたどるので、壁の角のすき間を見落とさない。
        壁にぶつからなければmax_distを返す。
        """
        cx, cy = world_to_cell(x, y)
        step_x = 1 if dx > 0 else -1
        step_y = 1 if dy > 0 else -1
        inf = float("inf")
        t_delta_x = abs(1.0 / dx) if dx else inf
        t_delta_y = abs(1.0 / dy) if dy else inf
        t_max_x = ((cx + (1 if dx > 0 else 0)) - x) / dx if dx else inf
        t_max_y = ((cy + (1 if dy > 0 else 0)) - y) / dy if dy else inf
        while True:
            t = min(t_max_x, t_max_y)
            if t > max_dist:
                return max_dist
            if abs(t_max_x - t_max_y) < 1e-9:  # ちょうど角を通る
                if self.is_wall(cx + step_x, cy) and self.is_wall(cx, cy + step_y):
                    return t  # 斜めに並んだ壁のすき間は通さない
                cx, cy = cx + step_x, cy + step_y
                t_max_x += t_delta_x
                t_max_y += t_delta_y
            elif t_max_x < t_max_y:
                cx += step_x
                t_max_x += t_delta_x
            else:
                cy += step_y
                t_max_y += t_delta_y
            if self.is_wall(cx, cy):
                return t

    def has_line_of_sight(self, x1, y1, x2, y2):
        dist = math.hypot(x2 - x1, y2 - y1)
        if dist < 1e-9:
            return True
        hit = self.first_wall_distance(x1, y1, (x2 - x1) / dist, (y2 - y1) / dist, dist)
        return hit >= dist

    def cast_ray(self, x, y, angle, max_dist):
        """壁にぶつかるまでの距離を返す（視界の扇形の描画用）。"""
        return self.first_wall_distance(x, y, math.cos(angle), math.sin(angle), max_dist)

    def visible_outline(self, x, y, radius, rays):
        """(x,y)から放射状にrays本の線を伸ばし、壁で止まった先の点を順に返す（足音の範囲の描画用）。

        この形の中にいれば、(x,y)との間に壁がない（視線が通る）。最初と最後は同じ向きの点。
        """
        points = []
        for i in range(rays + 1):
            angle = 2 * math.pi * i / rays
            dist = self.cast_ray(x, y, angle, radius)
            points.append((x + math.cos(angle) * dist, y + math.sin(angle) * dist))
        return points

    def is_next_to_wall(self, cx, cy):
        around = ((dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
        return any(self.is_wall(cx + dx, cy + dy) for dx, dy in around)

    def build_costs(self):
        """通路は1、壁際は3。警備員が壁から少し離れて歩くようになる。"""
        costs = [[1] * MAP_W for _ in range(MAP_H)]
        for y in range(MAP_H):
            for x in range(MAP_W):
                if self.is_next_to_wall(x, y):
                    costs[y][x] = 3
        return costs
