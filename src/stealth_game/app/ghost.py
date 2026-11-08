"""タイムアタックのリプレイに重ねる、ボットのゴースト（半透明の箱）。

リプレイ（クリア画面の V・難易度選択の画面の V）を始めるとき、同じ配置をボット（stealth_game/ghost.py）に解かせ、
その動きをリプレイの時間に合わせて動かす。ボットの動きは保存せず毎回計算する（同じ配置なら毎回同じ動き）。
同じ配置をくり返し再生するとき（R）は、計算した結果を使い回す。
"""

import math

from panda3d.core import TransparencyAttrib

from ..ghost import DT, best_run
from ..grid import cell_center
from ..layout import PLAYER_START

GHOST_CANDIDATES = 5  # ゲームの中では、比べる順番を5本に絞る（10本だと計算に約1秒かかる。5本で約0.6秒）
GHOST_COLOR = (0.55, 0.75, 1.0, 1)
GHOST_ALPHA = 0.45


class GhostMixin:
    def setup_ghost(self):
        self.ghost = None  # {"time": ボットのクリアの秒数, "poses": 各コマの後の (x, y, 向き)}
        self.ghost_cache = {}  # {アイテムの配置: ghost}
        self.ghost_np = self.render.attachNewNode("ghost")
        self.add_box(self.ghost_np, (-0.3, -0.3, 0), (0.6, 0.6, 0.9), GHOST_COLOR)
        self.add_box(self.ghost_np, (-0.12, 0.15, 0.55), (0.24, 0.3, 0.2), (0.9, 0.95, 1, 1))
        self.ghost_np.setTransparency(TransparencyAttrib.MAlpha)
        self.ghost_np.setAlphaScale(GHOST_ALPHA)
        self.ghost_np.setDepthWrite(False)  # 半透明の箱どうし・プレイヤーとの重なりで、奥のものが消えないように
        self.ghost_np.hide()

    def clear_ghost(self):
        self.ghost = None
        self.ghost_np.hide()

    def prepare_ghost(self):
        """タイムアタックのリプレイを始めるとき：今の配置をボットに解かせる（解けなければゴーストなし）。"""
        if not self.difficulty.time_attack or self.replay is None:
            self.clear_ghost()
            return
        key = tuple(self.item_cells)
        if key not in self.ghost_cache:
            run = best_run(self.world, self.item_cells, candidates=GHOST_CANDIDATES)
            self.ghost_cache[key] = {"time": run["time"], "poses": run["poses"]} if run["time"] is not None else None
        self.ghost = self.ghost_cache[key]
        if self.ghost is None:
            self.ghost_np.hide()
        else:
            self.ghost_np.show()

    def ghost_pose(self, elapsed):
        """経過時間 elapsed でのゴーストの (x, y, 向き)。コマの間は位置をなめらかにつなぐ。ゴールした後は止まる。"""
        poses = self.ghost["poses"]
        start = cell_center(PLAYER_START) + (math.pi / 2,)
        t = elapsed / DT  # poses[i] は i+1 コマ目の後
        i = int(math.floor(t))
        if i >= len(poses):
            return poses[-1]
        before = poses[i - 1] if i >= 1 else start
        after = poses[i]
        frac = t - i
        return (before[0] + (after[0] - before[0]) * frac, before[1] + (after[1] - before[1]) * frac, after[2])

    def update_ghost_view(self):
        if self.ghost is None:
            return
        x, y, heading = self.ghost_pose(self.elapsed)
        self.ghost_np.setPos(x, y, 0)
        self.ghost_np.setH(math.degrees(heading) - 90)

    def ghost_status(self):
        """状態の行に足す文字：ボットのタイム（ゴールした後）。"""
        if self.ghost is None:
            return ""
        if self.elapsed + 1e-9 >= self.ghost["time"]:
            return self.text["ghost_goal_status"].format(time=self.ghost["time"])
        return self.text["ghost_running_status"]

    def ghost_result(self):
        """リプレイの最後に出す、ボットとの差。"""
        if self.ghost is None:
            return ""
        return self.text["ghost_result"].format(bot=self.ghost["time"], diff=self.elapsed - self.ghost["time"])
