"""視点（全体・中間・近い）の切り替えとカメラの追従。"""

import math

from panda3d.core import Point3, Vec3

from ..render.overview import overview_distance, overview_position
from ..theme import (
    CAMERA_MODES,
    HUD_MARGIN,
    MIDDLE_CAMERA_SCALE,
    NEAR_CAMERA_OFFSET,
    NEAR_LOOK_AHEAD,
    OVERVIEW_LOOK,
)


class CameraMixin:
    """視点の切り替えとカメラ。"""

    def setup_camera(self):
        self.camLens.setFov(60)
        self.camLens.setNearFar(1, 300)
        self.camera.setPos(self.cam_pos)
        self.camera.lookAt(self.cam_look)

    def toggle_overview(self):
        """Tab：全体 → 中間 → 近い → 全体 … と視点を切り替える。"""
        if self.state != "menu":
            index = CAMERA_MODES.index(self.camera_mode)
            self.camera_mode = CAMERA_MODES[(index + 1) % len(CAMERA_MODES)]

    def is_overview(self):
        return self.camera_mode == "overview"

    def alert_bar_top(self):
        """警戒度メーターの上端の高さ（画面下端が-1、上端が1）。"""
        top = self.alert_bar["frameSize"][3]
        return self.render2d.getRelativePoint(self.alert_bar, Point3(0, 0, top)).getZ()

    def overview_camera_targets(self):
        """警戒度メーターに被らない、ぎりぎりの距離から全体を映す。"""
        fov = tuple(self.camLens.getFov())
        bottom = self.alert_bar_top() + HUD_MARGIN
        key = (round(fov[0], 3), round(fov[1], 3), round(bottom, 4))
        if key not in self.overview_cache:
            self.overview_cache[key] = overview_distance(fov, bottom)
        pos = overview_position(self.overview_cache[key])
        return Vec3(*pos), Vec3(*OVERVIEW_LOOK)

    def camera_targets(self):
        if self.is_overview():
            return self.overview_camera_targets()
        scale = MIDDLE_CAMERA_SCALE if self.camera_mode == "middle" else 1.0
        px, py = self.player.x, self.player.y
        ox, oy, oz = NEAR_CAMERA_OFFSET
        pos = Vec3(px + ox * scale, py + oy * scale, oz * scale)
        return pos, Vec3(px, py + NEAR_LOOK_AHEAD * scale, 0)

    def snap_camera(self):
        self.cam_pos, self.cam_look = self.camera_targets()
        self.camera.setPos(self.cam_pos)
        self.camera.lookAt(self.cam_look)

    def update_camera(self, dt):
        target_pos, target_look = self.camera_targets()
        k = 1 - math.exp(-8 * dt)
        self.cam_pos += (target_pos - self.cam_pos) * k
        self.cam_look += (target_look - self.cam_look) * k
        self.camera.setPos(self.cam_pos)
        self.camera.lookAt(self.cam_look)
