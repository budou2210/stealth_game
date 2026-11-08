"""タイムアタックの攻略ボット（鬼がいないので「8個のアイテムを集めて出口へ行く一番速い順番と道」を探すだけ）。

使い方（プロジェクトのフォルダで）:
    uv run python -m tools.bot.time_attack --seed 5           （種5の配置を1つ解く）
    uv run python -m tools.bot.time_attack --seeds 0-99       （種0〜99をまとめて解き、平均と最速を出す）
    uv run python -m tools.bot.play_record bot_results/time_attack/wins/seed_5.json   （本物の画面で再生）

計算の流れと、計算量を減らす工夫：
1. 距離（マスの数ではなく、斜め移動を入れた「本当の移動距離」）
   プレイヤーは8方向にしか動けず、斜めでも速さは同じ。なので障害物がなければ、(dx, dy) 進むのにかかる距離は
   「オクタイル距離」 max(dx, dy) + (√2 - 1)·min(dx, dy) そのもの。マス目の上の8方向のダイクストラ法で、
   この距離をそのまま測る。
   全マス（約1600）どうしの距離は求めず、必要な9か所（アイテム8個・出口）を起点にした
   ダイクストラを9回だけ行う（スタートからの距離は、この9枚の地図を引けば分かる）。各回の結果は「そこへ向かう距離の地図」として、動かすときにもそのまま使う。
2. 順番
   8個の並べ方は 8! = 40320 通りあり、それぞれ9区間を足すと約36万回の足し算になる。
   代わりに「残りの集合と今いる場所」ごとに最短の残り距離を表にする動的計画法（Held-Karp）で、
   2^8 × 8 × 8 ≈ 1.6万回の計算で最短の順番を出す。
   さらにこの表は「ここから先の最短」が正確に分かるので、最短の少し上（--margin）までの順番だけを、
   無駄な枝を1本もたどらずに全部挙げられる（分枝限定法の、限界が正確な場合）。
3. 実際に動かして比べる
   マス目の距離は、アイテムは0.7まで近づけば拾える・出口は0.9まで近づけばよい・角を少し削れる、
   といった点を含まない。そこで、候補の順番（--candidates 本まで）を本物と同じ処理のシミュレーターで
   実際に動かして、一番速いものを残す。今までの最速より遅くなった時点で、その候補の動かしを打ち切る。
"""

import argparse
import heapq
import json
import math
import time
from pathlib import Path

from stealth_game.difficulty import TIME_ATTACK
from stealth_game.grid import cell_center, world_to_cell
from stealth_game.layout import EXIT_CELL
from stealth_game.world import World

from .levels import RESULTS_ROOT
from .planner import encode_keys
from .sim import DT, Sim

SQRT2 = math.sqrt(2)
NEIGHBORS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
DEADZONE = 0.08  # 目標との差がこれ未満の向きには動かない（1コマに進むのは約0.15）
MAX_FRAMES = 3600  # 1回の動かしの上限（120秒）
RESULTS = RESULTS_ROOT / "time_attack"


# --- 1. 距離 ----------------------------------------------------------------
def walkable(world):
    """プレイヤーが歩けるマス（マップの外に出っ張ったスタートの小部屋も含む。タイムアタックでは扉は閉まらない）。"""
    return set(world.floor_cells) | set(world.pocket)


def distance_field(cells, goal):
    """goal までの8方向の移動距離を、全マスについて求める（ダイクストラ法）。
    斜めは、両隣のマスが両方とも床のときだけ通れる（壁の角をすり抜けない）。"""
    dist = {goal: 0.0}
    queue = [(0.0, goal)]
    while queue:
        d, (x, y) = heapq.heappop(queue)
        if d > dist[(x, y)]:
            continue
        for dx, dy in NEIGHBORS:
            n = (x + dx, y + dy)
            if n not in cells:
                continue
            if dx and dy and ((x + dx, y) not in cells or (x, y + dy) not in cells):
                continue
            nd = d + (SQRT2 if dx and dy else 1.0)
            if nd < dist.get(n, math.inf):
                dist[n] = nd
                heapq.heappush(queue, (nd, n))
    return dist


# --- 2. 順番 ----------------------------------------------------------------
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


# --- 3. 実際に動かす ----------------------------------------------------------
def keys_toward(px, py, tx, ty):
    keys = set()
    if tx - px > DEADZONE:
        keys.add("right")
    elif px - tx > DEADZONE:
        keys.add("left")
    if ty - py > DEADZONE:
        keys.add("up")
    elif py - ty > DEADZONE:
        keys.add("down")
    return keys


def next_cell(field, cell, cells):
    """距離の地図を1歩下る（斜めは壁の角をすり抜けない）。"""
    x, y = cell
    best, best_d = None, field.get(cell, math.inf)
    for dx, dy in NEIGHBORS:
        n = (x + dx, y + dy)
        if n not in field:
            continue
        if dx and dy and ((x + dx, y) not in cells or (x, y + dy) not in cells):
            continue
        d = field[n] + (SQRT2 if dx and dy else 1.0)
        if d <= best_d + 1e-9 and field[n] < field.get(cell, math.inf):
            best, best_d = n, d
    return best


def drive(seed, order, fields, cells, give_up=math.inf):
    """順番どおりに動かす。戻り値 (クリアの秒数 または None, 入力の記録)。
    give_up 秒を超えたら打ち切る（今までの最速より遅いことが確定したので）。"""
    sim = Sim(seed, cfg=TIME_ATTACK)
    targets = list(order) + ["exit"]
    log = []
    while not sim.done and len(log) < MAX_FRAMES:
        while targets[0] != "exit" and targets[0] in sim.items_collected:
            targets.pop(0)  # 拾えたら（中心まで行かなくても）すぐ次へ
        target = targets[0]
        goal = EXIT_CELL if target == "exit" else sim.item_cells[target]
        field = fields[goal]
        here = world_to_cell(sim.player.x, sim.player.y)
        step = next_cell(field, here, cells) if here != goal else None
        tx, ty = cell_center(step if step is not None else goal)
        keys = keys_toward(sim.player.x, sim.player.y, tx, ty)
        sim.step(keys)
        log.append(frozenset(keys))
        if sim.elapsed > give_up:
            return None, log
    return (sim.elapsed if sim.state == "win" else None), log


def solve(seed, candidates=20, margin=0.08, world=None):
    """種 seed の配置を解く。戻り値は結果の辞書（入力の記録つき）。"""
    started = time.perf_counter()
    world = world or World()
    cells = walkable(world)
    sim = Sim(seed, cfg=TIME_ATTACK, world=world)
    items = list(sim.item_cells)
    start = world_to_cell(sim.player.x, sim.player.y)
    fields = {goal: distance_field(cells, goal) for goal in items + [EXIT_CELL]}  # ダイクストラ9回
    start_to_item = [fields[c][start] for c in items]
    item_to_item = [[fields[b][a] for b in items] for a in items]
    item_to_exit = [fields[EXIT_CELL][a] for a in items]
    cost, shortest = solve_order(start_to_item, item_to_item, item_to_exit)
    orders = near_best_orders(cost, start_to_item, item_to_item, shortest * (1 + margin), candidates)
    plan_seconds = time.perf_counter() - started

    best_time, best_order, best_log = math.inf, None, None
    for _, order in orders:
        t, log = drive(seed, order, fields, cells, give_up=best_time)
        if t is not None and t < best_time:
            best_time, best_order, best_log = t, order, log
    return {
        "seed": seed,
        "outcome": "win" if best_log is not None else "fail",
        "time": round(best_time, 4) if best_log is not None else None,
        "order": best_order,
        "grid_distance": round(shortest, 3),
        "candidates": len(orders),
        "plan_seconds": round(plan_seconds, 4),
        "total_seconds": round(time.perf_counter() - started, 3),
        "keys": encode_keys(best_log) if best_log is not None else [],
    }


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
              "level": TIME_ATTACK.key, "order": result["order"], "keys": result["keys"]}
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
    parser.add_argument("--candidates", type=int, default=20, help="実際に動かして比べる順番の数の上限")
    parser.add_argument("--margin", type=float, default=0.08, help="最短の距離から何割増しまでの順番を候補にするか")
    parser.add_argument("--results", type=Path, default=RESULTS, help="結果のフォルダ")
    args = parser.parse_args()
    seeds = parse_seeds(args.seeds) if args.seeds else [args.seed if args.seed is not None else 0]
    world = World()
    times = []
    for seed in seeds:
        result = solve(seed, args.candidates, args.margin, world)
        saved = save(result, args.results)
        if result["outcome"] == "win":
            times.append((result["time"], seed))
        print(f"種 {seed}: {result['outcome']}  {result['time']}秒  順番 {result['order']}  "
              f"候補 {result['candidates']}本  計画 {result['plan_seconds']}秒・全体 {result['total_seconds']}秒"
              f"{'  （保存）' if saved else ''}")
    if len(times) > 1:
        print(f"クリア {len(times)}/{len(seeds)}  平均 {sum(t for t, _ in times) / len(times):.2f}秒  "
              f"最速 {min(times)[0]:.2f}秒（種 {min(times)[1]}）")


if __name__ == "__main__":
    main()
