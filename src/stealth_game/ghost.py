"""タイムアタックのボット（ゴースト）：8個のアイテムを集めて出口へ行く、一番速い順番と道を求めて動かす。

ゲームの中では、リプレイと同じ配置をこのボットに解かせ、その動きを半透明の箱（ゴースト）として重ねる。
攻略ボットのコマンド（tools/bot/time_attack.py）も、ここを使う。

計算の流れと、計算量を減らす工夫：
1. 距離と道：壁の角だけを中継点にした地図（route_graph.py の可視グラフ）で、壁ぎりぎりの最短の道を引く。
   地図はマップが同じなら全部の配置で同じなので、1回だけ作って使い回す。
2. 順番：8個の並べ方 8! = 40320 通りを全部比べず、動的計画法（Held-Karp、2^8 × 8 × 8 ≈ 1.6万回）で最短を出す。
   その表は「ここから先の最短」が正確に分かるので、最短の少し上までの順番だけを、無駄な枝をたどらずに挙げる。
3. 触れる点：アイテムは中心から0.7、出口は0.9まで近づけば十分。円の上で「前の点からの距離＋次の点までの距離」が
   一番短くなる点を、1つずつ順に選び直して決める（数回くり返す）。
4. 動かす：8方向のうち、目指す点までの距離が一番縮む向き（同じなら線から外れない向き）を1コマごとに選び、
   先の点が見通せたら手前の角を飛ばす。候補の順番を動かして一番速いものを残す（最速を超えたら打ち切る）。
5. 下限：どの順番でどう動かしても越えられない厳密な下限は exact_route.strict_lower_bound にある。
"""

import copy
import math
import time

from .constants import ITEM_PICKUP_DISTANCE, PLAYER_RADIUS, PLAYER_RUN_SPEED, SIM_DT
from .grid import cell_center
from .layout import EXIT_CELL, PLAYER_START
from .player import Player
from .route_graph import Graph, Point, octile, tangent

DT = SIM_DT  # 1コマの秒数（攻略ボットの記録と同じ）

EXIT_DISTANCE = 0.9  # 出口はこの距離まで近づけばよい（StealthGame.check_exit_reached）
TOUCH_MARGIN = 0.06  # 触れる点は、拾える距離よりこれだけ内側に置く
TOUCH_ANGLES = 24  # 触れる点の候補（円の上の向きの数）
TOUCH_ROUNDS = 3  # 触れる点を選び直すくり返しの数
DIRECTIONS = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
MAX_FRAMES = 3600  # 1回の動かしの上限（120秒）

_graphs = {}


def graph_for(world, radius=None):
    """地図は1つのマップ（と体の大きさ）につき1回だけ作る。radius を省くと、道を引くときの大きさ。"""
    key = (id(world), radius)
    if key not in _graphs:
        _graphs[key] = (world, Graph(world) if radius is None else Graph(world, radius))
    return _graphs[key][1]


def leg_distances(graph, start_xy, item_xys, exit_xy):
    """スタート→アイテム・アイテムどうし・アイテム→出口の最短距離。"""
    start = Point(graph, *start_xy)
    centers = [Point(graph, *xy) for xy in item_xys]
    exit_point = Point(graph, *exit_xy)
    start_to_item = [start.distance_to(graph, c)[0] for c in centers]
    item_to_item = [[a.distance_to(graph, b)[0] for b in centers] for a in centers]
    item_to_exit = [c.distance_to(graph, exit_point)[0] for c in centers]
    return (start, centers, exit_point), (start_to_item, item_to_item, item_to_exit)


# --- 順番 ----------------------------------------------------------------
def solve_order(start_to_item, item_to_item, item_to_exit):
    """Held-Karp：cost[mask][i] = アイテム i にいて、mask のアイテムをまだ拾っていないとき、
    残りを全部拾って出口に着くまでの最短距離。戻り値は (cost の表, スタートからの最短距離)。"""
    n = len(item_to_exit)
    full = (1 << n) - 1
    cost = [[math.inf] * n for _ in range(1 << n)]
    for i in range(n):
        cost[0][i] = item_to_exit[i]
    for mask in range(1, full + 1):  # mask が小さい（残りが少ない）順に埋まる：部分集合は必ず mask より小さい
        for i in range(n):
            if mask >> i & 1:
                continue  # i は今いる場所なので、残りに入っていない
            best = math.inf
            rest = mask
            while rest:
                j = (rest & -rest).bit_length() - 1
                rest &= rest - 1
                c = item_to_item[i][j] + cost[mask & ~(1 << j)][j]
                if c < best:
                    best = c
            cost[mask][i] = best
    total = min(start_to_item[j] + cost[full & ~(1 << j)][j] for j in range(n))
    return cost, total


def near_best_orders(cost, start_to_item, item_to_item, limit, count):
    """距離が limit 以下の順番を、短い順に最大 count 本。cost の表が「ここから先の最短」を正確に教えるので、
    limit を超える枝には入らない（たどるのは条件を満たす順番の道だけ）。"""
    n = len(start_to_item)
    full = (1 << n) - 1
    found = []

    def walk(order, last, mask, so_far):
        if not mask:
            found.append((so_far, order))  # so_far は出口までの距離を含む
            return
        for j in range(n):
            if not mask >> j & 1:
                continue
            step = item_to_item[last][j] if last is not None else start_to_item[j]
            rest = mask & ~(1 << j)
            if so_far + step + cost[rest][j] <= limit + 1e-9:
                walk(order + [j], j, rest, so_far + step + (cost[0][j] if not rest else 0.0))

    walk([], None, full, 0.0)
    found.sort()
    return found[:count]


# --- 触れる点と道 ------------------------------------------------------------
def touch_candidates(graph, center, radius):
    cx, cy = center.x, center.y
    found = [center]
    for a in range(TOUCH_ANGLES):
        t = 2 * math.pi * a / TOUCH_ANGLES
        x, y = cx + radius * math.cos(t), cy + radius * math.sin(t)
        if graph.point_free(x, y) and graph.segment_free(cx, cy, x, y):
            found.append(Point(graph, x, y))
    return found


def plan_route(graph, start, centers, exit_point, order, candidates_cache, touches=None):
    """順番 order の道。戻り値 ([(x, y, 区間の番号, 種類, 点)], 区間ごとの目標)。区間 i は i 番目の目標へ向かう道
    （最後の区間は出口）。種類は "corner"（壁の角）・"touch"（触れる点）・"center"（目標の中心）。
    touches を渡すと、触れる点を選ばずに、その点 [(x, y)]（目標ごと）を使う。"""
    targets = [centers[i] for i in order] + [exit_point]
    radii = [ITEM_PICKUP_DISTANCE - TOUCH_MARGIN] * len(order) + [EXIT_DISTANCE - TOUCH_MARGIN]
    keys = list(order) + ["exit"]
    touch = [start] + list(targets)
    if touches is not None:
        touch = [start] + [Point(graph, x, y) for x, y in touches]
    for _ in range(TOUCH_ROUNDS if touches is None else 0):
        changed = False
        for i in range(1, len(touch)):
            key = keys[i - 1]
            if key not in candidates_cache:
                candidates_cache[key] = touch_candidates(graph, targets[i - 1], radii[i - 1])

            def cost(q, i=i):
                c = touch[i - 1].distance_to(graph, q)[0]
                if i + 1 < len(touch):
                    c += q.distance_to(graph, touch[i + 1])[0]
                return c

            best = min(candidates_cache[key], key=cost)
            if best is not touch[i]:
                touch[i], changed = best, True
        if not changed:
            break
    route = []
    for i in range(1, len(touch)):
        _, chain = touch[i - 1].distance_to(graph, touch[i])
        for c in chain or []:
            x, y, _, _ = graph.corners[c]
            route.append((x, y, i - 1, "corner", None))
        route.append((touch[i].x, touch[i].y, i - 1, "touch", touch[i]))
        target = targets[i - 1]
        if touch[i] is not target:
            route.append((target.x, target.y, i - 1, "center", target))  # 念のため：触れる点で拾えなかったら中心まで行く
    return route, keys


# --- 動かす -------------------------------------------------------------------
def keys_of(dx, dy):
    keys = set()
    if dx > 0:
        keys.add("right")
    elif dx < 0:
        keys.add("left")
    if dy > 0:
        keys.add("up")
    elif dy < 0:
        keys.add("down")
    return frozenset(keys)


def moved(world, x, y, dx, dy):
    """本物と同じ動き方（壁に当たったら、当たらない向きの成分だけ進む）で1コマ動かした位置。"""
    p = Player()
    p.x, p.y = x, y
    p.move(DT, dx, dy, world)
    return p.x, p.y


def reroute(graph, route, k, px, py):
    """route の k 番目から先を、今の位置 (px, py) から、その区間の触れる点（なければ中心）まで引き直す。"""
    leg = route[k][2]
    end = next(i for i in range(k, len(route)) if route[i][2] == leg and route[i][4] is not None)
    here = Point(graph, px, py)
    _, chain = here.distance_to(graph, route[end][4])
    corners = [(graph.corners[c][0], graph.corners[c][1], leg, "corner", None) for c in chain or []]
    return route[:k] + corners + route[end:]


def choose_direction(world, px, py, aim, anchor):
    """8方向のうち、目指す点 aim までの距離が一番縮む向き（同じなら anchor→aim の線から外れない向き）。
    戻り値は (向き, 縮む距離)。"""
    ax, ay = aim[0], aim[1]
    lx, ly = ax - anchor[0], ay - anchor[1]
    length = math.hypot(lx, ly) or 1.0
    best, best_score = (0, 0), None
    for dx, dy in DIRECTIONS:
        x, y = moved(world, px, py, dx, dy)
        off = abs(lx * (y - anchor[1]) - ly * (x - anchor[0])) / length
        score = (round(octile(x, y, ax, ay), 6), off)
        if best_score is None or score < best_score:
            best, best_score = (dx, dy), score
    return best, octile(px, py, ax, ay) - best_score[0]


class Run:
    """タイムアタックの1回分の進み方（StealthGame.update_play のうち、鬼のいないタイムアタックで働く部分だけ）：
    動く → アイテムを拾う → 全部拾って出口に近づいたらクリア。tests/test_ghost.py で本物と一致を確かめている。"""

    def __init__(self, world, item_cells):
        self.world = world
        self.items = [cell_center(c) for c in item_cells]
        self.items_collected = set()
        self.player = Player()
        self.player.reset(PLAYER_START)
        self.elapsed = 0.0
        self.state = "play"

    def step(self, keys):
        self.elapsed += DT
        dx = int("right" in keys) - int("left" in keys)
        dy = int("up" in keys) - int("down" in keys)
        self.player.sneaking = "sneak" in keys
        self.player.move(DT, dx, dy, self.world)
        p = self.player
        for i, (ix, iy) in enumerate(self.items):
            if i not in self.items_collected and math.hypot(p.x - ix, p.y - iy) < ITEM_PICKUP_DISTANCE:
                self.items_collected.add(i)
        ex, ey = cell_center(EXIT_CELL)
        if len(self.items_collected) == len(self.items) and math.hypot(p.x - ex, p.y - ey) < EXIT_DISTANCE:
            self.state = "win"

    @property
    def done(self):
        return self.state == "win"

    def clone(self):
        """今の状態のコピー（マップとアイテムの位置は変わらないので共有する）。"""
        other = Run.__new__(Run)
        other.world, other.items = self.world, self.items
        other.items_collected = set(self.items_collected)
        other.player = copy.copy(self.player)
        other.elapsed, other.state = self.elapsed, self.state
        return other


def drive(graph, item_cells, route, keys, give_up=math.inf):
    """道どおりに動かす。戻り値 (クリアの秒数 または None, 入力の記録, 各コマの後の (x, y, 向き))。
    give_up 秒を超えたら打ち切る。"""
    sim = Run(graph.world, item_cells)
    log = []
    poses = []
    k = 0
    anchor = (sim.player.x, sim.player.y)
    step = PLAYER_RUN_SPEED * DT
    stalled = 0
    while not sim.done and len(log) < MAX_FRAMES:
        px, py = sim.player.x, sim.player.y
        # 拾い終えた目標へ向かう区間は飛ばす
        while k < len(route) - 1 and keys[route[k][2]] != "exit" and keys[route[k][2]] in sim.items_collected:
            k += 1
            anchor = (px, py)
        # 着いた点と、次の点が見通せるときの手前の角は飛ばす（触れる点は飛ばさない）
        while k < len(route) - 1:
            x, y, leg, kind, _ = route[k]
            nx, ny, nleg, _, _ = route[k + 1]
            reached = octile(px, py, x, y) <= step * 0.5
            skippable = kind == "corner" and nleg == leg and graph.segment_free(px, py, nx, ny)
            if not (reached or skippable):
                break
            k += 1
            anchor = (px, py)
        if stalled >= 2 or not graph.segment_free(px, py, route[k][0], route[k][1], PLAYER_RADIUS):
            # 道から外れて目指す点が見えなくなった（または進めなくなった）：今いる場所から、区間の終わりまで引き直す
            route = reroute(graph, route, k, px, py)
            anchor, stalled = (px, py), 0
        best, gain = choose_direction(graph.world, px, py, route[k], anchor)
        while gain <= 1e-6 and k < len(route) - 1 and route[k][3] == "corner":
            k += 1  # どの向きでも角の点に近づけない（壁に触れていて、近づく向きがふさがれている）：着いたとみなす
            anchor = (px, py)
            best, gain = choose_direction(graph.world, px, py, route[k], anchor)
        pressed = keys_of(*best)
        sim.step(pressed)
        stalled = stalled + 1 if math.hypot(sim.player.x - px, sim.player.y - py) < step * 0.3 else 0
        log.append(pressed)
        poses.append((sim.player.x, sim.player.y, sim.player.heading))
        if sim.elapsed > give_up:
            return None, log, poses
    return (sim.elapsed if sim.state == "win" else None), log, poses


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


def direction_of(keys):
    """押しているキーの組 → 向き (dx, dy)。"""
    return (int("right" in keys) - int("left" in keys), int("up" in keys) - int("down" in keys))


def _mixable(a, b):
    """向き a と b が、斜めとまっすぐの45°となりどうしか（混ぜても、まとめても同じ長さになる組）。"""
    return a != b and (0, 0) not in (a, b) and max(abs(a[0] - b[0]), abs(a[1] - b[1])) == 1 and (
        (a[0] and a[1]) != (b[0] and b[1]))


def smooth_log(world, item_cells, log):
    """入力の記録の「斜めとまっすぐが細かく入れ替わる区間」を、「斜めをまとめて → まっすぐをまとめて」
    （または逆）に並べ替える。どちらでも着く場所とかかるコマ数は同じなので、タイムを変えずに動きを滑らかにできる。

    区間ごとに、並べ替える前と後で、区間の終わりの位置（ほぼ一致）と拾ったアイテムと状態が同じになるときだけ採る
    （壁に当たると位置が変わるので採らない）。最後に記録を最初から流し直し、同じかそれより少ないコマ数で
    クリアできなければ、元の記録を返す。"""
    def advance(run, keys_list):
        for keys in keys_list:
            if run.done:
                break
            run.step(keys)
        return run

    def regroup(run, window, a, b):
        """window（向き a と b だけの区間）を並べ替えて run を進め、使った入力を返す。区間まるごとで並べ替えられなければ
        （途中で壁に当たる）、半分に分けてそれぞれ試す。"""
        if b is None or len(window) < 3:
            advance(run, window)
            return list(window)
        first = [k for k in window if direction_of(k) == a]
        second = [k for k in window if direction_of(k) == b]
        original = advance(run.clone(), window)
        for trial in (first + second, second + first):
            end = advance(run.clone(), trial)
            if (abs(end.player.x - original.player.x) < 1e-9 and abs(end.player.y - original.player.y) < 1e-9
                    and end.items_collected == original.items_collected and end.state == original.state):
                advance(run, trial)
                return trial
        half = len(window) // 2
        left = regroup(run, window[:half], a, b)
        return left + regroup(run, window[half:], a, b)

    run = Run(world, item_cells)
    out = []
    i = 0
    n = len(log)
    while i < n:
        a = direction_of(log[i])
        b = None
        j = i + 1
        while j < n:
            d = direction_of(log[j])
            if d != a and d != b:
                if b is None and _mixable(a, d):
                    b = d
                else:
                    break
            j += 1
        out += regroup(run, log[i:j], a, b)
        i = j
    check = advance(Run(world, item_cells), out)
    if check.state != "win":
        return list(log)
    return out


def poses_of(world, item_cells, log):
    """記録を流したときの、各コマの後の (x, y, 向き)。"""
    run = Run(world, item_cells)
    poses = []
    for keys in log:
        run.step(keys)
        poses.append((run.player.x, run.player.y, run.player.heading))
    return poses


def best_run(world, item_cells, candidates=10, margin=0.08, orders=None):
    """配置 item_cells を解く。戻り値は辞書：time（クリアの秒数。解けなければ None）・order・log・poses・
    distance（地図の上の最短距離）・plan_seconds（道と順番の計算の秒数）・candidates。
    orders（順番の並び）を渡すと、中心どうしの距離で選ぶ代わりに、その順番を動かして比べる。"""
    started = time.perf_counter()
    graph = graph_for(world)
    xys = (cell_center(PLAYER_START), [cell_center(c) for c in item_cells], cell_center(EXIT_CELL))
    (start, centers, exit_point), legs = leg_distances(graph, *xys)
    cost, shortest = solve_order(*legs)
    if orders is None:
        orders = near_best_orders(cost, legs[0], legs[1], shortest * (1 + margin), candidates)
    else:
        orders = [(None, list(o)) for o in orders]
    plan_seconds = time.perf_counter() - started
    best = {"time": None, "order": None, "log": None, "poses": None}
    cache = {}
    for _, order in orders:
        route, keys = plan_route(graph, start, centers, exit_point, order, cache)
        t, log, poses = drive(graph, item_cells, route, keys, give_up=best["time"] or math.inf)
        if t is not None and (best["time"] is None or t < best["time"]):
            best = {"time": t, "order": order, "log": log, "poses": poses}
    if best["log"] is not None:
        best["log"] = smooth_log(world, item_cells, best["log"])  # タイムを変えずに、細かい切り替えをまとめる
        best["poses"] = poses_of(world, item_cells, best["log"])
    best.update(distance=shortest, plan_seconds=plan_seconds, candidates=len(orders))
    return best


