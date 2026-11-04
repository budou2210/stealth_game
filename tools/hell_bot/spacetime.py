"""時間と場所の両方を考える経路探索。

見つかっていない間、警備員はプレイヤーに反応しない。そこで、
1. プレイヤーを透明にしたシミュレーターで警備員だけを先へ動かし、「何秒後に、どのマスが誰かの視界に入るか」の予定表を作る。
2. 0.5秒を1区切りとして、各区切りに「見つからずにいられるマス」だけをたどり、目標へ一番近づく経路を探す。

徘徊型（紫）は目的地を選ぶときにプレイヤーの位置を少し参考にするので、予定表は完全ではない。
そのため、実行する前に本物どおりのシミュレーターで確かめる（planner.py）。
"""

import math

from stealth_game.constants import NEAR_SENSE_RADIUS
from stealth_game.grid import world_to_cell

SAMPLE_FRAMES = 3  # 予定表の細かさ（3コマ＝0.1秒ごと）
SLOT_SAMPLES = 5  # 経路の1区切り＝5サンプル＝0.5秒（忍び足で1マス進める長さ）
HORIZON_SLOTS = 24  # 何区切り先まで探すか（12秒）
VIEW_MARGIN = 0.6  # 視界の距離の余裕（体の大きさと、ずれへの備え）
ANGLE_MARGIN = math.radians(10)  # 視野角の余裕
NEAR_MARGIN = 0.6  # すぐそばで気づかれる距離の余裕
RELEVANT_DISTANCE = 26.0  # プレイヤーからこれより遠い警備員は、予定表に入れない（計算を減らす）


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


def visible_cells(world, guards, cfg, px, py):
    """そのときの警備員の並びで、忍び足のプレイヤーが見つかるマスの集まり。"""
    view = cfg.view_range * cfg.sneak_view_rate + VIEW_MARGIN
    half = cfg.view_half_angle + ANGLE_MARGIN
    near = NEAR_SENSE_RADIUS + NEAR_MARGIN
    seen = set()
    for gx, gy, heading in guards:
        if math.hypot(gx - px, gy - py) > RELEVANT_DISTANCE:
            continue
        r = int(math.ceil(view))
        gcx, gcy = world_to_cell(gx, gy)
        for cy in range(gcy - r, gcy + r + 1):
            for cx in range(gcx - r, gcx + r + 1):
                if (cx, cy) in seen or world.is_wall(cx, cy):
                    continue
                tx, ty = cx + 0.5, cy + 0.5
                dist = math.hypot(tx - gx, ty - gy)
                if dist > view:
                    continue
                if dist > near:
                    angle = math.atan2(ty - gy, tx - gx)
                    diff = (angle - heading + math.pi) % (2 * math.pi) - math.pi
                    if abs(diff) > half:
                        continue
                if world.has_line_of_sight(gx, gy, tx, ty):
                    seen.add((cx, cy))
    return seen


def danger_schedule(sim, slots=HORIZON_SLOTS):
    """区切りごとの「見つかるマス」（その区切りの間に一度でも見つかるマスを全部含む）。"""
    samples = predict_guards(sim, slots)
    px, py = sim.player.x, sim.player.y
    per_sample = [visible_cells(sim.world, guards, sim.difficulty, px, py) for guards in samples]
    schedule = []
    for k in range(slots):
        cells = set()
        for i in range(k * SLOT_SAMPLES, (k + 1) * SLOT_SAMPLES + 1):
            cells |= per_sample[i]
        schedule.append(cells)
    return schedule


def plan_path(world, start, schedule, field, forbidden=frozenset(), floor_value=0.0):
    """区切りごとに「止まる／上下左右に1マス」を選び、見つからないマスだけをたどる。

    できるだけ先の区切りまで見つからずにいられ、その途中で目標までの距離（field）が一番小さくなる経路を返す
    （区切りごとのマスの列）。最初の区切りから安全なマスがなければ None。
    floor_value: 距離がこれ以下は同じとみなす（最後のアイテムの手前で待つとき用）。
    """
    def value(cell):
        return max(field.dist.get(cell, math.inf), floor_value)

    layer = {start: value(start)}
    parents = []
    for k, unsafe in enumerate(schedule):
        nxt = {}
        best_along = {}  # {マス: そこへ来るまでの経路で、目標に一番近づいたときの距離}
        for cell, along in layer.items():
            cx, cy = cell
            for n in (cell, (cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if n in forbidden or world.is_wall(*n):
                    continue
                if n in unsafe or (k > 0 and n != cell and cell in unsafe):  # 最初の区切りは、今いるマスが危なくても出てよい
                    continue
                v = min(along, value(n))
                if n not in nxt or v < best_along[n]:
                    nxt[n] = cell
                    best_along[n] = v
        if not nxt:
            break  # これより先は、どこにいても見つかる
        parents.append(nxt)
        layer = best_along
    if not parents:
        return None
    # 一番先の区切りまで見つからずにいられる経路のうち、途中で目標に一番近づけるもの。
    # 8秒もつ経路がなければ、一番長く逃げ切れる経路の中から選ぶことになる
    final = min(layer, key=lambda c: (layer[c], value(c)))
    path = [final]
    for k in range(len(parents) - 1, 0, -1):
        path.append(parents[k][path[-1]])
    path.reverse()
    return path
