"""ゲーム本体（Panda3DのShowBase）。各機能はMixinに分けてある。"""

import math
import random

from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    AmbientLight,
    ClockObject,
    DirectionalLight,
    Vec3,
    loadPrcFileData,
)

from ..constants import (
    CATCH_DISTANCE,
    CAUGHT_FREEZE_TIME,
    HELPER_MAX_HELD,
    HELPER_SPAWN_INTERVAL,
    ITEM_MIN_SPACING,
    ITEM_PICKUP_DISTANCE,
    ITEMS_DROPPED_ON_CATCH,
    PLAYER_RADIUS,
)
from ..difficulty import DEFAULT_DIFFICULTY_INDEX, NORMAL
from ..grid import cell_center, manhattan
from ..guard import Guard
from ..items import is_valid_item_cell, pick_item_cells
from ..layout import EXIT_CELL, PLAYER_START
from ..mapgen import build_guard_routes, build_wanderer_spawns
from ..player import Player, player_cell
from ..render.meshes import build_level_node, make_unit_box
from ..theme import INITIAL_CAMERA_LOOK, INITIAL_CAMERA_POS
from ..world import World
from .camera import CameraMixin
from .helpers import HelperMixin
from .hud import HudMixin
from .input import InputMixin
from .menu import MenuMixin
from .visuals import VisualsMixin


class StealthGame(
    InputMixin, CameraMixin, VisualsMixin, HudMixin, MenuMixin, HelperMixin, ShowBase
):
    def __init__(self):
        loadPrcFileData("", "window-title Stealth Game\nwin-size 1100 800")
        super().__init__()
        self.disableMouse()
        self.setBackgroundColor(0.04, 0.05, 0.08)

        self.world = World()
        self.player = Player()
        self.difficulty = NORMAL
        self.guards = self.make_guards(NORMAL)
        self.box = make_unit_box()
        self.state = "menu"
        self.menu_index = DEFAULT_DIFFICULTY_INDEX
        self.show_noise_range = True  # 設定：走ったときに足音の届く範囲を表示する（Fで切り替え）
        self.elapsed = 0.0
        self.item_cells = []
        self.items_collected = set()
        self.collect_order = []
        self.lives = NORMAL.lives
        self.caught_timer = 0.0
        self.held = {kind: 0 for kind in HELPER_MAX_HELD}  # 持っているお助けアイテムの数
        self.helper_pickups = {kind: None for kind in HELPER_MAX_HELD}  # マップに出ている箱のセル
        self.helper_spawn_timers = {kind: HELPER_SPAWN_INTERVAL for kind in HELPER_MAX_HELD}
        self.keys_were_down = {}  # 前のフレームで押されていたキー（押した瞬間の判定用）
        self.cloak_timer = 0.0  # 透明化の残り秒数
        self.placed_decoys = []  # 設置済み: {"cell", "timer", "np"}
        self.sound_rings = []  # 音の広がりの表示: {"np", "timer", "radius"}
        self.notice_timer = 0.0  # 0より大きい間、出現のお知らせをヒント欄に出す
        self.notice_key = "decoy_appeared"
        self.notice_kinds = []  # 出現のお知らせに載せる種類（同時に出たとき用）
        self.camera_mode = "overview"
        self.cam_pos = Vec3(*INITIAL_CAMERA_POS)
        self.cam_look = Vec3(*INITIAL_CAMERA_LOOK)

        self.setup_keys()
        self.setup_lights()
        self.setup_camera()
        self.build_level()
        self.build_actors()
        self.set_doors_closed(False)
        self.setup_hud()
        self.overview_cache = {}
        self.snap_camera()

        self.bind_events()
        self.open_menu()
        self.taskMgr.add(self.update, "update")

    def make_guards(self, cfg):
        routes = build_guard_routes()
        spawns = build_wanderer_spawns() if cfg.wanderers else []
        guards = [Guard(self.world, cfg, route=route) for route in routes]
        guards += [Guard(self.world, cfg, spawn=spawn) for spawn in spawns]
        if cfg.smart_wander:
            for guard in guards:
                guard.focus_provider = self.wander_foci
        return guards

    def setup_lights(self):
        ambient = AmbientLight("ambient")
        ambient.setColor((0.50, 0.50, 0.58, 1))
        self.render.setLight(self.render.attachNewNode(ambient))
        sun = DirectionalLight("sun")
        sun.setColor((0.80, 0.80, 0.72, 1))
        sun_np = self.render.attachNewNode(sun)
        sun_np.setHpr(-30, -60, 0)
        self.render.setLight(sun_np)

    def add_box(self, parent, pos, scale, color=None):
        node = self.box.copyTo(parent)
        node.setPos(*pos)
        node.setScale(*scale)
        if color is not None:
            node.setColor(*color)
        return node

    def build_level(self):
        self.level_np = build_level_node(self.world)
        self.level_np.reparentTo(self.render)

    def start_game(self, cfg):
        self.difficulty = cfg
        self.guards = self.make_guards(cfg)
        self.menu_title.hide()
        self.menu_text.hide()
        self.set_play_hud_visible(True)
        self.reset_game()

    def restart_game(self):
        if self.state != "menu":
            self.start_game(self.difficulty)

    def reset_game(self):
        self.state = "play"
        self.elapsed = 0.0
        self.lives = self.difficulty.lives
        self.items_collected = set()
        self.collect_order = []  # 拾った順。捕まったら最後に拾ったものから落とす
        self.camera_mode = "overview"  # 始めはマップ全体を映す（Tabで 中間 → 近い へ）
        self.item_cells = pick_item_cells(self.world)
        self.place_item_nodes()
        self.exit_np.setColor(0.8, 0.2, 0.2, 1)
        self.held = {kind: 0 for kind in HELPER_MAX_HELD}
        self.helper_pickups = {kind: None for kind in HELPER_MAX_HELD}
        self.helper_spawn_timers = {kind: HELPER_SPAWN_INTERVAL for kind in HELPER_MAX_HELD}
        self.notice_timer = 0.0
        self.respawn()

    def place_item_nodes(self):
        for item_np, cell in zip(self.item_nps, self.item_cells):
            x, y = cell_center(cell)
            item_np.setPos(x, y, 0.5)

    def set_doors_closed(self, closed):
        self.world.doors_closed = closed
        for door_np in self.door_nps:
            if closed:
                door_np.show()
            else:
                door_np.hide()

    def respawn(self):
        """プレイヤーをスタート部屋に戻し、鬼を全員最初の位置と状態に戻す。"""
        self.player.reset(PLAYER_START)
        self.set_doors_closed(False)
        for guard in self.guards:
            guard.reset()
        self.cloak_timer = 0.0
        self.clear_placed_decoys()
        self.message_text.setText("")
        self.snap_camera()

    def drop_items(self, cell):
        """最後に拾ったアイテムから順に落とす。落とした数を返す。

        1個目は捕まった場所に、2個目以降はマップのランダムな場所に落とす。
        """
        count = min(ITEMS_DROPPED_ON_CATCH, len(self.collect_order))
        taken = set(self.remaining_item_cells())
        spots = []
        for i in range(count):
            spot = self.drop_spot_near(cell, taken) if i == 0 else self.random_drop_spot(taken)
            spots.append(spot)
            taken.add(spot)
        for spot in spots:
            index = self.collect_order.pop()
            self.item_cells[index] = spot
            self.items_collected.discard(index)
        self.place_item_nodes()
        return count

    def drop_spot_near(self, cell, taken):
        """捕まった場所（そこが使えなければ一番近い床）。"""
        return self.world.nearest_cells(cell, 1, taken)[0]

    def random_drop_spot(self, taken):
        """ランダムな床。スタート・出口・他のアイテムからは離す（無理なら条件を緩める）。"""
        cells = [c for c in self.world.guard_cells if c not in taken]
        valid = [c for c in cells if is_valid_item_cell(c)]
        spread = [c for c in valid if all(manhattan(c, t) >= ITEM_MIN_SPACING for t in taken)]
        return random.choice(spread or valid or cells)

    def on_caught(self):
        self.lives -= 1
        if self.lives <= 0:
            self.state = "lose"
            self.message_text.setText(self.text["lose"])
            return
        dropped = self.drop_items(player_cell(self.player))
        self.state = "caught"
        self.caught_timer = CAUGHT_FREEZE_TIME
        self.message_text.setText(self.text["caught"].format(lives=self.lives, dropped=dropped))

    def update_caught(self, dt):
        """捕まった直後は少し止まり、その後スタート部屋で復活する。"""
        self.caught_timer -= dt
        if self.caught_timer <= 0:
            self.state = "play"
            self.respawn()

    def update_safe_zone(self):
        """安全地帯から完全に出たら扉を閉める。中にいる間は見つからない。"""
        p = self.player
        if not self.world.doors_closed and self.world.is_fully_outside_safe_zone(p.x, p.y, PLAYER_RADIUS):
            self.set_doors_closed(True)
        p.safe = not self.world.doors_closed and self.world.is_in_safe_zone(p.x, p.y)

    def remaining_item_cells(self):
        return [c for i, c in enumerate(self.item_cells) if i not in self.items_collected]

    def wander_foci(self):
        """難しい：徘徊型が狙う注目地点 (セル, 半径, 重み)。"""
        foci = [(player_cell(self.player), 12, 4.0), (EXIT_CELL, 10, 2.0)]
        remaining = self.remaining_item_cells()
        for cell in remaining:
            foci.append((cell, 8, 4.0 / len(remaining)))
        return foci

    def alert_allies(self, caller):
        """「応援」：追跡中の鬼が近くの仲間に居場所を伝える。半径0なら何もしない。"""
        radius = self.difficulty.ally_alert_radius
        if caller.last_known is None or radius <= 0:
            return
        allies = [
            other
            for other in self.guards
            if other is not caller and other.distance_to(caller.x, caller.y) <= radius
        ]
        limit = self.difficulty.ally_alert_max
        if limit > 0:  # 難しい：近い順に決まった人数だけ呼ぶ
            allies.sort(key=lambda g: g.distance_to(caller.x, caller.y))
            allies = allies[:limit]
        for other in allies:
            other.receive_alert(caller.last_known, caller.last_velocity)

    def share_alerts(self):
        """追跡中・応援で駆けつけ中の鬼に役割を振り（近い順）、見えている鬼は居場所を仲間と共有する。
        挟み撃ち用に、近い鬼の通る道（今いるマスと経路）を {セル: 役割} で後ろの鬼に渡す。"""
        pursuers = [g for g in self.guards if g.state == Guard.CHASE or g.responding]
        pursuers.sort(key=lambda g: g.distance_to(self.player.x, self.player.y))
        busy = {}
        for role, guard in enumerate(pursuers):
            guard.chase_role = role
            guard.flank_cells = busy
            for cell in [guard.cell()] + guard.path:
                busy.setdefault(cell, role)
            if guard.state == Guard.CHASE and guard.sees_player and not guard.hunting:
                self.alert_allies(guard)

    def collect_items(self):
        for i, cell in enumerate(self.item_cells):
            if i in self.items_collected:
                continue
            ix, iy = cell_center(cell)
            if math.hypot(self.player.x - ix, self.player.y - iy) < ITEM_PICKUP_DISTANCE:
                self.items_collected.add(i)
                self.collect_order.append(i)

    def has_all_items(self):
        return len(self.items_collected) == len(self.item_cells)

    def is_hunting_phase(self):
        return self.difficulty.hunt_after_all_items and self.has_all_items()

    def check_caught(self):
        """鬼に触れたら捕まる。透明化中は触れても捕まらない
        （ただし全アイテム回収後の狩りの鬼には透明化が効かない）。目がくらんでいる鬼には捕まらない。"""
        if self.player.safe:
            return False
        return any(
            guard.distance_to(self.player.x, self.player.y) < CATCH_DISTANCE
            and (not self.player.invisible or guard.hunting)
            and not guard.is_stunned()
            for guard in self.guards
        )

    def check_exit_reached(self):
        ex, ey = cell_center(EXIT_CELL)
        near = math.hypot(self.player.x - ex, self.player.y - ey) < 0.9
        return near and self.has_all_items()

    def update_play(self, dt):
        self.elapsed += dt
        dx, dy = self.read_input()
        self.player.sneaking = self.is_down("sneak")
        self.player.move(dt, dx, dy, self.world)
        self.update_safe_zone()
        self.collect_items()
        self.notice_timer = max(0.0, self.notice_timer - dt)
        self.update_helpers(dt)
        hunting = self.is_hunting_phase()
        for guard in self.guards:
            guard.hunting = hunting and guard.is_wanderer()
            guard.update(dt, self.player)
        self.share_alerts()
        exit_color = (0.2, 0.9, 0.3, 1) if self.has_all_items() else (0.8, 0.2, 0.2, 1)
        self.exit_np.setColor(*exit_color)
        if self.check_caught():
            self.on_caught()
        elif self.check_exit_reached():
            self.state = "win"
            self.message_text.setText(self.text["win"].format(time=self.elapsed))

    def update(self, task):
        dt = min(ClockObject.getGlobalClock().getDt(), 0.05)
        self.poll_action_keys()
        if self.state == "play":
            self.update_play(dt)
        elif self.state == "caught":
            self.update_caught(dt)
        self.update_visuals(dt)
        self.update_camera(dt)
        self.update_hud()
        return task.cont
