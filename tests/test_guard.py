"""鬼（Guard）の知覚と状態のテスト。"""

import math

from test_world import find_straight_run, find_wall_between

from stealth_game.constants import STUN_TIME_SEEN
from stealth_game.difficulty import HELL, NORMAL
from stealth_game.grid import cell_center
from stealth_game.guard import Guard
from stealth_game.player import Player


def place(world, cfg, guard_cell, player_cell, heading=0.0):
    guard = Guard(world, cfg, spawn=guard_cell)
    guard.heading = heading
    player = Player()
    player.x, player.y = cell_center(player_cell)
    player.safe = False
    return guard, player


def test_sees_player_in_front(world):
    run = find_straight_run(world, 5)
    guard, player = place(world, NORMAL, run[0], run[4], heading=0.0)  # 右（+x）を向く
    assert guard.check_sees(player)


def test_does_not_see_player_behind(world):
    run = find_straight_run(world, 5)
    guard, player = place(world, NORMAL, run[0], run[4], heading=math.pi)  # 反対を向く
    assert not guard.check_sees(player)


def test_does_not_see_through_wall(world):
    left, right = find_wall_between(world)
    guard, player = place(world, HELL, left, right, heading=0.0)
    assert not guard.check_sees(player)


def test_safe_or_invisible_player_is_not_seen(world):
    run = find_straight_run(world, 5)
    guard, player = place(world, NORMAL, run[0], run[2])
    player.safe = True
    assert not guard.check_sees(player)
    player.safe = False
    player.invisible = True
    assert not guard.check_sees(player)


def test_sneaking_shortens_view(world):
    run = find_straight_run(world, 10)
    guard, player = place(world, NORMAL, run[0], run[7])  # 7マス先（視界8、忍び足だと5.2）
    assert guard.check_sees(player)
    player.sneaking = True
    assert not guard.check_sees(player)


def test_hears_running_but_not_sneaking(world):
    run = find_straight_run(world, 5)
    guard, player = place(world, HELL, run[0], run[3], heading=math.pi)
    player.moving = True
    assert guard.check_hears(player)
    player.sneaking = True
    assert not guard.check_hears(player)


def test_wall_muffles_footsteps(world):
    """壁越しの足音は届く距離が半分になる（普通の2.5なら、壁の向こう2マスには届かない）。"""
    left, right = find_wall_between(world)
    guard, player = place(world, NORMAL, left, right, heading=math.pi)
    player.moving = True
    assert not guard.check_hears(player)
    run = find_straight_run(world, 3)
    guard, player = place(world, NORMAL, run[0], run[2], heading=math.pi)
    player.moving = True
    assert guard.check_hears(player), "同じ距離でも壁がなければ聞こえる"


def test_flanker_role(world):
    """挟み撃ちで回り込むのは、2番手以降で、プレイヤーから5マスより遠い鬼だけ。"""
    run = find_straight_run(world, 8)
    guard, _ = place(world, HELL, run[0], run[0])
    guard.chase_role = 1
    guard.last_known = run[5]
    assert not guard.is_flanker(), "5マスちょうどは回り込まない"
    guard.last_known = run[6]
    assert guard.is_flanker()
    guard.chase_role = 0
    assert not guard.is_flanker(), "一番近い鬼はまっすぐ追う"
    normal_guard, _ = place(world, NORMAL, run[0], run[0])
    normal_guard.chase_role = 1
    normal_guard.last_known = run[6]
    assert not normal_guard.is_flanker(), "挟み撃ちのない難易度では回り込まない"


def test_alert_rises_to_chase(world):
    run = find_straight_run(world, 5)
    guard, player = place(world, HELL, run[0], run[3])
    for _ in range(120):
        guard.update(1 / 60, player)
        if guard.state == Guard.CHASE:
            break
    assert guard.state == Guard.CHASE
    assert guard.exclaim_timer > 0, "見つけたら「！」を出す"


def test_stun_freezes_then_investigates(world):
    run = find_straight_run(world, 5)
    guard, player = place(world, NORMAL, run[0], run[3])
    guard.stun(player, STUN_TIME_SEEN)
    start = (guard.x, guard.y)
    for _ in range(int(STUN_TIME_SEEN * 60) - 1):
        guard.update(1 / 60, player)
        assert (guard.x, guard.y) == start, "目がくらんでいる間は動かない"
        assert not guard.sees_player
    for _ in range(5):
        guard.update(1 / 60, player)
    assert not guard.is_stunned()
