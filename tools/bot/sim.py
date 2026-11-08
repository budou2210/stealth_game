"""画面なしでゲームを進めるシミュレーター。

1フレームの進め方（update_play など）は、ゲーム本体の StealthGame の処理をそのまま借りる。
こうしておけば、本物のゲームと動きがずれにくい（tests/test_bot.py で一致を確かめている）。
状態は snapshot() でまるごと保存でき、restore() で何度でもやり直せる（乱数の状態も含む）。
"""

import copy
import random

from stealth_game.app.game import StealthGame
from stealth_game.constants import HELPER_MAX_HELD, SIM_DT
from stealth_game.items import pick_item_cells
from stealth_game.layout import PLAYER_START
from stealth_game.player import Player
from stealth_game.world import World

from .levels import level_cfg

DT = SIM_DT  # 1コマの秒数。ボットも記録の再生もこの間隔で進める

# StealthGame から借りる処理（Panda3Dの描画を使わないものだけ）
BORROWED = [
    "update_play", "read_input", "update_safe_zone", "collect_items", "update_helpers",
    "update_cloak", "helper_kinds", "has_all_items", "is_hunting_phase", "remaining_item_cells",
    "wander_foci", "alert_allies", "share_alerts", "check_caught", "check_exit_reached",
    "make_guards", "play_event_sounds",
    # 超越の仕掛け
    "setup_devices", "door_occupied", "update_timed_doors", "play_door_sound", "update_noisy_floors",
    "sound_floor", "update_cameras", "camera_alarm",
]


class _NoNode:
    """描画用のノードの代わり（色を変えても何もしない）。"""

    def setColor(self, *args):
        pass


class Sim:
    def __init__(self, seed, cfg=None, world=None):
        """seed の乱数で、ゲームを始めた直後の状態を作る（本物の start_game と同じ順番で乱数を使う）。
        cfg を省くと、--level で選んだ難易度（標準は地獄）。"""
        cfg = cfg or level_cfg()
        self.world = world or World()
        self.seed = seed
        random.seed(seed)
        self.difficulty = cfg
        self.guards = self.make_guards(cfg)
        self.state = "play"
        self.elapsed = 0.0
        self.lives = cfg.lives
        self.items_collected = set()
        self.collect_order = []
        self.item_cells = pick_item_cells(self.world)
        self.player = Player()
        self.player.reset(PLAYER_START)
        self.setup_devices()  # 鳴る床の場所は、本物と同じくアイテムの配置の後に乱数で選ぶ
        self.timed_closed = self.world.timed_closed
        self.held = {kind: 0 for kind in HELPER_MAX_HELD}
        self.helper_pickups = {kind: None for kind in HELPER_MAX_HELD}
        self.notice_timer = 0.0
        self.cloak_timer = 0.0
        self.placed_decoys = []
        self.exit_np = _NoNode()
        self.doors_closed = False
        for guard in self.guards:
            guard.reset()
        self.keys = set()  # 今押しているキー（"up" "down" "left" "right" "sneak"）
        self.rng_state = random.getstate()

    # --- 本物のゲームの代わりをする部分 ---------------------------------
    def is_down(self, name):
        return name in self.keys

    def play_sound(self, name, volume_rate=1.0):
        pass

    def add_ring(self, x, y, radius, color, alpha):
        pass

    def set_doors_closed(self, closed):
        self.doors_closed = closed
        self.world.doors_closed = closed

    def on_caught(self):
        self.state = "lose"

    def on_win(self):
        self.state = "win"

    # --- 進める・保存する -----------------------------------------------
    def step(self, keys):
        """keys を押した状態で1コマ進める。"""
        self.keys = set(keys)
        self.world.doors_closed = self.doors_closed  # World は保存した状態どうしで共有しているので、毎回合わせる
        self.world.timed_closed = self.timed_closed
        random.setstate(self.rng_state)
        self.update_play(DT)
        self.timed_closed = self.world.timed_closed
        self.rng_state = random.getstate()

    def snapshot(self):
        """今の状態のコピー（マップと難易度の設定は変わらないので共有する）。"""
        memo = {id(self.world): self.world, id(self.difficulty): self.difficulty}
        return copy.deepcopy(self, memo)

    @property
    def done(self):
        return self.state in ("win", "lose")


for _name in BORROWED:
    setattr(Sim, _name, getattr(StealthGame, _name))
