"""タイムアタックの攻略ボット（鬼がいないので「8個のアイテムを集めて出口へ行く一番速い順番と道」を探すだけ）。

使い方（プロジェクトのフォルダで）:
    uv run python -m tools.bot.time_attack --seed 5           （種5の配置を1つ解く）
    uv run python -m tools.bot.time_attack --seeds 0-99       （種0〜99をまとめて解き、平均と最速を出す）
    uv run python -m tools.bot.play_record bot_results/time_attack/wins/seed_5.json   （本物の画面で再生）

計算の流れと、計算量を減らす工夫：
1. 距離：壁の角だけを中継点にした地図（ta_graph.py の可視グラフ）で、体の半径（0.3）まで壁に寄った
   本当の最短の道と距離を求める。8方向（斜めも同じ速さ）なので距離はオクタイル距離。
   地図はマップが同じなら全部の配置で同じなので、1回だけ作って使い回す。
2. 順番：8個の並べ方 8! = 40320 通りを全部比べず、動的計画法（Held-Karp、2^8 × 8 × 8 ≈ 1.6万回）で最短を出す。
   その表は「ここから先の最短」が正確に分かるので、最短の少し上（--margin）までの順番だけを、
   無駄な枝をたどらずに挙げる。
3. 触れる点：アイテムは中心から0.7、出口は0.9まで近づけば十分。候補の順番ごとに、それぞれの円の上で
   「前の点からの距離＋次の点までの距離」が一番短くなる点を、1つずつ順に選び直して決める（数回くり返す）。
4. 動かす：道の点を順に目指す。8方向のうち、目指す点までの距離が一番縮む向き（同じなら線から外れない向き）を
   1コマごとに選び、先の点が見通せたら、手前の点を飛ばしてそちらを目指す。
   候補の順番を本物と同じ処理のシミュレーターで動かして、一番速いものを残す（最速を超えたら打ち切る）。
5. 仕上げ：残した入力の「キーを切り替えるコマ」を前後にずらしたり、1コマだけ向きを変えたりして、
   速くなれば採る（--refine-seconds 秒まで）。途中の状態を15コマごとに取っておき、変えたコマの手前から動かし直す。
6. 下限：「これより速くはできない時間」の目安も出す（下の lower_bound）。
"""

import argparse
import json
import math
import random
import time
from pathlib import Path

from stealth_game.constants import ITEM_PICKUP_DISTANCE, PLAYER_RADIUS, PLAYER_RUN_SPEED
from stealth_game.difficulty import TIME_ATTACK
from stealth_game.grid import cell_center
from stealth_game.layout import EXIT_CELL
from stealth_game.player import Player
from stealth_game.world import World

from .levels import RESULTS_ROOT
from .planner import decode_keys, encode_keys
from .sim import DT, Sim
from .ta_graph import Graph, Point, octile

EXIT_DISTANCE = 0.9  # 出口はこの距離まで近づけばよい（StealthGame.check_exit_reached）
TOUCH_MARGIN = 0.06  # 触れる点は、拾える距離よりこれだけ内側に置く
TOUCH_ANGLES = 24  # 触れる点の候補（円の上の向きの数）
TOUCH_ROUNDS = 3  # 触れる点を選び直すくり返しの数
OCTILE_PER_EUCLID = 1.0824  # 同じ直線距離で、オクタイル距離が一番長くなる向き（22.5°）での比 cos + (√2-1)·sin
DIRECTIONS = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
MAX_FRAMES = 3600  # 1回の動かしの上限（120秒）
CHECKPOINT_EVERY = 15  # 仕上げで取っておく途中の状態の間隔（コマ）
RESULTS = RESULTS_ROOT / "time_attack"

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


def lower_bound(start_to_item, item_to_item, item_to_exit):
    """「これより速くはできない」移動距離の目安。中心どうしの最短距離から、触れればよい円の分を引いて
    （円の中の直線距離 r は、8方向の移動では最大 1.0824·r）、同じ動的計画法で一番短い順番を求める。
    壁が円にかかっていると円の中でも回り道になるので、厳密な下限ではなく目安。"""
    k = OCTILE_PER_EUCLID
    item, ex = ITEM_PICKUP_DISTANCE * k, EXIT_DISTANCE * k
    s = [max(0.0, d - item) for d in start_to_item]
    m = [[max(0.0, d - 2 * item) for d in row] for row in item_to_item]
    e = [max(0.0, d - item - ex) for d in item_to_exit]
    return solve_order(s, m, e)[1]


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


def plan_route(graph, start, centers, exit_point, order, candidates_cache):
    """順番 order の道。戻り値 ([(x, y, 区間の番号, 種類)], 区間ごとの目標)。区間 i は i 番目の目標へ向かう道
    （最後の区間は出口）。種類は "corner"（壁の角）・"touch"（触れる点）・"center"（目標の中心）。"""
    targets = [centers[i] for i in order] + [exit_point]
    radii = [ITEM_PICKUP_DISTANCE - TOUCH_MARGIN] * len(order) + [EXIT_DISTANCE - TOUCH_MARGIN]
    keys = list(order) + ["exit"]
    touch = [start] + list(targets)
    for _ in range(TOUCH_ROUNDS):
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


def drive(seed, graph, route, keys, give_up=math.inf):
    """道どおりに動かす。戻り値 (クリアの秒数 または None, 入力の記録)。give_up 秒を超えたら打ち切る。"""
    sim = Sim(seed, cfg=TIME_ATTACK, world=graph.world)
    log = []
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
        if sim.elapsed > give_up:
            return None, log
    return (sim.elapsed if sim.state == "win" else None), log


# --- 仕上げ（入力を直接ずらして縮める） ------------------------------------------
def run_log(sim, log, start, give_up):
    """sim（start コマ目の直前の状態）から log[start:] を流す。戻り値 (クリアまでのコマ数 または None, 拾ったコマの合計)。"""
    picked = 0
    have = len(sim.items_collected)
    for f in range(start, len(log)):
        sim.step(log[f])
        if len(sim.items_collected) != have:
            picked += f * (len(sim.items_collected) - have)
            have = len(sim.items_collected)
        if sim.state == "win":
            return f + 1, picked
        if f + 1 >= give_up:
            return None, picked
    return None, picked


def checkpoints(seed, world, log):
    """log を流しながら、CHECKPOINT_EVERY コマごとの状態と、それまでに拾ったコマの合計を取っておく。"""
    sim = Sim(seed, cfg=TIME_ATTACK, world=world)
    saved = {}
    picked, have = 0, 0
    for f, keys in enumerate(log):
        if f % CHECKPOINT_EVERY == 0:
            saved[f] = (sim.snapshot(), picked)
        sim.step(keys)
        if len(sim.items_collected) != have:
            picked += f * (len(sim.items_collected) - have)
            have = len(sim.items_collected)
    return saved


OPPOSITE = {keys_of(dx, dy): keys_of(-dx, -dy) for dx, dy in DIRECTIONS}
RELOCATE_RANGE = 40  # 入れ替えで、抜いたコマを差し込む先の範囲（前後のコマ数）


def mutate(log, rng):
    """入力の記録を1か所変えたもの。戻り値 (新しい記録, 変えた一番前のコマ)。変えられなければ (None, 0)。

    1か所だけずらすと後の位置が全部ずれて、後のアイテムを拾い損ねる。なので、ずれが後に残らない変え方を主に使う：
    - 入れ替え：あるコマの向きを抜き、近くの別の場所に差し込む（両方を過ぎれば位置は元どおり。道の形だけ変わる）
    - 打ち消し：逆向きのコマを2つ抜く（位置は元どおりで、2コマ縮む）
    - 1コマ抜く：約0.15ずれるが、拾える範囲・出口の範囲に余裕があれば、そのまま1コマ縮む
    """
    n = len(log)
    roll = rng.random()
    if roll < 0.5:
        i = rng.randrange(n)
        j = min(n - 1, max(0, i + rng.randint(-RELOCATE_RANGE, RELOCATE_RANGE)))
        if i == j or log[i] == log[j]:
            return None, 0
        trial = log[:i] + log[i + 1:]
        trial.insert(j, log[i])
        return trial, min(i, j)
    if roll < 0.8:
        i = rng.randrange(n)
        lo, hi = max(0, i - RELOCATE_RANGE), min(n, i + RELOCATE_RANGE + 1)
        want = OPPOSITE.get(log[i])
        matches = [j for j in range(lo, hi) if log[j] == want]
        if not matches:
            return None, 0
        j = rng.choice(matches)
        a, b = sorted((i, j))
        return log[:a] + log[a + 1:b] + log[b + 1:], a
    i = rng.randrange(n)
    return log[:i] + log[i + 1:], i


def refine(seed, world, log, seconds, rng):
    """入力の記録 log（クリアできたもの）を、制限時間まで少しずつ変えて縮める。戻り値は新しい記録。"""
    deadline = time.perf_counter() + seconds
    frames = len(log)
    saved = checkpoints(seed, world, log)
    score = (frames, run_log(Sim(seed, cfg=TIME_ATTACK, world=world), log, 0, frames + 1)[1])
    while time.perf_counter() < deadline:
        trial, first = mutate(log, rng)
        if trial is None:
            continue
        base = first - first % CHECKPOINT_EVERY
        snap, picked = saved[base]
        done, later = run_log(snap.snapshot(), trial, base, score[0] + 1)
        if done is None:
            continue
        new = (done, picked + later)
        if new < score:
            log, score = trial[:done], new
            saved = checkpoints(seed, world, log)
    return log


# --- まとめ ---------------------------------------------------------------------
def solve(seed, candidates=10, margin=0.08, refine_seconds=3.0, world=None):
    """種 seed の配置を解く。戻り値は結果の辞書（入力の記録つき）。"""
    started = time.perf_counter()
    world = world or World()
    graph = graph_for(world)
    sim = Sim(seed, cfg=TIME_ATTACK, world=world)
    xys = ((sim.player.x, sim.player.y), [cell_center(c) for c in sim.item_cells], cell_center(EXIT_CELL))
    (start, centers, exit_point), (start_to_item, item_to_item, item_to_exit) = leg_distances(graph, *xys)
    cost, shortest = solve_order(start_to_item, item_to_item, item_to_exit)
    orders = near_best_orders(cost, start_to_item, item_to_item, shortest * (1 + margin), candidates)
    # 下限の目安は、体の本当の大きさ（壁にぎりぎりまで寄れる）の地図で測る
    bound = lower_bound(*leg_distances(graph_for(world, PLAYER_RADIUS), *xys)[1]) / PLAYER_RUN_SPEED
    plan_seconds = time.perf_counter() - started

    best_time, best_order, best_log = math.inf, None, None
    cache = {}
    for _, order in orders:
        route, keys = plan_route(graph, start, centers, exit_point, order, cache)
        t, log = drive(seed, graph, route, keys, give_up=best_time)
        if t is not None and t < best_time:
            best_time, best_order, best_log = t, order, log
    driven = best_time
    if best_log is not None and refine_seconds > 0:
        best_log = refine(seed, world, best_log, refine_seconds, random.Random(seed))
        best_time = len(best_log) * DT
    win = best_log is not None
    return {
        "seed": seed,
        "outcome": "win" if win else "fail",
        "time": round(best_time, 4) if win else None,
        "driven_time": round(driven, 4) if win else None,  # 仕上げの前のタイム
        "lower_bound": round(bound, 4),
        "order": best_order,
        "distance": round(shortest, 3),
        "candidates": len(orders),
        "plan_seconds": round(plan_seconds, 4),
        "total_seconds": round(time.perf_counter() - started, 3),
        "keys": encode_keys(best_log) if win else [],
    }


def replay_time(seed, keys, world=None):
    """記録を最初から流したときのクリアの秒数（クリアしなければ None）。"""
    sim = Sim(seed, cfg=TIME_ATTACK, world=world)
    for pressed in decode_keys(keys):
        sim.step(pressed)
        if sim.done:
            break
    return sim.elapsed if sim.state == "win" else None


def save(result, results=RESULTS):
    """クリアの記録を play_record で再生できる形で保存する（同じ種で前の記録のほうが速ければ残す）。"""
    if result["outcome"] != "win":
        return False
    folder = results / "wins"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"seed_{result['seed']}.json"
    if path.exists() and json.loads(path.read_text(encoding="utf-8"))["time"] <= result["time"]:
        return False
    record = {"seed": result["seed"], "dt": DT, "time": result["time"], "outcome": "win",
              "level": TIME_ATTACK.key, "order": result["order"], "lower_bound": result["lower_bound"],
              "keys": result["keys"]}
    path.write_text(json.dumps(record), encoding="utf-8")
    return True


def parse_seeds(text):
    if "-" in text:
        lo, hi = text.split("-")
        return list(range(int(lo), int(hi) + 1))
    return [int(s) for s in text.split(",")]


def main():
    parser = argparse.ArgumentParser(description="タイムアタックの攻略ボット")
    parser.add_argument("--seed", type=int, help="解く配置の種（1つ）")
    parser.add_argument("--seeds", help="まとめて解く種（例 0-99 や 1,5,9）")
    parser.add_argument("--candidates", type=int, default=10, help="実際に動かして比べる順番の数の上限")
    parser.add_argument("--margin", type=float, default=0.08, help="最短の距離から何割増しまでの順番を候補にするか")
    parser.add_argument("--refine-seconds", type=float, default=3.0, help="仕上げ（入力をずらして縮める）に使う秒数。0でしない")
    parser.add_argument("--results", type=Path, default=RESULTS, help="結果のフォルダ")
    args = parser.parse_args()
    seeds = parse_seeds(args.seeds) if args.seeds else [args.seed if args.seed is not None else 0]
    world = World()
    times = []
    for seed in seeds:
        r = solve(seed, args.candidates, args.margin, args.refine_seconds, world)
        saved = save(r, args.results)
        if r["outcome"] == "win":
            times.append((r["time"], seed, r["lower_bound"]))
            gap = (r["time"] / r["lower_bound"] - 1) * 100
            print(f"種 {seed}: {r['time']:.2f}秒（仕上げ前 {r['driven_time']:.2f}秒・下限の目安 {r['lower_bound']:.2f}秒・"
                  f"差 {gap:.1f}%）  順番 {r['order']}  候補 {r['candidates']}本  "
                  f"計画 {r['plan_seconds']}秒・全体 {r['total_seconds']}秒{'  （保存）' if saved else ''}")
        else:
            print(f"種 {seed}: クリアできず  候補 {r['candidates']}本")
    if len(times) > 1:
        avg = sum(t for t, _, _ in times) / len(times)
        avg_lb = sum(lb for _, _, lb in times) / len(times)
        best = min(times)
        print(f"クリア {len(times)}/{len(seeds)}  平均 {avg:.2f}秒（下限の目安の平均 {avg_lb:.2f}秒）  "
              f"最速 {best[0]:.2f}秒（種 {best[1]}）")


if __name__ == "__main__":
    main()
