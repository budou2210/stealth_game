"""画面なしでゲームを進めるシミュレーター。

1フレームの進め方（update_play など）は、ゲーム本体の StealthGame の処理をそのまま借りる。
こうしておけば、本物のゲームと動きがずれにくい（tests/test_hell_bot.py で一致を確かめている）。
状態は snapshot() でまるごと保存でき、restore() で何度でもやり直せる（乱数の状態も含む）。
"""

import copy
import random

from stealth_game.app.game import StealthGame
from stealth_game.constants import HELPER_MAX_HELD
from stealth_game.difficulty import HELL
from stealth_game.items import pick_item_cells
from stealth_game.layout import PLAYER_START
from stealth_game.player import Player
from stealth_game.world import World

DT = 1 / 30  # 1コマの秒数。ボットも記録の再生もこの間隔で進める

# StealthGame から借りる処理（Panda3Dの描画を使わないものだけ）
BORROWED = [
    "update_play", "read_input", "update_safe_zone", "collect_items", "update_helpers",
    "update_cloak", "helper_kinds", "has_all_items", "is_hunting_phase", "remaining_item_cells",
    "wander_foci", "alert_allies", "share_alerts", "check_caught", "check_exit_reached",
    "make_guards", "play_event_sounds",
]


class _NoNode:
    """描画用のノードの代わり（色を変えても何もしない）。"""

    def setColor(self, *args):
        pass


class Sim:
    def __init__(self, seed, cfg=HELL, world=None):
        """seed の乱数で、ゲームを始めた直後の状態を作る（本物の start_game と同じ順番で乱数を使う）。"""
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
        self.held = {kind: 0 for kind in HELPER_MAX_HELD}
        self.helper_pickups = {kind: None for kind in HELPER_MAX_HELD}
        self.notice_timer = 0.0
        self.cloak_timer = 0.0
        self.placed_decoys = []
        self.exit_np = _NoNode()
        self.player = Player()
        self.player.reset(PLAYER_START)
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
        random.setstate(self.rng_state)
        self.update_play(DT)
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
