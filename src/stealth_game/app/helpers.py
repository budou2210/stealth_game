"""お助けアイテム（透明化・スタン・音の罠）。地獄では出ない。"""

import math
import random

from panda3d.core import TransparencyAttrib

from ..constants import (
    CLOAK_TIME,
    DECOY_FUSE,
    FLASH_RADIUS,
    HELPER_MAX_HELD,
    HELPER_SPAWN_DISTANCE,
    HELPER_SPAWN_INTERVAL,
    ITEM_PICKUP_DISTANCE,
    STUN_TIME_NEAR,
    STUN_TIME_SEEN,
)
from ..grid import cell_center, manhattan
from ..player import player_cell
from ..theme import DECOY_PLACED_COLOR, DECOY_RING_COLOR, FLASH_RING_COLOR


class HelperMixin:
    """お助けアイテムの出現・所持・使用。"""

    def helper_kinds(self):
        """この難易度で出るお助けアイテムの種類。"""
        kinds = []  # 並び順＝表示の順番（透明化・スタン・音の罠）
        if self.difficulty.cloak:
            kinds.append("cloak")
        if self.difficulty.flash:
            kinds.append("flash")
        if self.difficulty.decoy_radius > 0:
            kinds.append("decoy")
        return kinds

    def clear_placed_decoys(self):
        for decoy in self.placed_decoys:
            decoy["np"].removeNode()
        for ring in self.sound_rings:
            ring["np"].removeNode()
        self.placed_decoys = []
        self.sound_rings = []

    def pick_helper_spawn(self):
        """プレイヤーから程よく離れた、鬼も歩ける床を選ぶ。"""
        here = player_cell(self.player)
        lo, hi = HELPER_SPAWN_DISTANCE
        taken = set(self.remaining_item_cells())
        taken |= {c for c in self.helper_pickups.values() if c is not None}
        cells = [c for c in self.world.guard_cells if c not in taken]
        near = [c for c in cells if lo <= manhattan(here, c) <= hi]
        return random.choice(near or cells)

    def update_helper_spawn(self, dt):
        """種類ごとに一定時間おきに1個出す。マップに出ている間と、上限まで持っている間は数えない。"""
        appeared = []
        for kind in self.helper_kinds():
            if self.helper_pickups[kind] is not None or self.held[kind] >= HELPER_MAX_HELD[kind]:
                continue
            self.helper_spawn_timers[kind] -= dt
            if self.helper_spawn_timers[kind] > 0:
                continue
            cell = self.pick_helper_spawn()
            self.helper_pickups[kind] = cell
            x, y = cell_center(cell)
            self.pickup_nps[kind].setPos(x, y, 0.5)
            appeared.append(kind)
        if appeared:
            self.notice_timer = 5.0
            self.notice_key = "both_appeared" if len(appeared) > 1 else f"{appeared[0]}_appeared"

    def collect_helper(self):
        for kind, cell in self.helper_pickups.items():
            if cell is None:
                continue
            x, y = cell_center(cell)
            if math.hypot(self.player.x - x, self.player.y - y) < ITEM_PICKUP_DISTANCE:
                self.helper_pickups[kind] = None
                self.held[kind] += 1
                self.helper_spawn_timers[kind] = HELPER_SPAWN_INTERVAL

    def use_cloak(self):
        """E：透明化を使う（透明化中は重ねて使えない）。"""
        if self.state != "play" or "cloak" not in self.helper_kinds():
            return
        if self.held["cloak"] <= 0 or self.cloak_timer > 0:
            return
        self.held["cloak"] -= 1
        self.cloak_timer = CLOAK_TIME

    def update_cloak(self, dt):
        self.cloak_timer = max(0.0, self.cloak_timer - dt)
        self.player.invisible = self.cloak_timer > 0

    def place_decoy(self):
        """Space：足元に音の罠を置く（安全地帯の中には置けない）。"""
        if self.state != "play" or "decoy" not in self.helper_kinds():
            return
        if self.held["decoy"] <= 0:
            return
        cell = player_cell(self.player)
        if cell in self.world.safe_cells or self.world.is_wall(*cell):
            return
        self.held["decoy"] -= 1
        x, y = cell_center(cell)
        node = self.add_box(self.render, (x - 0.18, y - 0.18, 0), (0.36, 0.36, 0.2), DECOY_PLACED_COLOR)
        self.placed_decoys.append({"cell": cell, "timer": DECOY_FUSE, "np": node})

    def fire_decoy(self, decoy):
        """大きな音を出し、範囲内の鬼を引きつける。"""
        cell = decoy["cell"]
        x, y = cell_center(cell)
        radius = self.difficulty.decoy_radius
        for guard in self.guards:
            if guard.distance_to(x, y) <= radius:
                guard.hear_decoy(cell)
        decoy["np"].removeNode()
        self.add_ring(x, y, radius, DECOY_RING_COLOR, 0.35)

    def add_ring(self, x, y, radius, color, alpha):
        """床に広がって消える円（音の罠の音・スタンの光）。"""
        ring = self.disc.copyTo(self.render)
        ring.setPos(x, y, 0.07)
        ring.setScale(0.01)
        ring.setColor(*color, alpha)
        ring.setLightOff()
        ring.setTwoSided(True)
        ring.setTransparency(TransparencyAttrib.MAlpha)
        ring.setDepthWrite(False)
        self.sound_rings.append({"np": ring, "timer": 0.0, "radius": radius})

    def use_flash(self):
        """Q・/：スタン（閃光で目くらまし）。その瞬間プレイヤーを視界に入れていた鬼は10秒、
        見ていなくても周囲（FLASH_RADIUS以内、壁越しも含む）にいた鬼は5秒、目くらましにする。
        安全地帯の中では使えない。全アイテム回収後の狩りの鬼には効かない。"""
        if self.state != "play" or "flash" not in self.helper_kinds():
            return
        if self.held["flash"] <= 0 or self.player.safe:
            return
        self.held["flash"] -= 1
        px, py = self.player.x, self.player.y
        for guard in self.guards:
            if guard.hunting:
                continue
            if guard.check_sees(self.player):
                guard.stun(self.player, STUN_TIME_SEEN)
            elif guard.distance_to(px, py) <= FLASH_RADIUS:
                guard.stun(self.player, STUN_TIME_NEAR)
        self.add_ring(px, py, FLASH_RADIUS, FLASH_RING_COLOR, 0.6)

    def update_placed_decoys(self, dt):
        still_waiting = []
        for decoy in self.placed_decoys:
            decoy["timer"] -= dt
            if decoy["timer"] <= 0:
                self.fire_decoy(decoy)
            else:
                still_waiting.append(decoy)
        self.placed_decoys = still_waiting

    def update_helpers(self, dt):
        self.update_cloak(dt)
        if not self.helper_kinds():
            return
        self.update_helper_spawn(dt)
        self.collect_helper()
        self.update_placed_decoys(dt)
