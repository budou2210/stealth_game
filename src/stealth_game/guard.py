"""警備員（鬼）のAI（ロジックのみ。描画はapp側）。"""

import math
import random

from .constants import (
    CHASE_HEAR_RATE,
    DIRECT_PURSUIT_RANGE,
    EXCLAIM_TIME,
    FLANK_GOAL_FREE,
    FOCUS_REACH,
    GUARD_PATROL_SPEED,
    GUARD_TURN_RATE,
    NEAR_SENSE_RADIUS,
    RESPOND_REPLAN,
    SOUND_WALL_MUFFLE,
    STUN_SPIN_RATE,
    WANDER_MAX_DISTANCE,
    WANDER_MIN_DISTANCE,
    WANDER_PAUSE_RANGE,
)
from .grid import cell_center, manhattan, world_to_cell
from .pathfinding import astar
from .player import player_cell


def normalize_angle(angle):
    return (angle + math.pi) % (2 * math.pi) - math.pi


class Guard:
    PATROL = "patrol"
    SEARCH = "search"
    SPOTTED = "spotted"  # 「！」を出して、追跡を始める直前の一瞬
    CHASE = "chase"

    def __init__(self, world, cfg, route=None, spawn=None):
        """routeがあれば順路を巡回、なければspawnから出発してランダムに徘徊する。"""
        self.world = world
        self.cfg = cfg
        self.route = route
        self.spawn = route[0] if route else spawn
        self.focus_provider = None  # 難しい：徘徊型が狙う注目地点を教えてくれる関数
        self.reset()

    def is_wanderer(self):
        return self.route is None

    def reset(self):
        self.x, self.y = cell_center(self.spawn)
        self.heading = 0.0
        self.state = Guard.PATROL
        self.alert = 0.0
        self.path = []
        self.route_index = 0
        self.last_known = None
        self.wait_timer = 0.0
        self.replan_timer = 0.0
        self.sees_player = False
        self.hunting = False  # Trueの間はプレイヤーを決して見失わない
        self.chase_role = 0
        self.responding = False  # 「応援」で呼ばれて駆けつけている途中か
        self.flank_cells = {}  # 挟み撃ち：近い鬼の通る道 {セル: その鬼の役割}
        self.pause_timer = None
        self.last_velocity = (0.0, 0.0)
        self.extrapolations_left = self.cfg.lost_extrapolations
        self.spot_timer = 0.0
        self.exclaim_timer = 0.0  # 0より大きい間「！」を表示する
        self.stun_timer = 0.0  # 0より大きい間、スタン（アイテム）で目がくらんで動けない

    # --- 基本ヘルパー ---------------------------------------------------
    def is_stunned(self):
        return self.stun_timer > 0

    def cell(self):
        return world_to_cell(self.x, self.y)

    def set_path_to(self, goal, extra_cost=None):
        path = astar(self.world, self.cell(), goal, extra_cost)
        self.path = path[1:]  # 先頭は今いるセルなので捨てる

    def distance_to(self, x, y):
        return math.hypot(x - self.x, y - self.y)

    def turn_toward(self, angle, dt):
        diff = normalize_angle(angle - self.heading)
        limit = GUARD_TURN_RATE * dt
        self.heading += max(-limit, min(limit, diff))

    # --- 知覚 -----------------------------------------------------------
    def view_range_for(self, player):
        rate = self.cfg.sneak_view_rate if player.sneaking else 1.0
        return self.cfg.view_range * rate

    def check_sees(self, player):
        if player.safe or player.invisible:  # 透明化中は至近距離でも見えない
            return False
        dist = self.distance_to(player.x, player.y)
        if dist > self.view_range_for(player):
            return False
        angle = math.atan2(player.y - self.y, player.x - self.x)
        in_fov = abs(normalize_angle(angle - self.heading)) <= self.cfg.view_half_angle
        if not (in_fov or dist <= NEAR_SENSE_RADIUS):
            return False
        return self.world.has_line_of_sight(self.x, self.y, player.x, player.y)

    def can_hear_within(self, player, radius):
        """radius以内で足音が届くか。壁越し（視線なし）だと距離が縮む。"""
        if player.safe:
            return False
        dist = self.distance_to(player.x, player.y)
        if dist > radius:
            return False
        if dist <= radius * SOUND_WALL_MUFFLE:
            return True
        return self.world.has_line_of_sight(self.x, self.y, player.x, player.y)

    def check_hears(self, player):
        return player.is_noisy() and self.can_hear_within(player, self.cfg.hear_radius)

    def update_alert(self, dt, player):
        if not self.sees_player:
            self.alert = max(0.0, self.alert - 0.4 * dt)
            return
        ratio = self.distance_to(player.x, player.y) / self.view_range_for(player)
        gain = (0.9 + 2.0 * (1.0 - ratio)) * self.cfg.alert_gain
        self.alert = min(1.0, self.alert + gain * dt)

    # --- 状態遷移 -------------------------------------------------------
    def start_chase(self, player):
        self.state = Guard.CHASE
        self.responding = False
        self.alert = 1.0
        self.last_known = player_cell(player)
        self.last_velocity = (player.vx, player.vy)
        self.extrapolations_left = self.cfg.lost_extrapolations
        self.replan_timer = 0.0

    def investigate(self, cell):
        """物音や仲間の合図で、その場所を調べに行く。"""
        self.state = Guard.SEARCH
        self.responding = False
        self.last_known = cell
        self.wait_timer = 0.0
        self.replan_timer = random.uniform(0.3, 0.6)
        self.set_path_to(cell)

    def return_to_patrol(self):
        self.responding = False
        if self.is_wanderer():
            self.state = Guard.PATROL
            self.pause_timer = None
            self.path = []
            return
        cx, cy = self.cell()
        nearest = min(
            range(len(self.route)),
            key=lambda i: manhattan((cx, cy), self.route[i]),
        )
        self.state = Guard.PATROL
        self.route_index = nearest
        self.set_path_to(self.route[nearest])

    def spot(self, player):
        """プレイヤーに気づいた。「！」を出し、間を置いて（地獄は即座に）追跡する。"""
        self.exclaim_timer = EXCLAIM_TIME
        self.responding = False
        if self.cfg.spot_delay <= 0:
            self.start_chase(player)
            return
        self.state = Guard.SPOTTED
        self.spot_timer = self.cfg.spot_delay
        self.path = []
        self.last_known = player_cell(player)
        self.last_velocity = (player.vx, player.vy)

    def update_spotted(self, dt, player):
        """その場で止まってプレイヤーの方を向き、間が終わったら追跡を始める。"""
        if self.sees_player:
            self.turn_toward(math.atan2(player.y - self.y, player.x - self.x), dt)
            self.last_known = player_cell(player)
            self.last_velocity = (player.vx, player.vy)
        self.spot_timer -= dt
        if self.spot_timer > 0:
            return
        known, velocity = self.last_known, self.last_velocity
        self.start_chase(player)
        if not self.sees_player:  # 間の間に見失ったら、最後に見た場所から追う
            self.last_known, self.last_velocity = known, velocity

    def hear_decoy(self, cell):
        """音の罠の大きな音。プレイヤーを見ていなければ調べに行く。
        全アイテム回収後の狩りの最中（hunting）と、目がくらんでいる間は反応しない。"""
        if self.hunting or self.is_stunned() or self.state == Guard.SPOTTED:
            return
        if self.state == Guard.CHASE and self.sees_player:
            return
        self.investigate(cell)

    def stun(self, player, duration):
        """スタン（アイテム）：目がくらんでその場で動けなくなる。追跡も警戒もいったん途切れる。
        すでに目がくらんでいれば、残り時間の長い方を採る（延長はしない）。"""
        self.stun_timer = max(self.stun_timer, duration)
        self.state = Guard.SEARCH
        self.responding = False
        self.path = []
        self.alert = 0.0
        self.exclaim_timer = 0.0
        self.sees_player = False
        self.last_known = player_cell(player)

    def update_stunned(self, dt):
        """目がくらんでいる間はその場で回るだけ。治ったら最後に見た場所を調べに行く。"""
        self.stun_timer = max(0.0, self.stun_timer - dt)
        self.heading += STUN_SPIN_RATE * dt
        if self.stun_timer <= 0:
            self.investigate(self.last_known)

    def receive_alert(self, cell, velocity):
        """追跡中の仲間から居場所を教えてもらう。
        挟み撃ちのある難易度では、逃げる向き（velocity）も教わり、駆けつける途中も先回りを狙う。"""
        if self.state == Guard.SPOTTED or self.is_stunned():
            return
        flank = self.cfg.flank_avoid_cost > 0
        if self.state == Guard.CHASE:
            if not self.sees_player:
                self.last_known = cell
                if flank:
                    self.last_velocity = velocity
        elif flank:
            if not self.responding:
                self.investigate(cell)
                self.responding = True
            self.last_known = cell
            self.last_velocity = velocity
            self.wait_timer = 0.0
        elif self.state == Guard.PATROL or self.last_known != cell:
            self.investigate(cell)

    # --- 徘徊型の目的地選び -----------------------------------------------
    def pick_focus_goal(self, here):
        """難しい：プレイヤー・未回収アイテム・出口の付近から目的地を選ぶ。"""
        foci = [f for f in self.focus_provider() if manhattan(here, f[0]) <= FOCUS_REACH]
        if not foci:
            return None
        cell, radius, _ = random.choices(foci, weights=[f[2] for f in foci])[0]
        candidates = [
            c
            for c in self.world.guard_cells
            if manhattan(c, cell) <= radius and manhattan(c, here) >= 4
        ]
        return random.choice(candidates) if candidates else None

    def pick_wander_goal(self):
        here = self.cell()
        smart = self.cfg.smart_wander and self.focus_provider is not None
        if smart and random.random() < self.cfg.focus_rate:
            goal = self.pick_focus_goal(here)
            if goal is not None:
                return goal
        near = [
            c
            for c in self.world.guard_cells
            if WANDER_MIN_DISTANCE <= manhattan(here, c) <= WANDER_MAX_DISTANCE
        ]
        return random.choice(near or self.world.guard_cells)

    def update_wander(self, dt):
        """目的地に着いたら少し見回し、次の目的地へ向かう。"""
        if self.pause_timer is None:
            self.pause_timer = random.uniform(*WANDER_PAUSE_RANGE)
        self.pause_timer -= dt
        self.heading += math.radians(90) * math.sin(self.pause_timer * 4) * dt
        if self.pause_timer <= 0:
            self.pause_timer = None
            self.set_path_to(self.pick_wander_goal())

    # --- 状態ごとの更新 ---------------------------------------------------
    def update_patrol(self, dt, player):
        if self.alert >= 1.0:
            self.spot(player)
            return
        if self.check_hears(player):
            self.investigate(player_cell(player))
            return
        if self.path:
            return
        if self.is_wanderer():
            self.update_wander(dt)
            return
        self.route_index = (self.route_index + 1) % len(self.route)
        self.set_path_to(self.route[self.route_index])

    def update_search(self, dt, player):
        if self.alert >= 1.0:
            self.spot(player)
            return
        self.replan_timer -= dt
        if self.responding:
            self.update_responding()
            if self.path:
                return
        elif self.check_hears(player) and self.replan_timer <= 0:
            self.investigate(player_cell(player))
            return
        if self.path:
            return
        self.wait_timer += dt
        self.heading += math.radians(70) * math.sin(self.wait_timer * 2.5) * dt * 2
        if self.wait_timer >= self.cfg.search_wait:
            self.return_to_patrol()

    def update_responding(self):
        """「応援」で駆けつける途中：教わった居場所へ、遠ければ回り込んで先回りする。"""
        if self.replan_timer > 0 or self.last_known is None:
            return
        self.replan_pursuit(self.pursuit_target_unseen())
        self.replan_timer = random.uniform(*RESPOND_REPLAN)

    def track_player(self, player):
        """見えていれば位置と速度を記憶。見えなくても足音で位置を掴む。"""
        if self.sees_player:
            self.last_known = player_cell(player)
            self.last_velocity = (player.vx, player.vy)
            self.extrapolations_left = self.cfg.lost_extrapolations
            return
        radius = self.cfg.hear_radius * CHASE_HEAR_RATE
        if player.is_noisy() and self.can_hear_within(player, radius):
            self.last_known = player_cell(player)

    def predict_target(self, player):
        """プレイヤーの進行方向の先を狙う（先回り）。役割が後ろの鬼ほど大きく先を読む。"""
        return self.lead_target(player.x, player.y, player.vx, player.vy)

    def lead_target(self, x, y, vx, vy):
        """(x,y)から速度(vx,vy)で逃げる相手の、少し先のセルを返す。"""
        factors = self.cfg.chase_lead_factors
        factor = factors[min(self.chase_role, len(factors) - 1)]
        dist = self.distance_to(x, y)
        lead_time = min(dist / self.cfg.chase_speed, 2.0) * factor
        goal_x = x + vx * lead_time
        goal_y = y + vy * lead_time
        return self.walkable_cell_toward(goal_x, goal_y, x, y)

    def pursuit_target_unseen(self):
        """見えていない追っ手の目的地。挟み撃ちをする鬼は、教わった向きの先を狙う。"""
        if not self.is_flanker():
            return self.last_known
        cx, cy = cell_center(self.last_known)
        return self.lead_target(cx, cy, *self.last_velocity)

    def is_flanker(self):
        """挟み撃ちで回り込む役か（激ムズ以上、2番手以降で、プレイヤーから遠い鬼）。"""
        if self.cfg.flank_avoid_cost <= 0 or self.chase_role == 0 or self.last_known is None:
            return False
        cx, cy = cell_center(self.last_known)
        return self.distance_to(cx, cy) > self.cfg.flank_min_distance

    def replan_pursuit(self, target):
        """targetへの経路を引く。回り込む役なら、近い鬼の通る道を避ける。"""
        if target is None:
            return
        if not self.is_flanker():
            self.set_path_to(target)
            return
        cost = self.cfg.flank_avoid_cost
        role = self.chase_role
        busy = self.flank_cells

        def extra_cost(cell):
            if busy.get(cell, role) >= role or manhattan(cell, target) <= FLANK_GOAL_FREE:
                return 0
            return cost

        self.set_path_to(target, extra_cost)

    def walkable_cell_toward(self, x, y, anchor_x, anchor_y):
        """(x,y)が壁なら、anchor側へ戻りながら最初の通路セルを返す。"""
        for i in range(21):
            t = i / 20
            px = x + (anchor_x - x) * t
            py = y + (anchor_y - y) * t
            if not self.world.is_wall_at(px, py):
                return world_to_cell(px, py)
        return world_to_cell(anchor_x, anchor_y)

    def extrapolate_escape(self):
        """見失った地点から、逃げた方向へ先読みして追う。できたらTrue。"""
        vx, vy = self.last_velocity
        speed = math.hypot(vx, vy)
        if self.extrapolations_left <= 0 or speed < 0.1 or self.last_known is None:
            return False
        self.extrapolations_left -= 1
        cx, cy = cell_center(self.last_known)
        goal_x = cx + vx / speed * self.cfg.lost_lookahead
        goal_y = cy + vy / speed * self.cfg.lost_lookahead
        self.last_known = self.walkable_cell_toward(goal_x, goal_y, cx, cy)
        self.set_path_to(self.last_known)
        return True

    def pick_chase_target(self, player):
        if self.sees_player:
            return self.predict_target(player)
        if self.last_known is None:
            return None
        return self.pursuit_target_unseen()

    def update_chase(self, dt, player):
        self.track_player(player)
        self.replan_timer -= dt
        target = self.pick_chase_target(player)
        if self.replan_timer <= 0 and target is not None:
            self.replan_pursuit(target)
            self.replan_timer = random.uniform(*self.cfg.chase_replan)
        if self.sees_player or self.path:
            return
        if not self.extrapolate_escape():
            self.state = Guard.SEARCH
            self.wait_timer = 0.0

    def is_direct_pursuit(self, player):
        if self.state != Guard.CHASE or player.safe:
            return False
        if player.invisible and not self.hunting:
            return False
        if self.distance_to(player.x, player.y) > DIRECT_PURSUIT_RANGE:
            return False
        return self.world.has_line_of_sight(self.x, self.y, player.x, player.y)

    # --- 移動 -----------------------------------------------------------
    def current_speed(self):
        if self.state == Guard.CHASE:
            return self.cfg.chase_speed
        if self.state == Guard.SEARCH:
            return self.cfg.search_speed
        return GUARD_PATROL_SPEED

    def move_toward(self, tx, ty, dt):
        """目標点へ向かって1歩進む。到着したらTrue。"""
        dist = self.distance_to(tx, ty)
        step = self.current_speed() * dt
        self.turn_toward(math.atan2(ty - self.y, tx - self.x), dt)
        if dist <= step:
            self.x, self.y = tx, ty
            return True
        self.x += (tx - self.x) / dist * step
        self.y += (ty - self.y) / dist * step
        return False

    def move_along_path(self, dt):
        if not self.path:
            return
        if self.move_toward(*cell_center(self.path[0]), dt):
            self.path.pop(0)

    def pursue_directly(self, player, dt):
        """近くで視界が通っているときは、経路を使わずプレイヤーへ一直線。"""
        self.path = []
        self.move_toward(player.x, player.y, dt)

    def update(self, dt, player):
        self.exclaim_timer = max(0.0, self.exclaim_timer - dt)
        if self.hunting:  # 全アイテム回収後の狩りが始まったら、目くらましも解ける
            self.stun_timer = 0.0
        if self.is_stunned():
            self.sees_player = False
            self.update_stunned(dt)
            return
        self.sees_player = not player.safe and (self.check_sees(player) or self.hunting)
        self.update_alert(dt, player)
        if self.hunting and self.state != Guard.CHASE:
            self.start_chase(player)
        if self.state == Guard.CHASE:
            self.update_chase(dt, player)
        elif self.state == Guard.SPOTTED:
            self.update_spotted(dt, player)
        elif self.state == Guard.SEARCH:
            self.update_search(dt, player)
        else:
            self.update_patrol(dt, player)
        if self.is_direct_pursuit(player):
            self.pursue_directly(player, dt)
        else:
            self.move_along_path(dt)
