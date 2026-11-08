"""順番を決めたときの、本当の最短の道（触れる点の選び方まで含めて、保証の幅つき）。

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
"""

import math
import time

from .constants import ITEM_PICKUP_DISTANCE, PLAYER_RADIUS, PLAYER_RUN_SPEED
from .grid import cell_center
from .layout import EXIT_CELL, PLAYER_START
from .route_graph import Graph, octile

EXIT_DISTANCE = 0.9
OCTILE_PER_EUCLID = 1.0824  # 直線距離 1 の、8方向の移動での長さの最大（22.5°の向き）
EXACT_GAP = 1e-6  # 角の中継点を、太らせた壁からこれだけ離す（ほぼ0）
INSIDE = 1e-6  # 候補の点は、拾える距離よりこれだけ内側に置く（拾えるのは「より近い」とき）
SAMPLES = 360  # 円の周に並べる候補の数（切れ目の点は別に足す）。360で保証の幅 約0.11（1コマ 0.153 より小さい）・1配置 約3秒

_cache = {}


class ExactMap:
    """本当の大きさの地図と、角どうしの最短距離（とその道）。"""

    def __init__(self, world):
        self.graph = Graph(world, PLAYER_RADIUS, EXACT_GAP)
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


def exact_map(world):
    if id(world) not in _cache:
        _cache[id(world)] = (world, ExactMap(world))
    return _cache[id(world)][1]


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


def solve_exact(world, item_cells, order, samples=SAMPLES):
    """順番 order（アイテムの番号の並び）での本当の最短の道。戻り値は辞書：
    length（求めた長さ）・slack（保証の幅：本当の最短の長さは length − slack 以上）・
    touches（各目標の触れる点）・path（道の点の並び）・min_frames（この順番でのクリアのコマ数の下限）・seconds。"""
    started = time.perf_counter()
    em = exact_map(world)
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

    value = [0.0]
    back = []  # 各区間：候補ごとの (前の候補の番号, 角の並び)
    for k in range(1, len(layers)):
        prev_pts, prev_vis, pts = layers[k - 1], vis[k - 1], layers[k]
        # 点 → 角
        msg = {}
        for p, links in enumerate(prev_vis):
            for u, d in links:
                c = value[p] + d
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
        if k == 1:
            (pcx, pcy), spread = (sx, sy), 0.0
        else:
            (pcx, pcy), spread = targets[k - 2], OCTILE_PER_EUCLID * radii[k - 2]
        # 2つの円の間に壁がなければ（中心どうしの線分を、体の大きさ＋両方の半径だけ太らせても壁に触れなければ）、
        # 前の候補とこの候補のどの組もまっすぐ見通せるので、組ごとの見通しの判定を省く
        cur_c, cur_r = targets[k - 1], radii[k - 1]
        prev_r = 0.0 if k == 1 else radii[k - 2]
        all_visible = g.segment_free(pcx, pcy, cur_c[0], cur_c[1], g.radius + prev_r + cur_r)
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
        back.append(new_back)

    end = min(range(len(value)), key=value.__getitem__)
    length = value[end]
    # 道をたどり直す
    path, touches = [], []
    q = end
    for k in range(len(layers) - 1, 0, -1):
        p, via = back[k - 1][q]
        touches.append(layers[k][q])
        path.append(layers[k][q])
        if via is not None:
            for c in reversed(em.chain(*via)):
                path.append(g.corners[c][:2])
        q = p
    path.append((sx, sy))
    path.reverse()
    touches.reverse()
    k = OCTILE_PER_EUCLID
    slack = sum(2 * k * rad * w / 2 for rad, w in zip(radii[:-1], widest[:-1])) + k * radii[-1] * widest[-1] / 2
    step = PLAYER_RUN_SPEED * (1 / 30)
    return {
        "length": length,
        "slack": slack,
        "touches": touches,
        "path": path,
        "min_frames": math.ceil((length - slack) / step - 1e-9),
        "seconds": time.perf_counter() - started,
    }

