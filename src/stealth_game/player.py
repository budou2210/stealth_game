"""プレイヤー（ロジックのみ。描画はapp側）。"""

import math

from .constants import PLAYER_RADIUS, PLAYER_RUN_SPEED, PLAYER_SNEAK_SPEED
from .grid import cell_center, world_to_cell


class Player:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.heading = math.pi / 2
        self.sneaking = False
        self.moving = False
        self.vx = 0.0
        self.vy = 0.0
        self.safe = True  # 安全地帯にいる間は見つからず、捕まらない
        self.invisible = False  # 透明化中は視界に映らない（足音は聞かれる）

    def reset(self, cell):
        self.x, self.y = cell_center(cell)
        self.heading = math.pi / 2
        self.sneaking = False
        self.moving = False
        self.vx = 0.0
        self.vy = 0.0
        self.safe = True
        self.invisible = False

    def is_noisy(self):
        return self.moving and not self.sneaking

    def move(self, dt, dx, dy, world):
        length = math.hypot(dx, dy)
        self.moving = length > 0
        self.vx = 0.0
        self.vy = 0.0
        if not self.moving:
            return
        old_x, old_y = self.x, self.y
        speed = PLAYER_SNEAK_SPEED if self.sneaking else PLAYER_RUN_SPEED
        step_x = dx / length * speed * dt
        step_y = dy / length * speed * dt
        self.heading = math.atan2(dy, dx)
        if not world.is_blocked(self.x + step_x, self.y, PLAYER_RADIUS):
            self.x += step_x
        if not world.is_blocked(self.x, self.y + step_y, PLAYER_RADIUS):
            self.y += step_y
        if dt > 0:
            self.vx = (self.x - old_x) / dt
            self.vy = (self.y - old_y) / dt


def player_cell(player):
    return world_to_cell(player.x, player.y)
