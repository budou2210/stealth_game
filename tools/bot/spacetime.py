"""時間と場所の両方を考える経路探索。

見つかっていない間、警備員はプレイヤーに反応しない。そこで、
1. プレイヤーを透明にしたシミュレーターで警備員だけを先へ動かし、「何秒後に、どのマスが誰かの視界に入るか」
   「どのマスなら走っても足音を聞かれないか」の予定表を作る。
2. 0.5秒を1区切りとして、各区切りに「見つからずにいられるマス」だけをたどり、目標へ一番近づく経路を探す。
   1区切りでできる動きは「止まる」「忍び足で上下左右に1マス」「走って上下左右に2マス」。
   走れるのは、走っても見つからず（走ると視界に入る距離が伸びる）、足音も聞かれないときだけ。

超越では、監視カメラの視界（時刻で決まる）も「見つかるマス」に入れ、閉まっている扉のマスは「いられないマス」にする。
扉の向こうが見えるかどうかは、そのサンプルの時刻の扉の開け閉めで調べる。

徘徊型（紫）は目的地を選ぶときにプレイヤーの位置を少し参考にするので、予定表は完全ではない。
そのため、実行する前に本物どおりのシミュレーターで確かめる（planner.py）。
"""

import math
from collections import OrderedDict
from contextlib import contextmanager

from stealth_game.constants import CAMERA_HALF_ANGLE, CAMERA_VIEW_RANGE, NEAR_SENSE_RADIUS, SOUND_WALL_MUFFLE
from stealth_game.grid import world_to_cell

from .levels import is_tuned
from .options import enabled
from .sim import DT

SAMPLE_FRAMES = 3  # 予定表の細かさ（3コマ＝0.1秒ごと）
SLOT_SAMPLES = 5  # 経路の1区切り＝5サンプル＝0.5秒（忍び足で1マス、走って2マス進める長さ）
if enabled("T"):  # 1区切りを14コマ（約0.47秒）にして、忍び足（1秒で2.2マス）で1マスちょうどに近づける
    SAMPLE_FRAMES, SLOT_SAMPLES = 2, 7
HORIZON_SLOTS = 24  # 何区切り先まで探すか（12秒）
# 余裕は小さめにして積極的に動く（倍の余裕と比べて、32配置でクリア 23→27、平均タイム約27%短縮）。
# 実行前に本物どおりのシミュレーションで確かめるので、余裕が小さくても見つかる経路は使わない
VIEW_MARGIN = 0.15 if enabled("F7") else 0.3  # 視界の距離の余裕（体の大きさと、ずれへの備え）
ANGLE_MARGIN = math.radians(3 if enabled("F7") else 5)  # 視野角の余裕
NEAR_MARGIN = 0.3  # すぐそばで気づかれる距離の余裕
HEAR_MARGIN = 0.3 if enabled("F3") else 0.6  # 足音が届く距離の余裕
RELEVANT_DISTANCE = 26.0  # プレイヤーからこれより遠い警備員は、予定表に入れない（計算を減らす）
# 超越だけ：視界・足音の計算を覚えておくとき、位置と向きをこの単位に丸める（歩いている警備員でも覚えた結果が
# 使えるように）。丸めのずれ（位置は最大0.05、向きは最大1.5°）は、上の余裕（VIEW_MARGIN・ANGLE_MARGIN）の中に収まる
POS_STEP = 0.1
HEADING_STEP = math.radians(3)

SNEAK = "sneak"
RUN = "run"


@contextmanager
def timed_doors_as(world, closed):
    """しばらくの間、時間で開け閉めする扉の状態を closed にする（World はシミュレーターの状態どうしで共有しているので、
    終わったら元に戻す）。"""
    saved = world.timed_closed
    world.timed_closed = closed
    try:
        yield
    finally:
        world.timed_closed = saved


def guard_states(sim):
    """予測を使い回してよいかの判定に使う、警備員の位置・向き・状態。"""
    return tuple((g.x, g.y, g.heading, g.state) for g in sim.guards)


class Prediction:
    """超越だけ：前回の予測（判断は約1秒ごとに12秒先までの予測を使うので、まだ先にある11秒ぶんを使い回す）。

    使い回すのは、今の警備員の位置・向き・状態が、予測のその時刻の値とぴったり同じときだけ
    （見つかって追われた、巻き戻した、などで違っていれば作り直す）。紫はプレイヤーの位置を少し見て動くので、
    使い回した予測は作り直した予測と少し違うことがあるが、実行する前に本物どおりのシミュレーターで確かめる。
    """

    def __init__(self):
        self.frame = None  # samples[0] の時刻（コマ数）
        self.samples, self.times, self.doors, self.states = [], [], [], []
        self.tail = None  # 予測を続けるためのシミュレーター（次に記録するサンプルの時刻の状態）
        self.reused = 0
        self.rebuilt = 0

    def start(self, sim):
        s = sim.snapshot()
        s.cloak_timer = 1e9  # 透明：見られず、触れても捕まらない（足音も出さない＝止まっている）
        self.frame = frame_of(sim)
        self.samples, self.times, self.doors, self.states = [], [], [], []
        self.tail = s
        self.rebuilt += 1

    def can_reuse(self, sim):
        if self.frame is None:
            return False
        offset = frame_of(sim) - self.frame
        if offset < 0 or offset % SAMPLE_FRAMES:
            return False
        index = offset // SAMPLE_FRAMES
        return index < len(self.samples) and self.states[index] == guard_states(sim)

    def drop_until(self, sim):
        index = (frame_of(sim) - self.frame) // SAMPLE_FRAMES
        del self.samples[:index], self.times[:index], self.doors[:index], self.states[:index]
        self.frame = frame_of(sim)
        self.reused += 1

    def extend(self, count, world):
        s = self.tail
        with timed_doors_as(world, world.timed_closed):
            while len(self.samples) < count:
                self.samples.append([(g.x, g.y, g.heading) for g in s.guards])
                self.states.append(guard_states(s))
                self.times.append(s.elapsed)
                self.doors.append(s.world.timed_closed)
                for _ in range(SAMPLE_FRAMES):
                    s.step(frozenset())
                    if s.done:
                        break


def frame_of(sim):
    return round(sim.elapsed / DT)


def predict_guards(sim, slots=HORIZON_SLOTS, cache=None):
    """プレイヤーを透明にして止めたまま、警備員の位置と向きを SAMPLE_FRAMES ごとに記録する。
    (警備員の並びの列, 時刻の列, 閉まっている扉のマスの列) を返す。cache（Prediction）があれば使い回す。"""
    cache = cache or Prediction()
    if cache.can_reuse(sim):
        cache.drop_until(sim)
    else:
        cache.start(sim)
    count = slots * SLOT_SAMPLES + 1
    cache.extend(count, sim.world)
    return cache.samples[:count], cache.times[:count], cache.doors[:count]


# 計算を速くするための覚え書き。どれも「同じ入力なら同じ結果」になるものだけを覚えるので、結果は変わらない。
# - 警備員のいるマスの周りの床の一覧（壁は動かないので、一度作れば使い回せる）
# - 警備員1人ぶんの「見えるマス」「足音が聞こえるマス」（位置と向きが同じなら同じ）。
#   判断は1秒ごとに12秒先まで予定表を作り直すので、前回と重なる11秒ぶんはここから取り出せる
_FLOOR_NEAR = {}
_SEEN_MEMO = OrderedDict()
_HEARD_MEMO = OrderedDict()
MEMO_LIMIT = 30000  # 覚えておく数の上限。12秒×鬼20人ぶん（約7000）を数回分まとめて覚えられる数。多すぎるとメモリを使いすぎる


def floor_near(world, gx, gy, radius):
    """(gx, gy) のマスを中心に、半径 radius の四角の範囲にある床のマス（壁を除く）。"""
    r = int(math.ceil(radius))
    gcx, gcy = world_to_cell(gx, gy)
    key = (gcx, gcy, r, world.doors_closed, world.timed_closed)
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


def snap(value, step):
    return round(value / step) * step


def guard_seen(world, gx, gy, heading, cfg):
    """警備員1人から見えるマス：(忍び足で見つかるマス, 走っていると見つかるマス)。超越では位置と向きを丸めて計算する。"""
    if is_tuned(cfg):
        gx, gy, heading = snap(gx, POS_STEP), snap(gy, POS_STEP), snap(heading, HEADING_STEP)
    key = (gx, gy, heading, world.doors_closed, world.timed_closed)
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
    """警備員1人に、走ると足音を聞かれるマス（壁越しは届く距離が縮む）。超越では位置を丸めて計算する。"""
    if is_tuned(cfg):
        gx, gy = snap(gx, POS_STEP), snap(gy, POS_STEP)
    key = (gx, gy, world.doors_closed, world.timed_closed)
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


def camera_seen(world, camera, heading, cfg):
    """監視カメラ1台から見えるマス：(忍び足で映るマス, 走っていると映るマス)。"""
    key = ("camera", camera.x, camera.y, round(heading, 4), world.timed_closed)
    hit = _SEEN_MEMO.get(key)
    if hit is not None:
        _SEEN_MEMO.move_to_end(key)
        return hit
    run_view = CAMERA_VIEW_RANGE + VIEW_MARGIN
    sneak_view = CAMERA_VIEW_RANGE * cfg.sneak_view_rate + VIEW_MARGIN
    half = CAMERA_HALF_ANGLE + ANGLE_MARGIN
    sneak_seen, run_seen = [], []
    for cell in floor_near(world, camera.x, camera.y, run_view):
        tx, ty = cell[0] + 0.5, cell[1] + 0.5
        dist = math.hypot(tx - camera.x, ty - camera.y)
        if dist > run_view:
            continue
        if dist > 0.7:  # 体の大きさぶん、カメラのすぐそばは向きに関係なく危ないとみなす
            diff = (math.atan2(ty - camera.y, tx - camera.x) - heading + math.pi) % (2 * math.pi) - math.pi
            if abs(diff) > half:
                continue
        if world.has_line_of_sight(camera.x, camera.y, tx, ty):
            run_seen.append(cell)
            if dist <= sneak_view:
                sneak_seen.append(cell)
    return _remember(_SEEN_MEMO, key, (frozenset(sneak_seen), frozenset(run_seen)))


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


def sample_seen(sim, guards, t, closed, px, py):
    """1つのサンプル（時刻 t、閉まっている扉 closed）で見つかるマス。閉まっている扉のマスにも、いられない。"""
    world, cfg = sim.world, sim.difficulty
    with timed_doors_as(world, closed):
        sneak, run = visible_cells(world, guards, cfg, px, py)
        for camera in sim.cameras:
            if math.hypot(camera.x - px, camera.y - py) > RELEVANT_DISTANCE:
                continue
            cam_sneak, cam_run = camera_seen(world, camera, camera.heading_at(t), cfg)
            sneak = sneak | cam_sneak
            run = run | cam_run
    if closed:
        sneak = sneak | closed
        run = run | closed
    return sneak, run


def danger_schedule(sim, slots=HORIZON_SLOTS, cache=None):
    """区切りごとの (忍び足で危ないマス, 走ると危ないマス)。その区切りの間に一度でも危ないマスを全部含む。"""
    samples, times, doors = predict_guards(sim, slots, cache)
    px, py = sim.player.x, sim.player.y
    world, cfg = sim.world, sim.difficulty
    seen = [sample_seen(sim, guards, t, closed, px, py) for guards, t, closed in zip(samples, times, doors)]
    schedule = []
    for k in range(slots):
        first, last = k * SLOT_SAMPLES, (k + 1) * SLOT_SAMPLES
        sneak_unsafe, run_unsafe = set(), set()
        for i in range(first, last + 1):
            sneak_unsafe |= seen[i][0]
            run_unsafe |= seen[i][1]
        # 足音は区切りの最初と最後の並びで調べる（余裕を広めにとってある）。V（速度重視）のときは足音を気にしない
        if not enabled("V"):
            for i in (first, last):
                with timed_doors_as(world, doors[i]):
                    run_unsafe |= audible_cells(world, samples[i], cfg, px, py)
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
    if enabled("F2"):  # 走るときの斜め（1,1）と桂馬（2,1）。角を削って通るので、途中のマスも空いていること
        for dx in (1, -1):
            for dy in (1, -1):
                side_x, side_y, diag = (cx + dx, cy), (cx, cy + dy), (cx + dx, cy + dy)
                if world.is_wall(*side_x) or world.is_wall(*side_y) or world.is_wall(*diag):
                    continue
                yield diag, (side_x, side_y), RUN
                for far, beside in (((cx + 2 * dx, cy + dy), (cx + 2 * dx, cy)), ((cx + dx, cy + 2 * dy), (cx, cy + 2 * dy))):
                    if not world.is_wall(*far):
                        yield far, (side_x, side_y, diag), RUN


def plan_path(world, start, schedule, field, forbidden=frozenset(), floor_value=0.0):
    """区切りごとに動きを選び、見つからない（走るときは足音も聞かれない）マスだけをたどる。

    できるだけ先の区切りまで見つからずにいられ、その途中で目標までの距離（field）が一番小さくなる経路を返す
    （区切りごとの (マス, "sneak" か "run") の列）。最初の区切りから安全なマスがなければ None。
    floor_value: 距離がこれ以下は同じとみなす（最後のアイテムの手前で待つとき用）。
    """
    def value(cell):
        return max(field.dist.get(cell, math.inf), floor_value)

    with timed_doors_as(world, frozenset()):  # 扉は開いているものとして動きを考え、閉まる時刻は予定表で避ける
        return _plan_path(world, start, schedule, value, forbidden)


def _plan_path(world, start, schedule, value, forbidden):
    early = enabled("C") or enabled("V")
    prefer = RUN if enabled("F3") else SNEAK  # 同じくらい近づけるときに選ぶ歩き方
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
                        v == best_along[n] and ((early and r < best_reached[n]) or (not early and mode == prefer))):
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
    if early or enabled("F4"):  # F4：目標に一番近づける経路のうち、一番早く届くもの
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
