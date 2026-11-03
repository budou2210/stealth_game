"""アイテムの配置（毎回ランダム。各区画にITEMS_PER_QUADRANT個ずつ）。"""

import random

from .constants import (
    ITEM_MIN_DISTANCE_FROM_EXIT,
    ITEM_MIN_DISTANCE_FROM_START,
    ITEM_MIN_SPACING,
    ITEMS_PER_QUADRANT,
)
from .grid import manhattan
from .layout import BASE_SIZE, EXIT_CELL, PLAYER_START, QUADRANTS


def quadrant_of(cell):
    return int(cell[0] >= BASE_SIZE), int(cell[1] >= BASE_SIZE)


def is_valid_item_cell(cell):
    if manhattan(cell, PLAYER_START) < ITEM_MIN_DISTANCE_FROM_START:
        return False
    return manhattan(cell, EXIT_CELL) >= ITEM_MIN_DISTANCE_FROM_EXIT


def pick_spread_cells(candidates, count, taken):
    """candidatesから、互いに離れたセルをcount個選ぶ。足りなければ残りから補う。"""
    chosen = []
    for cell in candidates:
        far = all(manhattan(cell, other) >= ITEM_MIN_SPACING for other in taken + chosen)
        if far:
            chosen.append(cell)
        if len(chosen) == count:
            return chosen
    leftovers = [c for c in candidates if c not in chosen]
    return chosen + leftovers[: count - len(chosen)]


def pick_item_cells(world):
    taken = []
    for quadrant in QUADRANTS:
        candidates = [
            c
            for c in world.floor_cells
            if quadrant_of(c) == quadrant and is_valid_item_cell(c)
        ]
        random.shuffle(candidates)
        taken += pick_spread_cells(candidates, ITEMS_PER_QUADRANT, taken)
    return taken
