"""（攻略ボット専用）順番を決めたときの、本当の最短の道（触れる点の選び方まで含めて、保証の幅つき）。

問題：スタートから、決めた順番でアイテムの円（半径0.7より内側に入れば拾える）に1回ずつ入り、
最後に出口の円（半径0.9）に入る道のうち、8方向の移動での長さ（オクタイル距離）が一番短いもの。

求め方：
1. 体の本当の大きさ（0.3）・角の中継点をほぼ壁に付けた地図（route_graph.Graph）を作り、
   角どうしの最短距離を全部求めておく（角は232個。マップが同じなら1回だけ）。
2. 道は、円の外から円に入るので、触れる点は円の周の上にある（円の中の点で触れる道は、周を横切ったところで
   もう拾えているので、そこで次へ向かう道より短くならない）。そこで円の周の上に候補の点を並べる。
   円が壁（太らせた壁）にかかるところは周が切れるので、切れ目の点も必ず候補に入れる。
3. 「スタート → 1個目の候補 → 2個目の候補 → … → 出口の候補」の一番短いつながりを、前から順に表を埋めて求める
   （動的計画法）。候補の組み合わせを全部比べたのと同じ結果になる。区間の距離は
   「点 → 見える角 → （角どうしの最短）→ 見える角 → 点」か、まっすぐ見通せればその長さで、
   これを「点→角」「角→角」「角→点」に分けて計算するので、候補の数の2乗の計算はほとんど要らない。
4. 保証の幅：本当の最短の道が円に触れる点のそばには、候補の点が必ずある（同じ周の切れていない弧の上、
   間隔の半分以内）。候補の点からその弧に沿って本当の触れる点まで回り込み、本当の最短の道に乗り換えれば、
   長さは回り込みの往復の分しか増えない。なので「求めた長さ − 本当の最短の長さ ≤ 保証の幅」になる
   （弧の長さ θ·r の、8方向の移動での長さは、直線距離の最大 1.0824 倍）。

下限（どう動かしても、これより少ないコマではクリアできない）について：
ゲームの当たり判定は、斜めの1コマを「横に動く → 縦に動く」として、それぞれの行き先だけを調べる。なので斜めの1コマの
まっすぐな線の途中は、壁の角を少しかすめることがある（体の大きさ0.3のままでは通れない線になる）。
ただし線の途中の点は、どれもその前後の位置から縦横それぞれ 0.055 以内（1コマの斜めの移動 0.108 の半分）にある。
前後の位置は体の大きさ0.3で通れるので、線の途中の点は「体の大きさ 0.3 − 0.055」なら必ず通れる。
そこで下限は、体の大きさを STRICT_RADIUS（0.245）と見た地図で測る（実際に動いた道は、この地図では必ず通れる道なので、
その長さ ≥ この地図での最短の長さ。1コマで進めるのは長さ 0.153 まで）。
"""

import math
import time

from stealth_game.constants import ITEM_PICKUP_DISTANCE, PLAYER_RADIUS, PLAYER_RUN_SPEED, SIM_DT
from stealth_game.grid import cell_center
from stealth_game.layout import EXIT_CELL, PLAYER_START
from stealth_game.route_graph import Graph, Point, octile
from stealth_game.route_order import solve_order

EXIT_DISTANCE = 0.9
OCTILE_PER_EUCLID = 1.0824  # 直線距離 1 の、8方向の移動での長さの最大（22.5°の向き）
EXACT_GAP = 1e-6  # 角の中継点を、太らせた壁からこれだけ離す（ほぼ0）
INSIDE = 1e-6  # 候補の点は、拾える距離よりこれだけ内側に置く（拾えるのは「より近い」とき）
STRICT_RADIUS = 0.245  # 下限を測るときの体の大きさ（0.3 − 斜めの1コマの半分 0.0542 より少し小さく）
SAMPLES = 360  # 円の周に並べる候補の数（切れ目の点は別に足す）。360で保証の幅 約0.11（1コマ 0.153 より小さい）・1配置 約3秒

_cache = {}


class ExactMap:
    """体の大きさ radius の地図と、角どうしの最短距離（とその道）。"""

    def __init__(self, world, radius=PLAYER_RADIUS):
        self.graph = Graph(world, radius, EXACT_GAP)
        n = len(self.graph.corners)
        self.dist = []
        self.prev = []
        for i in range(n):
            d, p = self.graph.field([(i, 0.0)])
            self.dist.append(d)
            self.prev.append(p)

    def chain(self, u, w):
        """角 u から角 w までの最短の道の角の並び（u と w を含む）。"""
        out = [w]
        while out[-1] != u:
            out.append(self.prev[u][out[-1]])
        return out[::-1]


def exact_map(world, radius=PLAYER_RADIUS):
    """地図は、マップと体の大きさの組ごとに1回だけ作る。"""
    key = (id(world), radius)
    if key not in _cache:
        _cache[key] = (world, ExactMap(world, radius))
    return _cache[key][1]


def circle_samples(graph, cx, cy, radius, count):
    """円の周の、通れる部分の上の候補の点 [(x, y)] と、隣どうしの最大の角度の間隔。
    周が太らせた壁で切れるところ（切れ目）は、必ず候補に入れる。"""
    r = graph.radius
    cuts = []
    for (wx, wy) in graph.walls:
        if abs(wx + 0.5 - cx) > radius + r + 1 or abs(wy + 0.5 - cy) > radius + r + 1:
            continue
        for line_x in (wx - r, wx + 1 + r):
            d = line_x - cx
            if abs(d) <= radius:
                a = math.acos(d / radius)
                cuts += [a, -a]
        for line_y in (wy - r, wy + 1 + r):
            d = line_y - cy
            if abs(d) <= radius:
                a = math.asin(d / radius)
                cuts += [a, math.pi - a]
    cuts = sorted({c % (2 * math.pi) for c in cuts})
    if not cuts:
        cuts = [0.0]
    step = 2 * math.pi / count
    angles = []
    widest = 0.0
    for k, a in enumerate(cuts):
        b = cuts[k + 1] if k + 1 < len(cuts) else cuts[0] + 2 * math.pi
        mid = (a + b) / 2
        if not graph.point_free(cx + radius * math.cos(mid), cy + radius * math.sin(mid)):
            continue  # この弧は壁の中
        # 切れ目のすぐ内側から、間隔 step 以下で並べる（両端の点も入れる）
        lo, hi = a + 1e-9, b - 1e-9
        pieces = max(1, math.ceil((hi - lo) / step))
        for j in range(pieces + 1):
            angles.append(lo + (hi - lo) * j / pieces)
        widest = max(widest, (hi - lo) / pieces)
    points = [(cx + radius * math.cos(t), cy + radius * math.sin(t)) for t in angles]
    points = [p for p in points if graph.point_free(*p)]
    return points, widest


def solve_exact(world, item_cells, order, samples=SAMPLES, radius=PLAYER_RADIUS):
    """順番 order（アイテムの番号の並び）での、体の大きさ radius の地図の上の本当の最短の道。戻り値は辞書：
    length（求めた長さ）・slack（保証の幅：本当の最短の長さは length − slack 以上）・
    touches（各目標の触れる点）・path（道の点の並び）・seconds・
    min_frames（length − slack を1コマの長さで割って切り上げた数。radius が STRICT_RADIUS のときだけ、
    「この順番でのクリアのコマ数の下限」と言える）。"""
    started = time.perf_counter()
    em = exact_map(world, radius)
    g = em.graph
    sx, sy = cell_center(PLAYER_START)
    targets = [cell_center(item_cells[i]) for i in order] + [cell_center(EXIT_CELL)]
    radii = [ITEM_PICKUP_DISTANCE - INSIDE] * len(order) + [EXIT_DISTANCE - INSIDE]

    layers = [[(sx, sy)]]
    widest = []
    for (cx, cy), rad in zip(targets, radii):
        pts, w = circle_samples(g, cx, cy, rad, samples)
        layers.append(pts)
        widest.append(w)
    vis = [[g.attach(x, y) for x, y in layer] for layer in layers]
    anchors = [((sx, sy), 0.0)] + [(c, rad) for c, rad in zip(targets, radii)]
    value, back = chain_dp(em, layers, vis, anchors, keep_back=True)

    end = min(range(len(value)), key=value.__getitem__)
    length = value[end]
    # 道をたどり直す
    path, touches, route = [], [], []
    q = end
    for k in range(len(layers) - 1, 0, -1):
        p, via = back[k - 1][q]
        touches.append(layers[k][q])
        path.append(layers[k][q])
        route.append(layers[k][q] + (k - 1, True, 0, 0))
        if via is not None:
            for c in reversed(em.chain(*via)):
                path.append(g.corners[c][:2])
                route.append(g.corners[c][:2] + (k - 1, False) + g.corners[c][2:])
        q = p
    path.append((sx, sy))
    path.reverse()
    touches.reverse()
    route.reverse()
    k = OCTILE_PER_EUCLID
    slack = sum(2 * k * rad * w / 2 for rad, w in zip(radii[:-1], widest[:-1])) + k * radii[-1] * widest[-1] / 2
    return {
        "order": list(order),
        "length": length,
        "slack": slack,
        "touches": touches,
        "path": path,
        # スタートの後の道の点 [(x, y, 区間の番号, 触れる点か, sx, sy)]（区間 i は i 番目の目標へ向かう。
        # sx, sy は角の点のとき、壁から離れる向き。触れる点では 0）
        "route": route,
        "min_frames": frames_for(length - slack),
        "seconds": time.perf_counter() - started,
    }


def chain_dp(em, layers, vis, anchors, keep_back=False, limit=math.inf):
    """「層0の点 → 層1の候補 → … → 最後の層の候補」の一番短いつながりを、前から順に表を埋めて求める。
    layers[k]：k 番目の層の候補の点。vis[k]：それぞれの点から見える角 [(角, 距離)]。
    anchors[k]：(層 k の円の中心, 半径)（打ち切りの見積もりに使う）。
    戻り値 (最後の層の各候補までの最短の長さ, 各区間の (前の候補, 通る角の組) の表。keep_back が偽なら None)。
    limit を渡すと、どこかの層で全部の候補が limit を超えたら、そこで打ち切る（最後の層の値はすべて inf）。"""
    g = em.graph
    value = [0.0] * len(layers[0])
    back = [] if keep_back else None
    for k in range(1, len(layers)):
        prev_pts, prev_vis, pts = layers[k - 1], vis[k - 1], layers[k]
        # 点 → 角
        msg = {}
        for p, links in enumerate(prev_vis):
            vp = value[p]
            for u, d in links:
                c = vp + d
                if c < msg.get(u, (math.inf,))[0]:
                    msg[u] = (c, p)
        # 角 → 角
        ends = {w for links in vis[k] for w, _ in links}
        m2 = {}
        for w in ends:
            best = (math.inf, None)
            for u, (c, _) in msg.items():
                t = c + em.dist[u][w]
                if t < best[0]:
                    best = (t, u)
            m2[w] = best
        new_value, new_back = [], []
        by_value = sorted(range(len(prev_pts)), key=value.__getitem__)
        (pcx, pcy), prev_r = anchors[k - 1]
        spread = OCTILE_PER_EUCLID * prev_r
        # 2つの円の間に壁がなければ（中心どうしの線分を、体の大きさ＋両方の半径だけ太らせても壁に触れなければ）、
        # 前の候補とこの候補のどの組もまっすぐ見通せるので、組ごとの見通しの判定を省く
        (ccx, ccy), cur_r = anchors[k]
        all_visible = g.segment_free(pcx, pcy, ccx, ccy, g.radius + prev_r + cur_r)
        for q, (qx, qy) in enumerate(pts):
            best = (math.inf, None, None)
            for w, d in vis[k][q]:
                t, u = m2[w]
                if t + d < best[0]:
                    best = (t + d, msg[u][1], (u, w))
            # まっすぐ見通せる組（角を通る道より短くなりうるものだけ、見通しを調べる）。
            # 前の候補は「そこまでの長さ」の短い順に見て、残りがどれも今の最短に届かなくなったら打ち切る
            # （前の候補はどれも前の円の中心から直線距離 r 以内なので、q までの長さは 中心からの長さ − 1.0824·r 以上）
            reach = octile(pcx, pcy, qx, qy) - spread
            for p in by_value:
                if value[p] + reach >= best[0]:
                    break
                px, py = prev_pts[p]
                t = value[p] + octile(px, py, qx, qy)
                if t < best[0] and (all_visible or g.segment_free(px, py, qx, qy)):
                    best = (t, p, None)
            new_value.append(best[0])
            new_back.append((best[1], best[2]))
        value = new_value
        if keep_back:
            back.append(new_back)
        if min(value) > limit:
            return [math.inf] * len(layers[-1]), back
    return value, back


class OrderScorer:
    """順番を「円に触れればよい」ことまで入れた長さで比べる（順番を選ぶとき用）。

    円の周の候補は少なめ（samples 個）にし、候補の点と、そこから見える角は、アイテムごとに一度だけ計算して
    どの順番にも使い回す。順番1つの長さは chain_dp で数ミリ秒。候補が少ない分、長さは本当の最短より
    少し長めに出るが（保証の幅は solve_exact と同じ式）、順番どうしを比べるには十分。"""

    def __init__(self, world, item_cells, samples=24, radius=PLAYER_RADIUS):
        self.em = exact_map(world, radius)
        g = self.em.graph
        start = cell_center(PLAYER_START)
        self.start_layer = ([start], [g.attach(*start)], (start, 0.0))
        centers = [cell_center(c) for c in item_cells] + [cell_center(EXIT_CELL)]
        radii = [ITEM_PICKUP_DISTANCE - INSIDE] * len(item_cells) + [EXIT_DISTANCE - INSIDE]
        self.layers = []
        for (cx, cy), rad in zip(centers, radii):
            pts, _ = circle_samples(g, cx, cy, rad, samples)
            self.layers.append((pts, [g.attach(x, y) for x, y in pts], ((cx, cy), rad)))

    def length(self, order, limit=math.inf):
        """順番 order の長さ（limit を超えると分かった時点で打ち切り、inf を返す）。"""
        chosen = [self.start_layer] + [self.layers[i] for i in order] + [self.layers[-1]]
        value, _ = chain_dp(self.em, [c[0] for c in chosen], [c[1] for c in chosen], [c[2] for c in chosen],
                            limit=limit)
        return min(value)


def frames_for(length):
    """長さ length を進むのに要るコマ数の下限（1コマで進めるのは長さ 0.153 まで）。"""
    return math.ceil(length / (PLAYER_RUN_SPEED * SIM_DT) - 1e-9)


def strict_lower_bound(world, item_cells, samples=72):
    """どの順番で、どう動かしても、これより少ないコマではクリアできないコマ数（厳密な下限）。

    体の大きさ STRICT_RADIUS の地図で、中心どうしの最短距離を測り、そこから「中心から円の周まで」の分を引いて、
    一番短い順番を動的計画法で求める（route_order.solve_order）。円に触れる点を b とすると、
    b どうしの距離 ≥ 中心どうしの距離 − (中心 → b の距離) × 2 なので、中心 → 周の距離の最大 R を引けばよい。
    R は周の上の候補の点で測り、候補の間の分（弧に沿って回り込む分）を足して、取りこぼしのないようにする。
    戻り値は (コマ数, 計算の秒数)。"""
    started = time.perf_counter()
    g = exact_map(world, STRICT_RADIUS).graph
    centers_xy = [cell_center(c) for c in item_cells] + [cell_center(EXIT_CELL)]
    radii = [ITEM_PICKUP_DISTANCE] * len(item_cells) + [EXIT_DISTANCE]
    centers = [Point(g, x, y) for x, y in centers_xy]
    start = Point(g, *cell_center(PLAYER_START))
    reach = []
    for center, rad in zip(centers, radii):
        points, widest = circle_samples(g, center.x, center.y, rad, samples)
        far = 0.0
        for x, y in points:
            if g.segment_free(center.x, center.y, x, y):
                d = octile(center.x, center.y, x, y)
            else:
                d = center.distance_to(g, Point(g, x, y))[0]
            far = max(far, d)
        reach.append(far + OCTILE_PER_EUCLID * rad * widest / 2)
    n = len(item_cells)
    items, exit_point = centers[:n], centers[n]
    start_to_item = [max(0.0, start.distance_to(g, c)[0] - reach[j]) for j, c in enumerate(items)]
    item_to_item = [[max(0.0, a.distance_to(g, b)[0] - reach[i] - reach[j]) for j, b in enumerate(items)]
                    for i, a in enumerate(items)]
    item_to_exit = [max(0.0, c.distance_to(g, exit_point)[0] - reach[i] - reach[n]) for i, c in enumerate(items)]
    _, shortest = solve_order(start_to_item, item_to_item, item_to_exit)
    return frames_for(shortest), time.perf_counter() - started
