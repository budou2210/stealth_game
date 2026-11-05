"""未来を読みながら動くボット。

- 0.4秒を1区切りとして、「進む／待つ／走る／離れる」の4つの動きを組み合わせた流れを、
  シミュレーターで1.6秒先まで試す。よさそうな流れだけを残しながら探し（ビームサーチ）、
  一番よい流れの最初の動きを実行する。これを0.4秒ごとにくり返す。
  「警備員が向こうを向くまで待ってから進む」のような、タイミングを計る動きが見つかる。
- 8個目（最後のアイテム）を拾う前に、拾ってから出口に着くまでの競走を最後まで試す。
  勝てると分かったら、その試した入力をそのまま実行する（シミュレーターは本物と同じ動きをするので確実）。
  勝てなければ、少し離れた見つからない場所で待ちながら試し直す（近くで待つと紫が集まってくる）。
- 捕まったり行き詰まったりしたら、少し前に保存した状態へ巻き戻してやり直す。
  やり直すたびに「少し待ってから動く」「目標のアイテムの順番を入れ替える」などで、前と違う動きをする。
  最後に残る記録は、成功した流れだけになる。
- 目標のアイテムに近づけない状態が続いたら、別のアイテムを先に取りに行く。
"""

import heapq
import math
import random
import time

from stealth_game.constants import PLAYER_RADIUS
from stealth_game.grid import manhattan, world_to_cell
from stealth_game.guard import Guard
from stealth_game.layout import EXIT_CELL

from .options import enabled
from .sim import DT
from .spacetime import RUN, SAMPLE_FRAMES, SLOT_SAMPLES, SNEAK, danger_schedule, plan_path

SEGMENT_FRAMES = 12  # 1区切りのコマ数（0.4秒）。この間は同じ動きを続ける
DEPTH = 6  # 何区切り先まで試すか（2.4秒）
BEAM = 4  # 区切りごとに残す流れの数
RUN_CLEARANCE = 1.0  # 足音の届く距離＋これ以内に警備員がいるときは走らない
DANGER_WEIGHT = 6.0  # 経路で、危険度の高いマスをどれだけ避けるか
STAGING_DISTANCE = 2.5  # 最後のアイテムの手前で待つ距離（予備の探索方法で使う。距離の地図の値）
LAST_ITEM_WAIT_DISTANCE = 6.0  # 最後のアイテムに、これより近づいて待たない（紫が集まってくるので）
LAST_ITEM_KEEP_OUT = 2  # 最後のアイテムから、この歩数以内のマスには、競走を始めるまで入らない
RACE_LIMIT_FRAMES = 30 * 40  # 競走を試すときの上限（40秒）
STUCK_SECONDS = 120  # この秒数アイテムを拾えなければ、その配置はあきらめる
TIME_LIMIT_SECONDS = 900  # ゲーム内の時間の上限
CHECKPOINT_SECONDS = 5.0  # この秒数ごとに状態を保存する（巻き戻し用）
REWIND_MARGIN = 3.0  # 捕まったら、最初に見つかった時刻のこれだけ前より前の保存点へ戻る
STUCK_REWIND = 30.0  # 行き詰まったら、これだけ前より前の保存点へ戻る
MAX_TRIES_PER_CHECKPOINT = 4  # 同じ保存点からやり直す回数の上限（超えたらもっと前へ戻る）
MAX_REWINDS = 60  # 1回の挑戦で巻き戻せる回数の上限
NO_PROGRESS_SECONDS = 25.0  # 目標のアイテムにこの秒数近づけなければ、別のアイテムを先にする
EXECUTE_SLOTS = 2  # 時間と場所の経路のうち、確かめてから実行する区切りの数（1秒）
FUTURE_CHECK_SLOTS = 8  # 実行した後も、この区切り数（4秒）は逃げ続けられることを確かめる
SLOT_FRAMES = SAMPLE_FRAMES * SLOT_SAMPLES
SMOOTH_AHEAD = 2 if enabled("S2") else 1  # 滑らかに動くとき、経路の何区切り先のマスまで近道してよいか（2は斜めの近道が増えるが、予定とずれやすい）
VALID_ALERT = 0.5  # 確かめるとき、警戒度がこれを超えたら実行しない

# 点数の重み
SPOTTED_PENALTY = 80.0  # 見つかった（追跡が始まった）
HEARD_PENALTY = 15.0  # 足音を聞かれて、近くを調べに来られた（1人ごと）
ALERT_PENALTY = 12.0  # 警戒度が ALERT_FREE を超えた分
ALERT_FREE = 0.35  # この警戒度までは、すぐ下がるので気にしない
COLLECT_BONUS = 40.0
CLOSE_DISTANCE = 4.5  # 警備員にこれより近づくと減点する（振り向かれたら終わりなので）
CLOSE_PENALTY = 1.5  # 1秒・1マスあたりの減点

DIRECTIONS = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
MOVES = ("follow", "hold", "run", "evade")


def keys_for(direction, sneak):
    dx, dy = direction
    keys = set()
    if dx > 0:
        keys.add("right")
    elif dx < 0:
        keys.add("left")
    if dy > 0:
        keys.add("up")
    elif dy < 0:
        keys.add("down")
    if sneak:
        keys.add("sneak")
    return frozenset(keys)


class Field:
    """target までの「危険度で重みをつけた距離」を全部のマスについて持つ（プレイヤーが歩けるマスだけ）。"""

    def __init__(self, world, target, danger_map, weight=DANGER_WEIGHT):
        self.world = world
        self.target = target
        self.dist = {target: 0.0}
        heap = [(0.0, target)]
        while heap:
            d, cell = heapq.heappop(heap)
            if d > self.dist[cell]:
                continue
            for nx, ny in ((cell[0] + 1, cell[1]), (cell[0] - 1, cell[1]), (cell[0], cell[1] + 1), (cell[0], cell[1] - 1)):
                if world.is_wall(nx, ny):
                    continue
                nd = d + 1.0 + weight * danger_map.danger((nx, ny))
                if nd < self.dist.get((nx, ny), math.inf):
                    self.dist[(nx, ny)] = nd
                    heapq.heappush(heap, (nd, (nx, ny)))

    def value(self, x, y):
        return self.dist.get(world_to_cell(x, y), math.inf)

    def walkable_step(self, cx, cy, dx, dy):
        if self.world.is_wall(cx + dx, cy + dy):
            return False
        return not (dx and dy and (self.world.is_wall(cx + dx, cy) or self.world.is_wall(cx, cy + dy)))

    def direction(self, x, y):
        """(x, y) から目標へ向かう向き（-1, 0, 1 の組）。一番値の小さい隣のマスの中心へ向かう。"""
        cx, cy = world_to_cell(x, y)
        best, best_cell = self.dist.get((cx, cy), math.inf), (cx, cy)
        for dx, dy in DIRECTIONS:
            if (dx or dy) and self.walkable_step(cx, cy, dx, dy):
                v = self.dist.get((cx + dx, cy + dy), math.inf)
                if v < best:
                    best, best_cell = v, (cx + dx, cy + dy)
        return toward(x, y, best_cell)


def toward(x, y, cell):
    ex, ey = cell[0] + 0.5 - x, cell[1] + 0.5 - y
    return (int(ex > 0.12) - int(ex < -0.12), int(ey > 0.12) - int(ey < -0.12))


def threat(sim):
    """今の危なさ：(見つかったか, 一番高い警戒度, プレイヤーの近くを調べに来ている警備員の数)。"""
    spotted = any(g.state in (Guard.SPOTTED, Guard.CHASE) and not g.hunting for g in sim.guards)
    alert = max(g.alert for g in sim.guards)
    here = world_to_cell(sim.player.x, sim.player.y)
    searching = sum(
        1 for g in sim.guards
        if g.state == Guard.SEARCH and g.last_known is not None and manhattan(g.last_known, here) <= 3
    )
    return spotted, alert, searching


def can_run(sim):
    """足音を聞かれる距離に警備員がいなければ走ってよい（V＝速度重視のときは、いつでも走ってよい）。"""
    if enabled("V"):
        return True
    p = sim.player
    limit = sim.difficulty.hear_radius + RUN_CLEARANCE
    return all(g.distance_to(p.x, p.y) > limit for g in sim.guards)


def evade_direction(sim, field):
    """一番近い警備員から離れる向き（歩けるマスの中で、離れる向きに一番近いもの）。"""
    p = sim.player
    g = min(sim.guards, key=lambda g: g.distance_to(p.x, p.y))
    ax, ay = p.x - g.x, p.y - g.y
    norm = math.hypot(ax, ay) or 1.0
    cx, cy = world_to_cell(p.x, p.y)
    best, best_dir = -math.inf, (0, 0)
    for dx, dy in DIRECTIONS:
        if (dx or dy) and field.walkable_step(cx, cy, dx, dy):
            score = (dx * ax + dy * ay) / (norm * math.hypot(dx, dy))
            if score > best:
                best, best_dir = score, toward(p.x, p.y, (cx + dx, cy + dy))
    return best_dir


def move_keys(sim, move, field):
    """その動きで、今のコマに押すキー。"""
    if move == "hold":
        return frozenset({"sneak"})
    if move == "evade":
        return keys_for(evade_direction(sim, field), sneak=True)
    return keys_for(field.direction(sim.player.x, sim.player.y), sneak=(move != "run"))


def forbidden_items(bot, forbidden_cells):
    return [i for i, c in enumerate(bot.sim.item_cells) if c in forbidden_cells]


class Node:
    """探索中の1つの流れ（シミュレーターの状態と、ここまでの点数）。"""

    __slots__ = ("sim", "first", "penalty", "collected", "spotted", "dead", "heard")

    def __init__(self, sim, first=None, penalty=0.0, collected=0, spotted=False, dead=False, heard=frozenset()):
        self.sim = sim
        self.first = first
        self.penalty = penalty
        self.collected = collected
        self.spotted = spotted
        self.dead = dead
        self.heard = heard


class Bot:
    def __init__(self, sim, danger_map, variant=0):
        """variant: 0 なら標準の動き。1以上なら、経路の重みやアイテムの順番を少しだけ変えた動きにする
        （同じ配置を何通りも試して、一番速いクリアを残すため）。"""
        self.sim = sim
        self.danger_map = danger_map
        self.world = sim.world
        self.variant = variant
        self.rng = random.Random(variant * 1000003 + sim.seed)  # ゲームの乱数とは別（ボットの判断のゆらぎ用）
        self.danger_weight = DANGER_WEIGHT * (0.5 + self.rng.random()) if variant else DANGER_WEIGHT
        self.log = []  # 実行した入力（1コマずつ）
        self.visited = []
        self.fail_cell = None
        self.fields = {}
        self.order = self.plan_order()
        self.last_collect_time = 0.0
        self.race_keys = None  # 勝てると分かった競走の入力（あれば、これをそのまま実行する）
        self.stats = {"spacetime": 0, "beam": 0}  # どちらの方法で動いたかの回数
        self.spotted_time = None  # 今の流れで最初に見つかった時刻
        self.hold_slots = 0  # 巻き戻した直後に、その場で待つ区切りの数（前と違う動きにするため）
        self.progress = (None, math.inf, 0.0)  # (目標のアイテム, 一番近づいた距離, そのときの時刻)
        self.checkpoints = []
        self.failures = []  # 巻き戻す前に見つかった（捕まった）マス（危険度の地図に使う）
        self.rewinds = 0

    # --- 経路 -----------------------------------------------------------
    def field(self, target):
        if target not in self.fields:
            self.fields[target] = Field(self.world, target, self.danger_map, self.danger_weight)
        return self.fields[target]

    def plan_order(self):
        """アイテムを集める順番。出口に一番近いアイテムを最後に残し、残りは近い順にたどる。"""
        items = list(range(len(self.sim.item_cells)))
        exit_field = self.field(EXIT_CELL)
        last = min(items, key=lambda i: exit_field.dist.get(self.sim.item_cells[i], math.inf))
        rest = [i for i in items if i != last]
        order = []
        here = world_to_cell(self.sim.player.x, self.sim.player.y)
        while rest:
            nxt = min(rest, key=lambda i: self.field(self.sim.item_cells[i]).dist.get(here, math.inf))
            order.append(nxt)
            rest.remove(nxt)
            here = self.sim.item_cells[nxt]
        if enabled("D"):
            order = self.shorten_order(order, last)
        if self.variant:  # ゆらぎ：となり合う2つを、ときどき入れ替える
            for k in range(len(order) - 1):
                if self.rng.random() < 0.25:
                    order[k], order[k + 1] = order[k + 1], order[k]
        return order + [last]

    def route_length(self, order, last):
        """スタート → order の順 → last → 出口 の道のり（危険度の重みつき）。"""
        cells = [world_to_cell(self.sim.player.x, self.sim.player.y)]
        cells += [self.sim.item_cells[i] for i in order + [last]] + [EXIT_CELL]
        return sum(self.field(b).dist.get(a, math.inf) for a, b in zip(cells, cells[1:]))

    def shorten_order(self, order, last):
        """順番の一部を逆向きにする組み替え（2-opt）を、道のりが短くならなくなるまでくり返す。"""
        best = list(order)
        best_len = self.route_length(best, last)
        improved = True
        while improved:
            improved = False
            for a in range(len(best) - 1):
                for b in range(a + 1, len(best)):
                    cand = best[:a] + best[a:b + 1][::-1] + best[b + 1:]
                    length = self.route_length(cand, last)
                    if length < best_len - 1e-9:
                        best, best_len, improved = cand, length, True
        return best

    def remaining(self):
        return [i for i in self.order if i not in self.sim.items_collected]

    def demote_target(self):
        """今の目標のアイテムを、次のアイテムの後ろに回す（最後の2個なら、どちらを最後にするかが入れ替わる）。"""
        remaining = self.remaining()
        if len(remaining) < 2:
            return
        first, second = remaining[0], remaining[1]
        self.order.remove(first)
        self.order.insert(self.order.index(second) + 1, first)
        self.progress = (None, math.inf, self.sim.elapsed)

    def keep_out_cells(self, item_cell):
        """競走を始めるまで入らないマス（最後のアイテムの周り）。"""
        x, y = item_cell
        r = LAST_ITEM_KEEP_OUT
        return frozenset((x + dx, y + dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1) if abs(dx) + abs(dy) <= r)

    # --- 未来を試す -----------------------------------------------------
    def progress_value(self, sim, field, staging):
        v = field.value(sim.player.x, sim.player.y)
        return max(v, STAGING_DISTANCE) if staging else v

    def expand(self, node, move, field, avoid_item, staging, known):
        """node から move を1区切り続けた先の流れ。"""
        s = node.sim.snapshot()
        child = Node(s, node.first or move, node.penalty, node.collected, node.spotted, False, node.heard)
        before = len(s.items_collected)
        heard = set(node.heard)
        for _ in range(SEGMENT_FRAMES):
            s.step(move_keys(s, move, field))
            if s.state == "lose" or (avoid_item is not None and avoid_item in s.items_collected):
                child.dead = True  # 捕まった／最後のアイテムを競走の準備なしに拾ってしまった
                return child
            spotted, alert, _ = threat(s)
            if spotted:
                child.spotted = True
            if alert > ALERT_FREE:
                child.penalty += ALERT_PENALTY * (alert - ALERT_FREE) / SEGMENT_FRAMES
            for g in s.guards:
                d = g.distance_to(s.player.x, s.player.y)
                if d < CLOSE_DISTANCE:
                    child.penalty += CLOSE_PENALTY * (CLOSE_DISTANCE - d) * DT
            here = world_to_cell(s.player.x, s.player.y)
            for g in s.guards:  # 新しくプレイヤーの近くを調べに来た警備員（足音を聞かれた）
                if g.state == Guard.SEARCH and g.last_known is not None and g.last_known != known.get(g.spawn) \
                        and manhattan(g.last_known, here) <= 4:
                    heard.add(g.spawn)
        child.heard = frozenset(heard)
        child.collected += len(s.items_collected) - before
        return child

    def score(self, node, field, start_value, staging):
        if node.dead:
            return -1000.0
        progress = start_value - self.progress_value(node.sim, field, staging)
        if math.isinf(progress):
            progress = 0.0
        return (progress + COLLECT_BONUS * node.collected - node.penalty
                - SPOTTED_PENALTY * node.spotted - HEARD_PENALTY * len(node.heard))

    def search(self, field, avoid_item=None, staging=False):
        """ビームサーチで一番よい流れを探し、その最初の動きを返す。"""
        root = Node(self.sim)
        known = {g.spawn: g.last_known for g in self.sim.guards}
        start_value = self.progress_value(self.sim, field, staging)
        beam = [root]
        best_first, best_score = "hold", -math.inf
        for _ in range(DEPTH):
            children = []
            for node in beam:
                if node.dead:
                    continue
                for move in MOVES:
                    if move == "run" and not can_run(node.sim):
                        continue
                    child = self.expand(node, move, field, avoid_item, staging, known)
                    children.append((self.score(child, field, start_value, staging), id(child), child))
            if not children:
                break
            children.sort(key=lambda c: c[0], reverse=True)
            beam = [c[2] for c in children[:BEAM]]
            best_score, best_first = children[0][0], children[0][2].first
        return best_first

    def try_race(self, last_index):
        """最後のアイテムを拾って出口まで走る入力を試す。勝てればその入力の列を返す。"""
        s = self.sim.snapshot()
        item_field = self.field(self.sim.item_cells[last_index])
        exit_field = self.field(EXIT_CELL)
        keys_log = []
        for _ in range(RACE_LIMIT_FRAMES):
            target = exit_field if last_index in s.items_collected else item_field
            keys = keys_for(target.direction(s.player.x, s.player.y), sneak=False)
            s.step(keys)
            keys_log.append(keys)
            if s.state == "win":
                return keys_log
            if s.state == "lose":
                return None
        return None

    # --- 時間と場所の経路 -----------------------------------------------
    def spacetime_keys(self, field, forbidden=frozenset(), floor_value=0.0):
        """予定表から経路を探し、最初の数区切りぶんの入力を本物どおりに確かめてから返す。

        確かめる内容は2つ。①その間に見つからない ②実行し終えた後も、FUTURE_CHECK_SLOTS 区切りは
        逃げ続けられる経路がある（紫がプレイヤーに寄ってくるので、「1秒後は無事でも次で詰む」ことがある）。
        1秒ぶんでだめなら、0.5秒ぶんで同じことを確かめる。
        """
        here = world_to_cell(self.sim.player.x, self.sim.player.y)
        path = plan_path(self.world, here, danger_schedule(self.sim), field, forbidden, floor_value)
        if not path:
            return None
        # まずは滑らかな動き方（止まらずに進み、斜めに近道する）で試し、だめなら経路どおりの動き方で試す
        for smooth in (True, False):
            for slots in (EXECUTE_SLOTS, 1):
                result = self.check_cells(path[:slots], forbidden, following=path[slots:], smooth=smooth)
                if result is None:
                    continue
                keys_log, after = result
                if after.done:
                    return keys_log
                after_here = world_to_cell(after.player.x, after.player.y)
                future = plan_path(self.world, after_here, danger_schedule(after, FUTURE_CHECK_SLOTS),
                                   field, forbidden, floor_value)
                if future and len(future) >= FUTURE_CHECK_SLOTS:
                    return keys_log
        return None

    def steer(self, s, path, i, forbidden):
        """滑らかに動くときの、今向かうマスと走るかどうか。

        経路の i 番目の区切りのマスへ向かう代わりに、その先（SMOOTH_AHEAD 区切り先まで）のマスへ
        壁に当たらずまっすぐ行けるなら、そちらへ向かう。こうすると、マスの中心で止まらずに進み続け、
        「右・上・右・上」の階段は斜めの直進になる。経路が「その場で待つ」ところより先へは行かない。
        """
        px, py = s.player.x, s.player.y
        best = i
        for j in range(i + 1, min(i + 1 + SMOOTH_AHEAD, len(path))):
            if path[j][0] == path[j - 1][0]:
                break  # 経路はここで待つ
            if not self.straight_clear(px, py, path[j][0], forbidden):
                break
            best = j
        run = path[i][1] == RUN  # 歩き方は今の区切りに従う（先が忍び足でも、今の区切りが走るなら走る）
        return path[best][0], run

    def straight_clear(self, x, y, cell, forbidden):
        """(x, y) から cell の中心まで、体が壁に当たらず、入ってはいけないマスも通らずに、まっすぐ行けるか。"""
        tx, ty = cell[0] + 0.5, cell[1] + 0.5
        dist = math.hypot(tx - x, ty - y)
        steps = max(1, int(dist / 0.2))
        for k in range(1, steps + 1):
            cx, cy = x + (tx - x) * k / steps, y + (ty - y) * k / steps
            if self.world.is_blocked(cx, cy, PLAYER_RADIUS + 0.05) or world_to_cell(cx, cy) in forbidden:
                return False
        return True

    def check_cells(self, steps, forbidden, following=(), smooth=False):
        """区切りごとの (マス, 歩き方) の列を、本物どおりに実行してみる。見つからなければ (入力の列, 実行後の状態)。

        following: その先の経路（滑らかに動くとき、次へ向かうために見る）。smooth: 滑らかに動くか。
        """
        s = self.sim.snapshot()
        known = {g.spawn: g.last_known for g in s.guards}
        avoid = forbidden_items(self, forbidden)
        path = list(steps) + list(following)
        keys_log = []
        for i, (cell, mode) in enumerate(steps):
            for _ in range(SLOT_FRAMES):
                if smooth:
                    target, run = self.steer(s, path, i, forbidden)
                else:
                    target, run = cell, mode == RUN
                keys = keys_for(toward(s.player.x, s.player.y, target), sneak=not run)
                s.step(keys)
                keys_log.append(keys)
                spotted, alert, _ = threat(s)
                if s.state == "lose" or spotted or alert > VALID_ALERT:
                    return None
                if any(i in s.items_collected for i in avoid):
                    return None
                here = world_to_cell(s.player.x, s.player.y)
                for g in ([] if enabled("V") else s.guards):  # V（速度重視）のときは、足音を聞かれてもよい
                    if (g.state == Guard.SEARCH and g.last_known is not None
                            and g.last_known != known.get(g.spawn) and manhattan(g.last_known, here) <= 4):
                        return None  # 足音を聞かれた
                if s.done:
                    return keys_log, s
        return keys_log, s

    # --- 1回の判断 ------------------------------------------------------
    def decide(self):
        """次に押す入力の列を返す。競走に勝てる入力が見つかったら None（race_keys に入れる）。"""
        remaining = self.remaining()
        if not remaining:
            return self.escape_keys()
        self.check_progress()
        target_index = remaining[0]
        target_cell = self.sim.item_cells[target_index]
        field = self.field(target_cell)
        last = len(remaining) == 1
        if last:
            race = self.try_race(target_index)  # どこにいても、今走れば勝てるかを試す
            if race is not None:
                self.race_keys = race
                return None
        forbidden = self.keep_out_cells(target_cell) if last else frozenset()
        if self.hold_slots > 0:  # 巻き戻した直後は、見つからなければ少しその場で待つ
            self.hold_slots -= 1
            here = world_to_cell(self.sim.player.x, self.sim.player.y)
            result = self.check_cells([(here, SNEAK)], forbidden)
            if result is not None:
                return result[0]
        if last:
            keys = self.spacetime_keys(field, forbidden=forbidden, floor_value=LAST_ITEM_WAIT_DISTANCE)
        else:
            keys = self.spacetime_keys(field)
        if keys:
            self.stats["spacetime"] += 1
            return keys
        self.stats["beam"] += 1
        if last:
            return self.beam_keys(self.search(field, avoid_item=target_index, staging=True), field)
        return self.beam_keys(self.search(field), field)

    def escape_keys(self):
        """競走を経ずに8個とも集めてしまったとき（予備の探索方法でたまたま拾ったなど）：出口へ走る。

        出口まで逃げ切れるなら、その入力をそのまま実行する。逃げ切れなくても出口へ走り、捕まったら巻き戻しに任せる。
        """
        exit_field = self.field(EXIT_CELL)
        s = self.sim.snapshot()
        keys_log = []
        for _ in range(RACE_LIMIT_FRAMES):
            keys = keys_for(exit_field.direction(s.player.x, s.player.y), sneak=False)
            s.step(keys)
            keys_log.append(keys)
            if s.done:
                break
        if s.state == "win":
            self.race_keys = keys_log
            return None
        return keys_log[:SEGMENT_FRAMES]

    def check_progress(self):
        """目標のアイテムに長く近づけていなければ、別のアイテムを先にする。"""
        remaining = self.remaining()
        target = remaining[0]
        value = self.field(self.sim.item_cells[target]).value(self.sim.player.x, self.sim.player.y)
        best_target, best_value, since = self.progress
        if target != best_target or value < best_value - 0.5:
            self.progress = (target, value, self.sim.elapsed)
        elif len(remaining) > 1 and self.sim.elapsed - since > NO_PROGRESS_SECONDS:
            self.demote_target()

    def beam_keys(self, move, field):
        """ビームサーチで選んだ動きを1区切りぶん、入力の列にする（実際の状態に合わせて1コマずつ決める）。"""
        s = self.sim.snapshot()
        keys_log = []
        for _ in range(SEGMENT_FRAMES):
            keys = move_keys(s, move, field)
            s.step(keys)
            keys_log.append(keys)
            if s.done:
                break
        return keys_log

    def apply(self, keys):
        before = len(self.sim.items_collected)
        self.sim.step(keys)
        self.log.append(keys)
        self.visited.append(world_to_cell(self.sim.player.x, self.sim.player.y))
        if self.fail_cell is None and threat(self.sim)[0]:
            self.fail_cell = self.visited[-1]  # 最初に見つかった場所
            self.spotted_time = self.sim.elapsed
        if len(self.sim.items_collected) > before:
            self.last_collect_time = self.sim.elapsed

    # --- 巻き戻し -------------------------------------------------------
    def save_checkpoint(self):
        self.checkpoints.append({
            "time": self.sim.elapsed,
            "sim": self.sim.snapshot(),
            "log": len(self.log),
            "visited": len(self.visited),
            "order": list(self.order),
            "last_collect_time": self.last_collect_time,
            "progress": self.progress,
            "tries": 0,
        })

    def rewind(self, failure):
        """failure（"lose" か "stuck"）の前の保存点へ戻る。戻れたら True。"""
        if self.rewinds >= MAX_REWINDS:
            return False
        if failure == "lose":
            target = (self.spotted_time if self.spotted_time is not None else self.sim.elapsed) - REWIND_MARGIN
        else:
            target = self.sim.elapsed - STUCK_REWIND
        while self.checkpoints:
            cp = self.checkpoints[-1]
            if cp["time"] <= target and cp["tries"] < MAX_TRIES_PER_CHECKPOINT:
                break
            self.checkpoints.pop()  # 失敗した流れの保存点と、やり直し尽くした保存点は捨てる
        else:
            return False
        if self.fail_cell is not None:
            self.failures.append(self.fail_cell)
        self.sim = cp["sim"].snapshot()  # 保存点そのものは、次のやり直し用に残しておく
        del self.log[cp["log"]:]
        del self.visited[cp["visited"]:]
        self.order = list(cp["order"])
        self.last_collect_time = cp["last_collect_time"]
        self.progress = cp["progress"]
        self.fail_cell = None
        self.spotted_time = None
        self.race_keys = None
        cp["tries"] += 1
        self.hold_slots = cp["tries"]  # やり直すたびに、少しずつ長く待ってから動く
        if cp["tries"] % 2 == 0:
            self.demote_target()  # 2回に1回は、アイテムの順番も変える
        self.rewinds += 1
        return True

    def play(self, on_progress=None, max_compute_seconds=None):
        """1回の挑戦を最後まで進め、結果を返す（捕まったり行き詰まったりしたら巻き戻してやり直す）。

        max_compute_seconds: 計算時間の上限（秒）。超えたらそこで打ち切る（結果は "time_limit"）。
        """
        outcome = None
        best_items = 0
        started = time.perf_counter()
        self.save_checkpoint()
        while True:
            sim = self.sim
            best_items = max(best_items, len(sim.items_collected))
            if sim.state == "win":
                outcome = "win"
                break
            failure = None
            if sim.state == "lose":
                failure = "lose"
            elif sim.elapsed - self.last_collect_time > STUCK_SECONDS:
                failure = "stuck"
            elif sim.elapsed > TIME_LIMIT_SECONDS or (
                    max_compute_seconds is not None and time.perf_counter() - started > max_compute_seconds):
                outcome = "time_limit"
                break
            if failure:
                if not self.rewind(failure):
                    outcome = failure
                    break
                continue
            if sim.elapsed >= self.checkpoints[-1]["time"] + CHECKPOINT_SECONDS:
                self.save_checkpoint()
            if self.race_keys:
                for keys in self.race_keys:
                    self.apply(keys)
                    if self.sim.done:
                        break
                self.race_keys = None
                continue
            keys_log = self.decide()
            if keys_log is None:
                continue  # 競走に勝てる入力が見つかった（次のループで実行する）
            for keys in keys_log:
                self.apply(keys)
                if self.sim.done:
                    break
            if on_progress:
                on_progress(self, keys_log)
        sim = self.sim
        if outcome != "win" and self.fail_cell is not None:
            self.failures.append(self.fail_cell)
        fail_cell = None
        if outcome != "win" and self.visited:
            fail_cell = self.fail_cell or self.visited[-1]
        return {
            "seed": sim.seed,
            "outcome": outcome,
            "time": round(sim.elapsed, 2),
            "items": len(sim.items_collected),
            "best_items": best_items,
            "fail_cell": list(fail_cell) if fail_cell else None,
            "fail_cells": [list(c) for c in self.failures],
            "rewinds": self.rewinds,
            "frames": len(self.log),
            "moves": dict(self.stats),
        }


def encode_keys(log):
    """入力の記録を「同じ入力が何コマ続いたか」の形に縮める。"""
    out = []
    for keys in log:
        k = "+".join(sorted(keys))
        if out and out[-1][0] == k:
            out[-1][1] += 1
        else:
            out.append([k, 1])
    return out


def decode_keys(encoded):
    log = []
    for k, n in encoded:
        keys = frozenset(k.split("+")) if k else frozenset()
        log.extend([keys] * n)
    return log


__all__ = ["Bot", "Field", "encode_keys", "decode_keys", "DT"]
