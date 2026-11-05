"""時間と場所の両方を考える経路探索。

見つかっていない間、警備員はプレイヤーに反応しない。そこで、
1. プレイヤーを透明にしたシミュレーターで警備員だけを先へ動かし、「何秒後に、どのマスが誰かの視界に入るか」
   「どのマスなら走っても足音を聞かれないか」の予定表を作る。
2. 0.5秒を1区切りとして、各区切りに「見つからずにいられるマス」だけをたどり、目標へ一番近づく経路を探す。
   1区切りでできる動きは「止まる」「忍び足で上下左右に1マス」「走って上下左右に2マス」。
   走れるのは、走っても見つからず（走ると視界に入る距離が伸びる）、足音も聞かれないときだけ。

徘徊型（紫）は目的地を選ぶときにプレイヤーの位置を少し参考にするので、予定表は完全ではない。
そのため、実行する前に本物どおりのシミュレーターで確かめる（planner.py）。
"""

import math
from collections import OrderedDict

from stealth_game.constants import NEAR_SENSE_RADIUS, SOUND_WALL_MUFFLE
from stealth_game.grid import world_to_cell

from .options import enabled

SAMPLE_FRAMES = 3  # 予定表の細かさ（3コマ＝0.1秒ごと）
SLOT_SAMPLES = 5  # 経路の1区切り＝5サンプル＝0.5秒（忍び足で1マス、走って2マス進める長さ）
if enabled("T"):  # 1区切りを14コマ（約0.47秒）にして、忍び足（1秒で2.2マス）で1マスちょうどに近づける
    SAMPLE_FRAMES, SLOT_SAMPLES = 2, 7
HORIZON_SLOTS = 24  # 何区切り先まで探すか（12秒）
# 余裕は小さめにして積極的に動く（倍の余裕と比べて、32配置でクリア 23→27、平均タイム約27%短縮）。
# 実行前に本物どおりのシミュレーションで確かめるので、余裕が小さくても見つかる経路は使わない
VIEW_MARGIN = 0.3  # 視界の距離の余裕（体の大きさと、ずれへの備え）
ANGLE_MARGIN = math.radians(5)  # 視野角の余裕
NEAR_MARGIN = 0.3  # すぐそばで気づかれる距離の余裕
HEAR_MARGIN = 0.6  # 足音が届く距離の余裕
RELEVANT_DISTANCE = 26.0  # プレイヤーからこれより遠い警備員は、予定表に入れない（計算を減らす）

SNEAK = "sneak"
RUN = "run"


def predict_guards(sim, slots=HORIZON_SLOTS):
    """プレイヤーを透明にして止めたまま、警備員の位置と向きを SAMPLE_FRAMES ごとに記録する。"""
    s = sim.snapshot()
    s.cloak_timer = 1e9  # 透明：見られず、触れても捕まらない（足音も出さない＝止まっている）
    samples = []
    for _ in range(slots * SLOT_SAMPLES + 1):
        samples.append([(g.x, g.y, g.heading) for g in s.guards])
        for _ in range(SAMPLE_FRAMES):
            s.step(frozenset())
            if s.done:
                break
    return samples


# 計算を速くするための覚え書き。どれも「同じ入力なら同じ結果」になるものだけを覚えるので、結果は変わらない。
# - 警備員のいるマスの周りの床の一覧（壁は動かないので、一度作れば使い回せる）
# - 警備員1人ぶんの「見えるマス」「足音が聞こえるマス」（位置と向きが同じなら同じ）。
#   判断は1秒ごとに12秒先まで予定表を作り直すので、前回と重なる11秒ぶんはここから取り出せる
_FLOOR_NEAR = {}
_SEEN_MEMO = OrderedDict()
_HEARD_MEMO = OrderedDict()
MEMO_LIMIT = 6000  # 覚えておく数の上限（多すぎるとメモリを使いすぎるので、古いものから捨てる）


def floor_near(world, gx, gy, radius):
    """(gx, gy) のマスを中心に、半径 radius の四角の範囲にある床のマス（壁を除く）。"""
    r = int(math.ceil(radius))
    gcx, gcy = world_to_cell(gx, gy)
    key = (gcx, gcy, r, world.doors_closed)
    cells = _FLOOR_NEAR.get(key)
    if cells is None:
        cells = [
            (cx, cy)
            for cy in range(gcy - r, gcy + r + 1)
            for cx in range(gcx - r, gcx + r + 1)
            if not world.is_wall(cx, cy)
        ]
        _FLOOR_NEAR[key] = cells
    return cells


def _remember(memo, key, value):
    memo[key] = value
    if len(memo) > MEMO_LIMIT:
        memo.popitem(last=False)
    return value


def guard_seen(world, gx, gy, heading, cfg):
    """警備員1人から見えるマス：(忍び足で見つかるマス, 走っていると見つかるマス)。"""
    key = (gx, gy, heading, world.doors_closed)
    hit = _SEEN_MEMO.get(key)
    if hit is not None:
        _SEEN_MEMO.move_to_end(key)
        return hit
    sneak_view = cfg.view_range * cfg.sneak_view_rate + VIEW_MARGIN
    run_view = cfg.view_range + VIEW_MARGIN
    half = cfg.view_half_angle + ANGLE_MARGIN
    near = NEAR_SENSE_RADIUS + NEAR_MARGIN
    sneak_seen, run_seen = [], []
    for cell in floor_near(world, gx, gy, run_view):
        tx, ty = cell[0] + 0.5, cell[1] + 0.5
        dist = math.hypot(tx - gx, ty - gy)
        if dist > run_view:
            continue
        if dist > near:
            diff = (math.atan2(ty - gy, tx - gx) - heading + math.pi) % (2 * math.pi) - math.pi
            if abs(diff) > half:
                continue
        if world.has_line_of_sight(gx, gy, tx, ty):
            run_seen.append(cell)
            if dist <= sneak_view:
                sneak_seen.append(cell)
    return _remember(_SEEN_MEMO, key, (frozenset(sneak_seen), frozenset(run_seen)))


def guard_heard(world, gx, gy, cfg):
    """警備員1人に、走ると足音を聞かれるマス（壁越しは届く距離が縮む）。"""
    key = (gx, gy, world.doors_closed)
    hit = _HEARD_MEMO.get(key)
    if hit is not None:
        _HEARD_MEMO.move_to_end(key)
        return hit
    radius = cfg.hear_radius + HEAR_MARGIN
    through_wall = cfg.hear_radius * SOUND_WALL_MUFFLE + HEAR_MARGIN
    heard = []
    for cell in floor_near(world, gx, gy, radius):
        tx, ty = cell[0] + 0.5, cell[1] + 0.5
        dist = math.hypot(tx - gx, ty - gy)
        if dist > radius:
            continue
        if dist <= through_wall or world.has_line_of_sight(gx, gy, tx, ty):
            heard.append(cell)
    return _remember(_HEARD_MEMO, key, frozenset(heard))


def visible_cells(world, guards, cfg, px, py):
    """そのときの警備員の並びで、見つかるマス。(忍び足で見つかるマス, 走っていると見つかるマス)。"""
    sneak_seen, run_seen = set(), set()
    for gx, gy, heading in guards:
        if math.hypot(gx - px, gy - py) > RELEVANT_DISTANCE:
            continue
        sneak, run = guard_seen(world, gx, gy, heading, cfg)
        sneak_seen |= sneak
        run_seen |= run
    return sneak_seen, run_seen


def audible_cells(world, guards, cfg, px, py):
    """走ると足音を聞かれるマス（壁越しは届く距離が縮む）。"""
    heard = set()
    for gx, gy, _ in guards:
        if math.hypot(gx - px, gy - py) > RELEVANT_DISTANCE:
            continue
        heard |= guard_heard(world, gx, gy, cfg)
    return heard


def danger_schedule(sim, slots=HORIZON_SLOTS):
    """区切りごとの (忍び足で危ないマス, 走ると危ないマス)。その区切りの間に一度でも危ないマスを全部含む。"""
    samples = predict_guards(sim, slots)
    px, py = sim.player.x, sim.player.y
    world, cfg = sim.world, sim.difficulty
    seen = [visible_cells(world, guards, cfg, px, py) for guards in samples]
    schedule = []
    for k in range(slots):
        first, last = k * SLOT_SAMPLES, (k + 1) * SLOT_SAMPLES
        sneak_unsafe, run_unsafe = set(), set()
        for i in range(first, last + 1):
            sneak_unsafe |= seen[i][0]
            run_unsafe |= seen[i][1]
        # 足音は区切りの最初と最後の並びで調べる（余裕を広めにとってある）。V（速度重視）のときは足音を気にしない
        if not enabled("V"):
            run_unsafe |= audible_cells(world, samples[first], cfg, px, py)
            run_unsafe |= audible_cells(world, samples[last], cfg, px, py)
        schedule.append((sneak_unsafe, run_unsafe))
    return schedule


def moves_from(world, cell):
    """1区切りでできる動き：(行き先, 途中で通るマス, 走るか)。"""
    cx, cy = cell
    yield cell, (), SNEAK
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        one = (cx + dx, cy + dy)
        if world.is_wall(*one):
            continue
        yield one, (), SNEAK
        two = (cx + 2 * dx, cy + 2 * dy)
        if not world.is_wall(*two):
            yield two, (one,), RUN


def plan_path(world, start, schedule, field, forbidden=frozenset(), floor_value=0.0):
    """区切りごとに動きを選び、見つからない（走るときは足音も聞かれない）マスだけをたどる。

    できるだけ先の区切りまで見つからずにいられ、その途中で目標までの距離（field）が一番小さくなる経路を返す
    （区切りごとの (マス, "sneak" か "run") の列）。最初の区切りから安全なマスがなければ None。
    floor_value: 距離がこれ以下は同じとみなす（最後のアイテムの手前で待つとき用）。
    """
    def value(cell):
        return max(field.dist.get(cell, math.inf), floor_value)

    early = enabled("C") or enabled("V")
    layer = {start: value(start)}
    reached = {start: 0}  # {マス: 経路の中で、一番近づいた距離に初めて届いた区切り}（C のとき使う）
    parents = []
    for k, (sneak_unsafe, run_unsafe) in enumerate(schedule):
        nxt = {}
        best_along = {}  # {マス: そこへ来るまでの経路で、目標に一番近づいたときの距離}
        best_reached = {}
        for cell, along in layer.items():
            for n, passed, mode in moves_from(world, cell):
                if n in forbidden or any(p in forbidden for p in passed):
                    continue
                unsafe = run_unsafe if mode == RUN else sneak_unsafe
                if n in unsafe or any(p in unsafe for p in passed):
                    continue
                if k > 0 and n != cell and cell in unsafe:  # 最初の区切りは、今いるマスが危なくても出てよい
                    continue
                v = min(along, value(n))
                r = k if value(n) < along else reached[cell]
                if n not in nxt or v < best_along[n] or (
                        v == best_along[n] and ((early and r < best_reached[n]) or (not early and mode == SNEAK))):
                    nxt[n] = (cell, mode)
                    best_along[n] = v
                    best_reached[n] = r
        if not nxt:
            break  # これより先は、どこにいても見つかる
        parents.append(nxt)
        layer = best_along
        reached = best_reached
    if not parents:
        return None
    # 一番先の区切りまで見つからずにいられる経路のうち、途中で目標に一番近づけるもの。
    # 最後までもつ経路がなければ、一番長く逃げ切れる経路の中から選ぶことになる
    if early:
        final = min(layer, key=lambda c: (layer[c], reached[c], value(c)))
    else:
        final = min(layer, key=lambda c: (layer[c], value(c)))
    path = []
    cell = final
    for k in range(len(parents) - 1, -1, -1):
        prev, mode = parents[k][cell]
        path.append((cell, mode))
        cell = prev
    path.reverse()
    return path
