"""理論値の仕掛け（監視カメラ・時間で開け閉めする扉・鳴る床）の進行。見張り番は鬼として動く。

ここにはPanda3Dを使う処理を書かない（ボットのシミュレーターも、この処理をそのまま借りる）。
見た目は visuals.py の build_device_views / update_device_views。
"""

from ..constants import (
    CAMERA_ALARM_COOLDOWN,
    CAMERA_CALL_RADIUS,
    FLOOR_COOLDOWN,
    FLOOR_RUN_RADIUS,
    FLOOR_SNEAK_RADIUS,
    PLAYER_RADIUS,
)
from ..devices import build_cameras, build_timed_doors, pick_noisy_floors
from ..grid import cell_center, world_to_cell
from ..player import player_cell
from ..theme import CAMERA_RING_COLOR, FLOOR_RING_COLOR

GUARD_BODY_RADIUS = 0.35  # 扉を閉めてよいかの判定に使う、鬼の体の半分の幅


def body_cells(x, y, radius):
    """半径radiusの四角形が掛かっているセル。"""
    return {world_to_cell(x + dx, y + dy) for dx in (-radius, radius) for dy in (-radius, radius)}


class DevicesMixin:
    """理論値の仕掛け。ほかの難易度では、どれも空のまま何もしない。"""

    def setup_devices(self):
        """ゲームを始めるときに作る。鳴る床の場所はここで乱数で選ぶ（アイテムの配置の後）。"""
        cfg = self.difficulty
        self.cameras = build_cameras() if cfg.cameras else []
        self.camera_cooldowns = [0.0] * len(self.cameras)
        self.camera_alarm_timers = [0.0] * len(self.cameras)  # 見た目：鳴った直後は赤く点滅する
        self.camera_alarms = 0  # カメラが鳴った回数（ボットが「映った」ことを知るのに使う）
        self.timed_doors = build_timed_doors() if cfg.timed_doors else []
        self.noisy_floors = pick_noisy_floors(self.world, cfg.noisy_floors) if cfg.noisy_floors else []
        self.floor_cooldowns = [0.0] * len(self.noisy_floors)
        self.floor_under = None  # 今乗っている鳴る床の番号
        self.world.timed_closed = frozenset()
        self.update_timed_doors()

    # --- 時間で開け閉めする扉 ------------------------------------------------
    def door_occupied(self, door):
        """扉のセルに、プレイヤーか鬼の体が掛かっているか（掛かっている間は閉めない）。"""
        if body_cells(self.player.x, self.player.y, PLAYER_RADIUS) & door.cells:
            return True
        return any(body_cells(g.x, g.y, GUARD_BODY_RADIUS) & door.cells for g in self.guards)

    def update_timed_doors(self):
        """時刻に合わせて開け閉めする。閉まる時刻でも、誰かが扉の上にいる間は開けたままにする。"""
        if not self.timed_doors:
            return
        closed = set()
        for door in self.timed_doors:
            if not door.wants_closed(self.elapsed):
                door.closed = False
            elif not door.closed and not self.door_occupied(door):
                door.closed = True
                self.play_door_sound(door)
            if door.closed:
                closed |= door.cells
        self.world.timed_closed = frozenset(closed)

    def play_door_sound(self, door):
        """近くの扉が閉まったときだけ音を出す（遠くの扉の音まで鳴らすと、うるさいので）。"""
        x, y = cell_center(min(door.cells))
        if abs(x - self.player.x) + abs(y - self.player.y) <= 12:
            self.play_sound("door", 0.6)

    # --- 鳴る床 -------------------------------------------------------------
    def update_noisy_floors(self, dt):
        """鳴る床に乗った瞬間に音を出す。同じ床は、鳴ってからしばらく鳴らない。"""
        if not self.noisy_floors:
            return
        self.floor_cooldowns = [max(0.0, c - dt) for c in self.floor_cooldowns]
        here = player_cell(self.player)
        under = next((i for i, cells in enumerate(self.noisy_floors) if here in cells), None)
        if under is not None and under != self.floor_under and self.floor_cooldowns[under] <= 0:
            self.sound_floor(under, here)
        self.floor_under = under

    def sound_floor(self, index, cell):
        """走って乗ると遠くまで、忍び足だと近くまで音が届く。届いた鬼は、その場所を調べに来る（音の罠と同じ）。"""
        radius = FLOOR_RUN_RADIUS if not self.player.sneaking else FLOOR_SNEAK_RADIUS
        x, y = cell_center(cell)
        for guard in self.guards:
            if guard.distance_to(x, y) <= radius:
                guard.hear_decoy(cell)
        self.floor_cooldowns[index] = FLOOR_COOLDOWN
        self.add_ring(x, y, radius, FLOOR_RING_COLOR, 0.35)
        self.play_sound("decoy_fire", 0.8 if radius >= FLOOR_RUN_RADIUS else 0.4)

    # --- 監視カメラ -----------------------------------------------------------
    def update_cameras(self, dt):
        """カメラに映ったら、近くの鬼が映った場所を調べに来る。鳴ったカメラは、しばらく鳴らない。"""
        for i, camera in enumerate(self.cameras):
            self.camera_cooldowns[i] = max(0.0, self.camera_cooldowns[i] - dt)
            self.camera_alarm_timers[i] = max(0.0, self.camera_alarm_timers[i] - dt)
            if self.camera_cooldowns[i] > 0:
                continue
            if camera.sees(self.world, self.player, self.difficulty, self.elapsed):
                self.camera_alarm(i, camera)

    def camera_alarm(self, index, camera):
        cell = player_cell(self.player)
        for guard in self.guards:
            if guard.distance_to(camera.x, camera.y) <= CAMERA_CALL_RADIUS:
                guard.hear_decoy(cell)
        self.camera_cooldowns[index] = CAMERA_ALARM_COOLDOWN
        self.camera_alarm_timers[index] = CAMERA_ALARM_COOLDOWN
        self.camera_alarms += 1
        self.add_ring(camera.x, camera.y, CAMERA_CALL_RADIUS, CAMERA_RING_COLOR, 0.3)
        self.play_sound("spotted")
