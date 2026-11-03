"""A*（4方向・マンハッタン距離・heapq）。ライブラリに置き換えず自作を維持する。"""

import heapq

from .grid import manhattan


class Node:
    __slots__ = ("pos", "g", "f", "parent")

    def __init__(self, pos, g, f, parent=None):
        self.pos = pos
        self.g = g
        self.f = f
        self.parent = parent

    def __lt__(self, other):
        return self.f < other.f


def build_path(node):
    path = []
    while node is not None:
        path.append(node.pos)
        node = node.parent
    path.reverse()
    return path


def expand(world, node, goal, best_g, open_heap, extra_cost):
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = node.pos[0] + dx, node.pos[1] + dy
        if world.is_forbidden_for_guard(nx, ny):
            continue
        new_g = node.g + world.costs[ny][nx]
        if extra_cost is not None:
            new_g += extra_cost((nx, ny))
        if new_g >= best_g.get((nx, ny), new_g + 1):
            continue
        best_g[(nx, ny)] = new_g
        new_f = new_g + manhattan((nx, ny), goal)
        heapq.heappush(open_heap, Node((nx, ny), new_g, new_f, node))


def astar(world, start, goal, extra_cost=None):
    """start→goal のセル列（startを含む）を返す。行けなければ空リスト。
    extra_cost(セル)を渡すと、そのマスのコストに足す（0以上の整数。挟み撃ちの回り道用）。"""
    if world.is_forbidden_for_guard(*goal):
        return []
    open_heap = [Node(start, 0, manhattan(start, goal))]
    best_g = {start: 0}
    while open_heap:
        node = heapq.heappop(open_heap)
        if node.pos == goal:
            return build_path(node)
        if node.g > best_g[node.pos]:
            continue
        expand(world, node, goal, best_g, open_heap, extra_cost)
    return []
