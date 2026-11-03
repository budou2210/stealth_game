"""難易度の値が、docs/design.md の仕様表どおりかを確かめる。

数値を意図して変えたときは、仕様表とこのテストの両方を直す。
"""

import math

import pytest

from stealth_game.difficulty import DIFFICULTIES, EASY, HARD, HELL, NORMAL, VERY_HARD

# 仕様表の行: (項目, 簡単, 普通, 難しい, 激ムズ, 地獄)
SPEC = [
    ("view_range", 8, 8, 9, 10, 10),
    ("view_angle_deg", 70, 70, 75, 80, 80),
    ("sneak_view_rate", 0.65, 0.65, 0.72, 0.8, 0.8),
    ("alert_gain", 1, 1, 1.6, 1.6, 1.6),
    ("hear_radius", 2.5, 2.5, 3, 6.5, 6.5),
    ("chase_speed", 3.1, 3.1, 3.96, 3.96, 4.4),
    ("search_speed", 2.8, 2.8, 3.2, 3.2, 3.2),
    ("spot_delay", 0.5, 0.5, 0.5, 0.5, 0.0),
    ("ally_alert_radius", 0, 0, 8, 16, 16),
    ("ally_alert_max", 0, 0, 2, 0, 0),
    ("flank_avoid_cost", 0, 0, 0, 6, 6),
    ("focus_rate", 0, 0, 0.1, 0.3, 0.3),
    ("hunt_after_all_items", False, False, True, True, True),
    ("wanderers", False, True, True, True, True),
    ("lives", 3, 2, 1, 1, 1),
    ("cloak", True, True, True, True, False),
    ("flash", True, True, False, False, False),
    ("decoy_radius", 16, 16, 16, 16, 0),
]
LEVELS = [EASY, NORMAL, HARD, VERY_HARD, HELL]


def value_of(cfg, name):
    if name == "view_angle_deg":
        return math.degrees(cfg.view_half_angle) * 2
    return getattr(cfg, name)


@pytest.mark.parametrize("row", SPEC, ids=[row[0] for row in SPEC])
def test_matches_spec_table(row):
    name, *expected = row
    actual = [value_of(cfg, name) for cfg in LEVELS]
    assert actual == pytest.approx(expected)


def test_menu_order():
    assert [cfg.key for cfg in DIFFICULTIES] == ["easy", "normal", "hard", "very_hard", "hell"]
