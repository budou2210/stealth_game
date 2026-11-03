"""プレイヤー・鬼・アイテムなどの見た目の作成と毎フレームの更新。"""

import math

from panda3d.core import (
    Geom,
    GeomNode,
    GeomTrifans,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    TextNode,
    TransparencyAttrib,
    Vec3,
)

from ..constants import (
    CLOAK_WARN_TIME,
    DECOY_FUSE,
    DECOY_RING_TIME,
    EXCLAIM_BLINK_TIME,
    EXCLAIM_OVERVIEW_SIZE,
    EXCLAIM_POP_TIME,
    EXCLAIM_SCREEN_SIZE,
    EXCLAIM_TIME,
    ITEMS_PER_QUADRANT,
)
from ..difficulty import DIFFICULTIES
from ..grid import cell_center
from ..guard import Guard
from ..layout import EXIT_CELL, QUADRANTS
from ..render.meshes import make_disc
from ..theme import (
    CLOAK_PICKUP_COLOR,
    CONE_COLORS,
    CONE_RAYS,
    DECOY_PICKUP_COLOR,
    DECOY_PLACED_COLOR,
    EXCLAIM_BLINK_COLOR,
    EXCLAIM_CARD_COLOR,
    EXCLAIM_COLOR,
    EXCLAIM_FRAME_COLOR,
    FLASH_PICKUP_COLOR,
    SAFE_DOOR_COLOR,
    STATE_COLORS,
    STUN_COLOR,
    WALL_HEIGHT,
    WANDERER_PATROL_COLOR,
)


def exclaim_scale(age, base_size):
    """「！」の大きさ。出た瞬間は1.8倍に弾み、EXCLAIM_POP_TIMEで元に戻る。"""
    pop = 1.0 + 0.8 * max(0.0, 1.0 - age / EXCLAIM_POP_TIME)
    return base_size * pop


class VisualsMixin:
    """見た目（ノード）の作成と更新。"""

    def build_actors(self):
        self.player_np = self.render.attachNewNode("player")
        self.add_box(self.player_np, (-0.3, -0.3, 0), (0.6, 0.6, 0.9), (0.3, 0.95, 0.4, 1))
        self.add_box(self.player_np, (-0.12, 0.15, 0.55), (0.24, 0.3, 0.2), (0.9, 1, 0.9, 1))

        # 鬼が一番多い難易度に合わせて作り、少ない難易度では余りを隠す
        most = max(len(self.make_guards(cfg)) for cfg in DIFFICULTIES)
        self.guard_views = [self.make_guard_view() for _ in range(most)]
        total = ITEMS_PER_QUADRANT * len(QUADRANTS)
        self.item_nps = [self.make_item_node() for _ in range(total)]

        ex, ey = cell_center(EXIT_CELL)
        self.exit_np = self.add_box(
            self.render, (ex - 0.9, ey - 0.9, 0), (1.8, 1.8, 0.12), (0.8, 0.2, 0.2, 1)
        )
        # お助けアイテム（マップに出ている1個）と、音の広がりの円の元
        self.pickup_nps = {
            "decoy": self.make_pickup_node(DECOY_PICKUP_COLOR),
            "cloak": self.make_pickup_node(CLOAK_PICKUP_COLOR),
            "flash": self.make_pickup_node(FLASH_PICKUP_COLOR),
        }
        self.player_np.setTransparency(TransparencyAttrib.MAlpha)
        self.disc = make_disc()
        # 安全地帯の扉。外に出ると現れて、戻れなくなる
        self.door_nps = [
            self.add_box(self.render, (x, y, 0), (1, 1, WALL_HEIGHT), SAFE_DOOR_COLOR)
            for x, y in sorted(self.world.safe_doors)
        ]

    def make_guard_view(self):
        pivot = self.render.attachNewNode("guard")
        body = self.add_box(pivot, (-0.35, -0.35, 0), (0.7, 0.7, 1.0), STATE_COLORS["patrol"])
        self.add_box(pivot, (-0.12, 0.3, 0.55), (0.24, 0.4, 0.22), (1, 1, 1, 1))
        cone = GeomNode("cone")
        cone_np = self.render.attachNewNode(cone)
        cone_np.setLightOff()
        cone_np.setTwoSided(True)
        cone_np.setTransparency(TransparencyAttrib.MAlpha)
        cone_np.setDepthWrite(False)
        exclaim = TextNode("exclaim")
        exclaim.setText("!")
        exclaim.setAlign(TextNode.ACenter)
        exclaim.setTextColor(*EXCLAIM_COLOR)
        exclaim.setShadow(0.06, 0.06)
        exclaim.setShadowColor(0, 0, 0, 1)
        exclaim.setCardColor(*EXCLAIM_CARD_COLOR)  # 赤い札の上に文字を載せる
        exclaim.setCardAsMargin(0.35, 0.35, 0.15, 0.1)
        exclaim.setCardDecal(True)
        exclaim.setFrameColor(*EXCLAIM_FRAME_COLOR)
        exclaim.setFrameAsMargin(0.35, 0.35, 0.15, 0.1)
        exclaim.setFrameLineWidth(3)
        exclaim_np = self.render.attachNewNode(exclaim)
        exclaim_np.setBillboardPointEye()
        exclaim_np.setLightOff()
        exclaim_np.setDepthTest(False)
        exclaim_np.setDepthWrite(False)
        exclaim_np.setBin("fixed", 10)
        exclaim_np.hide()
        return {
            "pivot": pivot, "body": body, "cone": cone,
            "exclaim": exclaim_np, "exclaim_text": exclaim,
        }

    def make_pickup_node(self, color):
        pivot = self.render.attachNewNode("helper_pickup")
        self.add_box(pivot, (-0.22, -0.22, -0.22), (0.44, 0.44, 0.44), color)
        pivot.hide()
        return pivot

    def make_item_node(self):
        pivot = self.render.attachNewNode("item")
        self.add_box(pivot, (-0.2, -0.2, -0.2), (0.4, 0.4, 0.4), (1.0, 0.85, 0.1, 1))
        return pivot

    def update_cone(self, guard, view):
        node = view["cone"]
        node.removeAllGeoms()
        r, g, b = CONE_COLORS[guard.state]
        cfg = guard.cfg
        vdata = GeomVertexData("cone", GeomVertexFormat.getV3c4(), Geom.UHDynamic)
        vdata.setNumRows(CONE_RAYS + 2)
        vertex = GeomVertexWriter(vdata, "vertex")
        color = GeomVertexWriter(vdata, "color")
        vertex.addData3(guard.x, guard.y, 0.05)
        color.addData4(r, g, b, 0.45)
        for i in range(CONE_RAYS + 1):
            spread = 2 * cfg.view_half_angle * i / CONE_RAYS
            angle = guard.heading - cfg.view_half_angle + spread
            dist = self.world.cast_ray(guard.x, guard.y, angle, cfg.view_range)
            vertex.addData3(guard.x + math.cos(angle) * dist, guard.y + math.sin(angle) * dist, 0.05)
            color.addData4(r, g, b, 0.10)
        fan = GeomTrifans(Geom.UHDynamic)
        fan.addConsecutiveVertices(0, CONE_RAYS + 2)
        fan.closePrimitive()
        geom = Geom(vdata)
        geom.addPrimitive(fan)
        node.addGeom(geom)

    def body_color(self, guard):
        if guard.is_stunned():
            return STUN_COLOR
        if guard.is_wanderer() and guard.state == Guard.PATROL:
            return WANDERER_PATROL_COLOR
        return STATE_COLORS[guard.state]

    def update_guard_view(self, guard, view):
        view["pivot"].show()
        view["pivot"].setPos(guard.x, guard.y, 0)
        view["pivot"].setH(math.degrees(guard.heading) - 90)
        view["body"].setColor(*self.body_color(guard))
        if guard.is_stunned():  # 目がくらんでいる間は視界を出さない
            view["cone"].removeAllGeoms()
        else:
            self.update_cone(guard, view)
        if guard.exclaim_timer > 0:
            self.update_exclaim(guard, view)
        else:
            view["exclaim"].hide()

    def update_exclaim(self, guard, view):
        """「！」を弾ませ、点滅させる。全体表示では鬼と同じくらいの大きさにする。"""
        age = EXCLAIM_TIME - guard.exclaim_timer
        node = view["exclaim"]
        node.show()
        node.setPos(guard.x, guard.y, 2.0 + 0.15 * math.sin(age * 12))
        if self.is_overview():
            base_size = EXCLAIM_OVERVIEW_SIZE
        else:
            distance = (self.cam_pos - Vec3(guard.x, guard.y, 2.0)).length()
            base_size = EXCLAIM_SCREEN_SIZE * distance
        node.setScale(exclaim_scale(age, base_size))
        blink = age < EXCLAIM_BLINK_TIME and int(age * 12) % 2 == 1
        view["exclaim_text"].setTextColor(*(EXCLAIM_BLINK_COLOR if blink else EXCLAIM_COLOR))

    def player_alpha(self):
        """透明化中は薄く表示。残りわずかになると点滅して知らせる。"""
        if self.cloak_timer <= 0 or self.state == "menu":
            return 1.0
        if self.cloak_timer < CLOAK_WARN_TIME and int(self.cloak_timer * 8) % 2 == 0:
            return 0.65
        return 0.3

    def update_decoy_views(self, dt):
        for kind, node in self.pickup_nps.items():
            if self.helper_pickups[kind] is not None and self.state != "menu":
                node.show()
                node.setH(node.getH() + 200 * dt)
            else:
                node.hide()
        for decoy in self.placed_decoys:  # 鳴る直前ほど速く点滅
            blink = math.sin((DECOY_FUSE - decoy["timer"]) ** 2 * 6) > 0
            decoy["np"].setColor(*(DECOY_PLACED_COLOR if blink else (1, 1, 1, 1)))
        alive = []
        for ring in self.sound_rings:
            ring["timer"] += dt
            t = ring["timer"] / DECOY_RING_TIME
            if t >= 1:
                ring["np"].removeNode()
                continue
            ring["np"].setScale(max(0.01, ring["radius"] * t))
            ring["np"].setAlphaScale(1 - t)
            alive.append(ring)
        self.sound_rings = alive

    def update_item_views(self, dt):
        for i, (item_np, cell) in enumerate(zip(self.item_nps, self.item_cells)):
            if i not in self.items_collected:
                item_np.show()
                item_np.setH(item_np.getH() + 120 * dt)
            else:
                item_np.hide()
        for item_np in self.item_nps[len(self.item_cells):]:
            item_np.hide()

    def update_visuals(self, dt):
        self.player_np.setPos(self.player.x, self.player.y, 0)
        self.player_np.setH(math.degrees(self.player.heading) - 90)
        self.player_np.setAlphaScale(self.player_alpha())
        for guard, view in zip(self.guards, self.guard_views):
            self.update_guard_view(guard, view)
        for view in self.guard_views[len(self.guards):]:
            view["pivot"].hide()
            view["exclaim"].hide()
            view["cone"].removeAllGeoms()
        self.update_decoy_views(dt)
        self.update_item_views(dt)
