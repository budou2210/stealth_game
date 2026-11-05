"""理論値の仕掛け（見張り番・監視カメラ・時間で開け閉めする扉・鳴る床）のテスト。"""

import math
import random

import pytest

from stealth_game.constants import (
    CAMERA_CALL_RADIUS,
    CAMERA_VIEW_RANGE,
    DOOR_OPEN_RATE,
    DOOR_PERIOD,
    FLOOR_COOLDOWN,
    FLOOR_RUN_RADIUS,
    FLOOR_SNEAK_RADIUS,
    SENTRY_DWELL,
)
from stealth_game.devices import (
    build_cameras,
    build_sentry_posts,
    build_timed_doors,
    noisy_floor_candidates,
    pick_noisy_floors,
)
from stealth_game.difficulty import DIFFICULTIES, HELL, THEORY
from stealth_game.grid import cell_center
from stealth_game.guard import Guard
from stealth_game.layout import EXIT_CELL, PLAYER_START
from stealth_game.player import Player

DT = 1 / 30


def started_game(game_class, cfg=THEORY, seed=1):
    random.seed(seed)
    game = game_class()
    game.keys = set()
    game.is_down = lambda name: name in game.keys
    game.start_game(cfg)
    return game


def put_player(game, cell, sneaking=False):
    game.player.x, game.player.y = cell_center(cell)
    game.player.safe = False
    game.player.sneaking = sneaking


# --- 置き場所 -------------------------------------------------------------
def test_devices_sit_on_floor(world):
    for post, _ in build_sentry_posts():
        assert not world.walls[post[1]][post[0]]
    for camera in build_cameras():
        assert not world.is_wall_at(camera.x, camera.y)
    for door in build_timed_doors():
        assert len(door.cells) == 4
        assert all(not world.walls[y][x] for x, y in door.cells)


def test_noisy_floor_candidates(world):
    candidates = noisy_floor_candidates(world)
    timed = set().union(*(d.cells for d in build_timed_doors()))
    assert len(candidates) == 32
    for cells in candidates:
        assert not cells & timed  # 時間で開け閉めする扉とは重ならない
        assert not cells & world.safe_cells
    near_start = [c for c in candidates if min(abs(x - 7) + abs(y - 3) for x, y in c) == 0]
    assert not near_start  # スタート部屋の東の扉は候補にしない


def test_noisy_floors_change_by_seed(world):
    random.seed(1)
    first = pick_noisy_floors(world, 6)
    random.seed(2)
    second = pick_noisy_floors(world, 6)
    assert len(first) == len(set(first)) == 6
    assert first != second


def test_only_theory_has_devices(game_class):
    for cfg in DIFFICULTIES:
        game = started_game(game_class, cfg)
        has = cfg is THEORY
        assert bool(game.cameras) == has
        assert bool(game.timed_doors) == has
        assert bool(game.noisy_floors) == has
        assert any(g.is_sentry() for g in game.guards) == has


# --- 見張り番 -------------------------------------------------------------
def test_sentry_turns_in_place(world):
    post, look = build_sentry_posts()[0]
    guard = Guard(world, THEORY, route=[post], look=look)
    player = Player()
    player.reset(PLAYER_START)  # 安全地帯にいて、見つからない
    headings = []
    for frame in range(int(SENTRY_DWELL * 4 / DT) + 1):
        guard.update(DT, player)
        if frame % int(SENTRY_DWELL / DT) == int(SENTRY_DWELL / DT) // 2:  # 1つの向きを見ている途中
            headings.append(round(math.degrees(guard.heading) % 360))
    assert guard.cell() == post
    assert headings == [round(math.degrees(a) % 360) for a in look]


# --- 監視カメラ -----------------------------------------------------------
def straight_ahead_cell(camera, distance):
    return int(camera.x + math.cos(camera.center) * distance), int(camera.y + math.sin(camera.center) * distance)


def test_camera_sees_in_front_but_not_too_far(world):
    camera = build_cameras()[0]
    t = 0.0  # 周期のずれ0の台は、時刻0にちょうど中心を向く
    player = Player()
    player.safe = False
    player.x, player.y = cell_center(straight_ahead_cell(camera, 2.5))
    assert camera.sees(world, player, THEORY, t)
    player.sneaking = True  # 忍び足でも、この距離なら映る
    assert camera.sees(world, player, THEORY, t)
    angle = camera.center
    for dist in (CAMERA_VIEW_RANGE * THEORY.sneak_view_rate + 0.1, CAMERA_VIEW_RANGE + 0.1):
        player.x, player.y = camera.x + math.cos(angle) * dist, camera.y + math.sin(angle) * dist
        assert not camera.sees(world, player, THEORY, t)  # 忍び足の距離・ふつうの距離の外
        player.sneaking = False


def test_camera_does_not_see_outside_its_angle(world):
    camera = build_cameras()[0]
    player = Player()
    player.safe = False
    side = camera.center + math.radians(30)  # 視界（中心から22°）の少し外。部屋の中の床
    player.x, player.y = camera.x + math.cos(side) * 3, camera.y + math.sin(side) * 3
    assert not world.is_wall_at(player.x, player.y)
    assert not camera.sees(world, player, THEORY, 0.0)


def test_camera_alarm_calls_nearby_guards(game_class):
    game = started_game(game_class)
    camera = game.cameras[0]
    put_player(game, straight_ahead_cell(camera, 2.5))
    game.elapsed = 0.0
    game.update_cameras(DT)
    assert game.camera_alarms == 1
    near = [g for g in game.guards if g.distance_to(camera.x, camera.y) <= CAMERA_CALL_RADIUS]
    assert near and all(g.state == Guard.SEARCH for g in near)
    game.update_cameras(DT)  # 鳴った直後は、続けて鳴らない
    assert game.camera_alarms == 1


# --- 時間で開け閉めする扉 ----------------------------------------------------
def test_timed_door_schedule():
    door = build_timed_doors()[0]  # 周期のずれ0
    assert not door.wants_closed(0.0)
    assert not door.wants_closed(DOOR_PERIOD * DOOR_OPEN_RATE - 0.01)
    assert door.wants_closed(DOOR_PERIOD * DOOR_OPEN_RATE + 0.01)
    assert not door.wants_closed(DOOR_PERIOD + 0.01)


def test_closed_door_blocks_movement_and_sight(game_class):
    game = started_game(game_class)
    door = game.timed_doors[0]
    game.elapsed = DOOR_PERIOD * DOOR_OPEN_RATE + 0.1
    game.update_timed_doors()
    assert door.closed
    cell = min(door.cells)
    assert game.world.is_wall(*cell)
    game.elapsed = DOOR_PERIOD + 0.1
    game.update_timed_doors()
    assert not door.closed
    assert not game.world.is_wall(*cell)


def test_door_stays_open_while_someone_is_on_it(game_class):
    game = started_game(game_class)
    door = game.timed_doors[0]
    put_player(game, min(door.cells))
    game.elapsed = DOOR_PERIOD * DOOR_OPEN_RATE + 0.1
    game.update_timed_doors()
    assert not door.closed  # プレイヤーが扉の上にいる間は閉めない
    put_player(game, EXIT_CELL)
    game.update_timed_doors()
    assert door.closed


def test_guard_waits_at_closed_door(world):
    door = build_timed_doors()[0]
    cells = sorted(door.cells)
    before = (cells[0][0] - 1, cells[0][1])
    guard = Guard(world, HELL, spawn=before)
    guard.path = [cells[0]]
    world.timed_closed = door.cells
    try:
        guard.move_along_path(1.0)
        assert guard.cell() == before
    finally:
        world.timed_closed = frozenset()


# --- 鳴る床 -------------------------------------------------------------
def floor_test_game(game_class):
    game = started_game(game_class)
    for guard in game.guards:  # 鬼を床からの距離がばらばらになる場所に置き直す
        guard.state = Guard.PATROL
    return game


def step_onto_floor(game, sneaking):
    cells = sorted(game.noisy_floors[0])
    outside = (cells[0][0] - 1, cells[0][1]) if not game.world.is_wall(cells[0][0] - 1, cells[0][1]) else (
        cells[0][0], cells[0][1] - 1)
    put_player(game, outside, sneaking)
    game.update_noisy_floors(DT)
    put_player(game, cells[0], sneaking)
    game.player.moving = True
    game.update_noisy_floors(DT)
    return cells[0]


@pytest.mark.parametrize("sneaking, radius", [(False, FLOOR_RUN_RADIUS), (True, FLOOR_SNEAK_RADIUS)])
def test_floor_calls_guards_within_radius(game_class, sneaking, radius):
    game = floor_test_game(game_class)
    cell = step_onto_floor(game, sneaking)
    x, y = cell_center(cell)
    for guard in game.guards:
        called = guard.state == Guard.SEARCH and guard.last_known == cell
        assert called == (guard.distance_to(x, y) <= radius)


def test_floor_sounds_only_when_stepping_on(game_class):
    game = floor_test_game(game_class)
    step_onto_floor(game, False)
    assert game.floor_cooldowns[0] == FLOOR_COOLDOWN
    for guard in game.guards:
        guard.state = Guard.PATROL
    game.update_noisy_floors(DT)  # 乗ったままでは鳴らない
    assert all(g.state == Guard.PATROL for g in game.guards)
    step_onto_floor(game, False)  # 降りて乗り直しても、しばらくは鳴らない
    assert all(g.state == Guard.PATROL for g in game.guards)
