"""タイムアタックの攻略ボット専用の動かし方と、順番の候補（ゲーム内のゴーストは使わない）。

- drive_through：決めた順番・触れる点で、ゴーストと同じ動かし方（ghost.drive）をする
- drive_touches：1コマごとに「残りの長さが一番短くなる向き」を選ぶ動かし方
- center_orders：アイテムの中心どうしの距離で、最短に近い順番を挙げる
"""

import math

from stealth_game.constants import ITEM_PICKUP_DISTANCE
from stealth_game.ghost import (
    DIRECTIONS,
    EXIT_DISTANCE,
    MAX_FRAMES,
    TOUCH_MARGIN,
    Run,
    drive,
    graph_for,
    keys_of,
    leg_distances,
    moved,
    plan_route,
)
from stealth_game.grid import cell_center
from stealth_game.layout import EXIT_CELL, PLAYER_START
from stealth_game.route_graph import Point, octile, tangent
from stealth_game.route_order import near_best_orders, solve_order


def drive_through(world, item_cells, order, touches):
    """順番 order・触れる点 touches（目標ごとの (x, y)。円の周の上の点）で動かす。触れる点は、拾える距離より
    少し内側（TOUCH_MARGIN）へ寄せて目指す。戻り値 (クリアの秒数 または None, 入力の記録, 各コマの後の位置)。
    触れる点が、道を引くときの大きさでは通れない場所なら (None, None, None)。"""
    graph = graph_for(world)
    centers_xy = [cell_center(item_cells[i]) for i in order] + [cell_center(EXIT_CELL)]
    radii = [ITEM_PICKUP_DISTANCE - TOUCH_MARGIN] * len(order) + [EXIT_DISTANCE - TOUCH_MARGIN]
    inner = []
    for (cx, cy), (x, y), r in zip(centers_xy, touches, radii):
        d = math.hypot(x - cx, y - cy) or 1.0
        px, py = cx + (x - cx) * r / d, cy + (y - cy) * r / d
        if not graph.point_free(px, py):
            return None, None, None
        inner.append((px, py))
    start = Point(graph, *cell_center(PLAYER_START))
    centers = [Point(graph, *cell_center(c)) for c in item_cells]
    exit_point = Point(graph, *cell_center(EXIT_CELL))
    route, keys = plan_route(graph, start, centers, exit_point, order, {}, touches=inner)
    return drive(graph, item_cells, route, keys)


def center_orders(world, item_cells, margin, count):
    """アイテムの中心どうしの距離で、最短の (1 + margin) 倍以内の順番を、短い順に最大 count 本。
    戻り値 ([(距離, 順番)], 最短の距離)。"""
    graph = graph_for(world)
    xys = (cell_center(PLAYER_START), [cell_center(c) for c in item_cells], cell_center(EXIT_CELL))
    _, legs = leg_distances(graph, *xys)
    cost, shortest = solve_order(*legs)
    return near_best_orders(cost, legs[0], legs[1], shortest * (1 + margin), count), shortest


def drive_touches(world, item_cells, order, touches, give_up=math.inf):
    """決めた順番 order・触れる点 touches（exact_route.solve_exact の "touches"）で動かす。

    1コマごとに、8方向それぞれについて「動いた先から最後までの残りの長さ」を求め、一番短くなる向きを選ぶ。
    残りの長さ ＝ 動いた先から次の触れる点までの、地図（体の本当の大きさ0.3）の上の最短距離
               ＋ そこから先の触れる点どうしの最短距離の合計。
    動いた先でアイテムを拾えるなら、その先の触れる点で測る。出口の円に入れる向きがあれば、それを選ぶ。
    目指す点の手前で切り替えるやり方（drive）と違い、曲がり角や触れる点の手前で1コマを無駄にしない。
    見える角は、動いた先ごとに全部の角を調べる（今の位置から見える角だけにすると、少し動けば見えてくる角を見落とし、
    角の手前で止まってしまうため）。ただし、残りの長さが今の最短を超える角は、見通しを調べる前に捨てる。
    戻り値 (クリアの秒数 または None, 入力の記録, 各コマの後の位置)。"""
    g = graph_for(world)  # 道を引くときの大きさ（体を少し大きく見る）の地図：壁にぴったり沿わず、つかえにくい
    sim = Run(world, item_cells)
    keys = list(order) + ["exit"]
    targets = [cell_center(item_cells[i]) for i in order] + [cell_center(EXIT_CELL)]
    inner = [ITEM_PICKUP_DISTANCE - TOUCH_MARGIN] * len(order) + [EXIT_DISTANCE - TOUCH_MARGIN]
    marks = []
    for (cx, cy), (x, y), r in zip(targets, touches, inner):
        d = math.hypot(x - cx, y - cy) or 1.0
        mx, my = cx + (x - cx) * r / d, cy + (y - cy) * r / d  # 触れる点を、拾える距離より少し内側へ
        if not g.point_free(mx, my):
            return None, [], []
        marks.append(Point(g, mx, my))
    rest = [0.0] * len(marks)  # その触れる点から最後まで
    for i in range(len(marks) - 2, -1, -1):
        rest[i] = rest[i + 1] + marks[i].distance_to(g, marks[i + 1])[0]
    radii = [ITEM_PICKUP_DISTANCE] * len(order) + [EXIT_DISTANCE]

    def remaining(x, y, leg):
        mark = marks[leg]
        best = math.inf
        if g.segment_free(x, y, mark.x, mark.y):
            best = octile(x, y, mark.x, mark.y)
        for v, cx, cy, sx, sy in corner_list:
            d = octile(x, y, cx, cy) + mark.dist[v]
            if d < best and tangent(x - cx, y - cy, sx, sy) and g.segment_free(x, y, cx, cy):
                best = d
        return best + rest[leg]

    corner_list = [(v,) + tuple(c) for v, c in enumerate(g.corners)]

    def step_options(px, py, leg):
        """8方向それぞれの (向き, 残りの長さ, 動いた先, 動いた先の区間)。出口に入れる向きの残りは -1。"""
        out = []
        for dx, dy in DIRECTIONS:
            x, y = moved(world, px, py, dx, dy)
            here = leg
            tx, ty = targets[leg]
            if math.hypot(x - tx, y - ty) < radii[leg]:
                if keys[leg] == "exit":
                    out.append(((dx, dy), -1.0, (x, y), leg))
                    continue
                here = leg + 1  # このコマで拾える：その先の触れる点で測る
            out.append(((dx, dy), remaining(x, y, here), (x, y), here))
        return out

    def lookahead(px, py, leg, depth):
        """depth 手先までの組み合わせのうち、最後の残りが一番短いものの (1手目, 残り)。"""
        best = (None, math.inf)
        for move, cost, (x, y), here in step_options(px, py, leg):
            if depth > 1 and cost >= 0:
                cost = lookahead(x, y, here, depth - 1)[1]
            if cost < best[1]:
                best = (move, cost)
        return best

    log, poses = [], []
    stuck, last = 0, math.inf
    while not sim.done and len(log) < MAX_FRAMES:
        px, py = sim.player.x, sim.player.y
        leg = next(i for i, key in enumerate(keys) if key == "exit" or key not in sim.items_collected)
        options = step_options(px, py, leg)
        best, best_cost = min(options, key=lambda o: o[1])[0], min(o[1] for o in options)
        if best_cost >= last - 1e-9:
            # どの向きでも残りが縮まない（壁の角の手前で、1コマ動くと壁に当たる位置など）：
            # 2手先・3手先までの組み合わせを試し、一番縮む組み合わせの1手目を選ぶ
            for depth in (2, 3):
                best, best_cost = lookahead(px, py, leg, depth)
                if best_cost < last - 1e-9:
                    break
        if best_cost == math.inf:
            best = None
        if best is None:
            return None, log, poses  # どの向きでも、次の触れる点への道が見つからない
        # 残りの長さが10コマ続けて縮まなければ、進めなくなったとみなしてあきらめる（呼ぶ側は drive の結果を使う）
        stuck = stuck + 1 if best_cost >= last - 1e-9 else 0
        last = min(last, best_cost)
        if stuck >= 10:
            return None, log, poses
        pressed = keys_of(*best)
        sim.step(pressed)
        log.append(pressed)
        poses.append((sim.player.x, sim.player.y, sim.player.heading))
        if sim.elapsed > give_up:
            return None, log, poses
    return (sim.elapsed if sim.state == "win" else None), log, poses
