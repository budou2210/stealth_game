"""未来を読みながら動くボット。

- 0.4秒を1区切りとして、「進む／待つ／走る／離れる」の4つの動きを組み合わせた流れを、
  シミュレーターで1.6秒先まで試す。よさそうな流れだけを残しながら探し（ビームサーチ）、
  一番よい流れの最初の動きを実行する。これを0.4秒ごとにくり返す。
  「警備員が向こうを向くまで待ってから進む」のような、タイミングを計る動きが見つかる。
- 8個目（最後のアイテム）を拾う前に、拾ってから出口に着くまでの競走を最後まで試す。
  勝てると分かったら、その試した入力をそのまま実行する（シミュレーターは本物と同じ動きをするので確実）。
  勝てなければ、手前の見つからない場所で待ちながら試し直す。
"""

import heapq
import math

from stealth_game.grid import manhattan, world_to_cell
from stealth_game.guard import Guard
from stealth_game.layout import EXIT_CELL

from .sim import DT
from .spacetime import SAMPLE_FRAMES, SLOT_SAMPLES, danger_schedule, plan_path

SEGMENT_FRAMES = 12  # 1区切りのコマ数（0.4秒）。この間は同じ動きを続ける
DEPTH = 6  # 何区切り先まで試すか（2.4秒）
BEAM = 4  # 区切りごとに残す流れの数
RUN_CLEARANCE = 1.0  # 足音の届く距離＋これ以内に警備員がいるときは走らない
DANGER_WEIGHT = 6.0  # 経路で、危険度の高いマスをどれだけ避けるか
STAGING_DISTANCE = 2.5  # 最後のアイテムの手前で待つ距離（距離の地図の値）
RACE_CHECK_DISTANCE = 6.0  # 最後のアイテムまでこの距離以内なら、競走を試す
RACE_LIMIT_FRAMES = 30 * 40  # 競走を試すときの上限（40秒）
STUCK_SECONDS = 120  # この秒数アイテムを拾えなければ、その配置はあきらめる
TIME_LIMIT_SECONDS = 900
EXECUTE_SLOTS = 2  # 時間と場所の経路のうち、確かめてから実行する区切りの数（1秒）
FUTURE_CHECK_SLOTS = 8  # 実行した後も、この区切り数（4秒）は逃げ続けられることを確かめる
SLOT_FRAMES = SAMPLE_FRAMES * SLOT_SAMPLES
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
    """足音を聞かれる距離に警備員がいなければ走ってよい。"""
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
    def __init__(self, sim, danger_map):
        self.sim = sim
        self.danger_map = danger_map
        self.world = sim.world
        self.log = []  # 実行した入力（1コマずつ）
        self.visited = []
        self.fail_cell = None
        self.fields = {}
        self.order = self.plan_order()
        self.last_collect_time = 0.0
        self.race_keys = None  # 勝てると分かった競走の入力（あれば、これをそのまま実行する）
        self.stats = {"spacetime": 0, "beam": 0}  # どちらの方法で動いたかの回数

    # --- 経路 -----------------------------------------------------------
    def field(self, target):
        if target not in self.fields:
            self.fields[target] = Field(self.world, target, self.danger_map)
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
        return order + [last]

    def remaining(self):
        return [i for i in self.order if i not in self.sim.items_collected]

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
        for slots in (EXECUTE_SLOTS, 1):
            result = self.check_cells(path[:slots], forbidden)
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

    def check_cells(self, cells, forbidden):
        """区切りごとのマスの列を、本物どおりに実行してみる。見つからなければ (入力の列, 実行後の状態)。"""
        s = self.sim.snapshot()
        known = {g.spawn: g.last_known for g in s.guards}
        avoid = forbidden_items(self, forbidden)
        keys_log = []
        for cell in cells:
            for _ in range(SLOT_FRAMES):
                keys = keys_for(toward(s.player.x, s.player.y, cell), sneak=True)
                s.step(keys)
                keys_log.append(keys)
                spotted, alert, _ = threat(s)
                if s.state == "lose" or spotted or alert > VALID_ALERT:
                    return None
                if any(i in s.items_collected for i in avoid):
                    return None
                here = world_to_cell(s.player.x, s.player.y)
                for g in s.guards:
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
        target_index = remaining[0]
        target_cell = self.sim.item_cells[target_index]
        field = self.field(target_cell)
        if len(remaining) > 1:
            keys = self.spacetime_keys(field)
            if keys:
                self.stats["spacetime"] += 1
                return keys
            self.stats["beam"] += 1
            return self.beam_keys(self.search(field), field)
        if field.value(self.sim.player.x, self.sim.player.y) <= RACE_CHECK_DISTANCE:
            race = self.try_race(target_index)
            if race is not None:
                self.race_keys = race
                return None
        keys = self.spacetime_keys(field, forbidden=frozenset({target_cell}), floor_value=STAGING_DISTANCE)
        if keys:
            self.stats["spacetime"] += 1
            return keys
        self.stats["beam"] += 1
        return self.beam_keys(self.search(field, avoid_item=target_index, staging=True), field)

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
        if len(self.sim.items_collected) > before:
            self.last_collect_time = self.sim.elapsed

    def play(self, on_progress=None):
        """1回の挑戦を最後まで進め、結果を返す。"""
        sim = self.sim
        outcome = None
        while not sim.done:
            if sim.elapsed > TIME_LIMIT_SECONDS:
                outcome = "time_limit"
                break
            if sim.elapsed - self.last_collect_time > STUCK_SECONDS:
                outcome = "stuck"
                break
            if self.race_keys:
                for keys in self.race_keys:
                    self.apply(keys)
                break
            keys_log = self.decide()
            if keys_log is None:
                continue  # 競走に勝てる入力が見つかった（次のループで実行する）
            for keys in keys_log:
                self.apply(keys)
                if sim.done:
                    break
            if on_progress:
                on_progress(self, keys_log)
        outcome = outcome or sim.state
        fail_cell = None
        if outcome != "win" and self.visited:
            fail_cell = self.fail_cell or self.visited[-1]
        return {
            "seed": sim.seed,
            "outcome": outcome,
            "time": round(sim.elapsed, 2),
            "items": len(sim.items_collected),
            "fail_cell": list(fail_cell) if fail_cell else None,
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
