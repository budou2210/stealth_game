"""マス目ごとの危険度の地図。最初は人の見立て（PRIOR_REGIONS）から始め、挑戦の結果で上書きしていく。

危険度 = (失敗の数 + 見立て × PRIOR_WEIGHT) / (通った数 + PRIOR_WEIGHT)
結果が増えるほど、最初の見立ての影響は小さくなる。
"""

import json
import random

from stealth_game.grid import manhattan
from stealth_game.items import pick_item_cells
from stealth_game.layout import EXIT_CELL, MAP_H, MAP_W

# 最初の見立て（人の経験から）。値が大きいほど危ない。ここに入らない床は DEFAULT_PRIOR
_ROOM_X = list(range(12, 19)) + list(range(21, 28))
_ROOM_Y = list(range(1, 7)) + list(range(33, 39))
SEAM_DOOR_CELLS = {(x, y) for x in (19, 20) for y in (3, 4, 35, 36)}  # 中央の部屋どうしをつなぐ扉（両側から見張られる）
CENTER_ROOM_CELLS = {(x, y) for x in _ROOM_X for y in _ROOM_Y}  # 上段・下段の中央の部屋
TOP_LEFT_ROOM_CELLS = {(x, y) for x in range(1, 7) for y in range(33, 39)}  # 左上の隅の部屋（6×6）
PRIOR_REGIONS = [  # (マスの集まり, 見立ての危険度)。先に書いたものが優先
    (SEAM_DOOR_CELLS, 0.8),
    (CENTER_ROOM_CELLS, 0.5),
    (TOP_LEFT_ROOM_CELLS, 0.4),
]
DEFAULT_PRIOR = 0.15
PRIOR_WEIGHT = 4.0  # 見立てを「何回ぶんの結果」とみなすか
FAIL_SPREAD = 2  # 失敗した場所から、このマス数以内にも失敗を少し分ける
NEAR_EXIT = 10  # 出口からこの歩数以内にアイテムが1つもない配置は、選び分けで不利にする
NO_NEAR_EXIT_PENALTY = 1.5
EXPLORE_RATE = 0.15  # 選び分けで、ときどき点数を無視して試す割合（見立ての思い込みを直すため）


def prior_of(cell):
    for cells, value in PRIOR_REGIONS:
        if cell in cells:
            return value
    return DEFAULT_PRIOR


class DangerMap:
    def __init__(self):
        self.visits = {}  # {セル: 通った挑戦の数}
        self.fails = {}  # {セル: 失敗の重み}
        self.attempts = 0

    def danger(self, cell):
        prior = prior_of(cell)
        fails = self.fails.get(cell, 0.0)
        visits = self.visits.get(cell, 0)
        return (fails + prior * PRIOR_WEIGHT) / (visits + PRIOR_WEIGHT)

    def record(self, visited_cells, fail_cells):
        """1回の挑戦の結果。visited_cells＝通ったマス、fail_cells＝見つかった（捕まった）マスの列（巻き戻す前の失敗も含む）。"""
        self.attempts += 1
        for cell in set(visited_cells):
            self.visits[cell] = self.visits.get(cell, 0) + 1
        for cell in fail_cells:
            self.record_failure(cell)

    def record_failure(self, fail_cell):
        fx, fy = fail_cell
        for dx in range(-FAIL_SPREAD, FAIL_SPREAD + 1):
            for dy in range(-FAIL_SPREAD, FAIL_SPREAD + 1):
                d = abs(dx) + abs(dy)
                if d <= FAIL_SPREAD:
                    cell = (fx + dx, fy + dy)
                    self.fails[cell] = self.fails.get(cell, 0.0) + 1.0 / (1 + d)

    # --- 保存 -----------------------------------------------------------
    def save(self, path):
        data = {
            "attempts": self.attempts,
            "visits": [[x, y, n] for (x, y), n in self.visits.items()],
            "fails": [[x, y, n] for (x, y), n in self.fails.items()],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    @classmethod
    def load(cls, path):
        m = cls()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            m.attempts = data["attempts"]
            m.visits = {(x, y): n for x, y, n in data["visits"]}
            m.fails = {(x, y): n for x, y, n in data["fails"]}
        return m

    def all_cells(self):
        return [(x, y) for y in range(MAP_H) for x in range(MAP_W)]


def layout_score(danger_map, item_cells):
    """配置の点数（小さいほど有望）。アイテムのある場所の危険度の合計＋出口の近くにアイテムがないときの罰。"""
    score = sum(danger_map.danger(c) for c in item_cells)
    if not any(manhattan(c, EXIT_CELL) <= NEAR_EXIT for c in item_cells):
        score += NO_NEAR_EXIT_PENALTY
    return score


def items_for_seed(world, seed):
    """その種で始めたときのアイテムの配置（Sim と同じ順番で乱数を使う）。"""
    random.seed(seed)
    return pick_item_cells(world)


def choose_seed(world, danger_map, candidates, tried, rng):
    """まだ試していない種から、次に挑戦する種を選ぶ。ふだんは点数の一番よいもの、ときどきランダム。"""
    fresh = [s for s in candidates if s not in tried]
    if not fresh:
        return None
    if rng.random() < EXPLORE_RATE:
        return rng.choice(fresh)
    return min(fresh, key=lambda s: layout_score(danger_map, items_for_seed(world, s)))
