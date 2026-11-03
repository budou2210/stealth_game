"""アイテム配置のテスト。"""

import random
from collections import Counter

import pytest

from stealth_game.constants import ITEMS_PER_QUADRANT
from stealth_game.items import is_valid_item_cell, pick_item_cells, quadrant_of
from stealth_game.layout import QUADRANTS


@pytest.mark.parametrize("seed", range(10))
def test_items_are_spread_over_quadrants(world, seed):
    random.seed(seed)
    cells = pick_item_cells(world)
    assert len(cells) == ITEMS_PER_QUADRANT * len(QUADRANTS)
    assert len(set(cells)) == len(cells), "同じマスに2個置かない"
    counts = Counter(quadrant_of(c) for c in cells)
    assert all(counts[q] == ITEMS_PER_QUADRANT for q in QUADRANTS)
    floor = set(world.floor_cells)
    for cell in cells:
        assert cell in floor
        assert is_valid_item_cell(cell), "スタート・出口から離す"
