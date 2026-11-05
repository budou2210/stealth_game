"""ゲーム全体を、乱数とボットの入力を固定して動かすテスト。

- 各難易度で、例外が出ずに最後まで動くこと
- 鬼の動きが以前と変わっていないこと（指紋 = 毎フレームの状態から作ったハッシュ値）

鬼のAIや数値を意図して変えたときは test_behavior_is_unchanged が失敗するので、
失敗メッセージに出る新しい指紋で FINGERPRINTS を書き換える。
"""

import hashlib
import random

import pytest

from stealth_game.difficulty import DIFFICULTIES

FRAMES = 1800  # 30秒分

# 難易度ごとの (乱数の種, 指紋)。種は、30秒のうちに追跡と捕獲が起きるものを選んである。
# 指紋は、鬼の動き・お助けアイテム・捕獲などが少しでも変わると値が変わる
EXPECTED = {
    "easy": (31, "5f1f4bf3bba0720b"),
    "normal": (2, "775565e8cc7b0808"),
    "hard": (5, "f1d190c9e1a9e206"),
    "very_hard": (5, "ac6b49aecc9010b3"),
    "hell": (2, "555f4332c6abb6b3"),
    "transcend": (1, "cdedb25ebc3e7764"),
}


def make_game(game_class, cfg, seed):
    random.seed(seed)
    game = game_class()
    game.down = set()
    game.is_down = lambda name: name in game.down
    game.start_game(cfg)
    return game


def bot_step(bot, game, frame):
    """20フレームごとに向きを変え、ときどき忍び足やお助けアイテムを使う。"""
    if frame % 20 == 0:
        h = bot.choice(["up", "down", "left", "right", None])
        v = bot.choice(["up", "down", "left", "right", None])
        game.down = {k for k in (h, v) if k}
        if bot.random() < 0.3:
            game.down.add("sneak")
        for key in ("cloak", "flash", "decoy", "overview"):
            if bot.random() < 0.05:
                game.down.add(key)
    elif frame % 20 == 3:
        game.down -= {"cloak", "flash", "decoy", "overview"}


def snapshot(game):
    p = game.player
    guards = tuple(
        (round(g.x, 6), round(g.y, 6), g.state, round(g.alert, 6), round(g.stun_timer, 6), tuple(g.path))
        for g in game.guards
    )
    snap = (game.state, round(p.x, 6), round(p.y, 6), game.lives, tuple(sorted(game.items_collected)),
            tuple(game.item_cells), tuple(sorted(game.held.items())), round(game.cloak_timer, 6), guards)
    if game.timed_doors or game.cameras or game.noisy_floors:  # 超越の仕掛け（ほかの難易度の指紋は変えない）
        devices = (tuple(sorted(game.world.timed_closed)), game.camera_alarms,
                   tuple(round(c, 6) for c in game.floor_cooldowns), tuple(tuple(sorted(f)) for f in game.noisy_floors))
        snap = snap[:-1] + (devices, guards)
    return snap


def run(game_class, cfg, seed, frames=FRAMES):
    """ボットで遊ばせ、(指紋, 出てきた状態の集合) を返す。負けたらその場でリスタートする。"""
    game = make_game(game_class, cfg, seed)
    bot = random.Random(seed * 7 + 1)
    digest = hashlib.sha256()
    seen = set()
    for frame in range(frames):
        bot_step(bot, game, frame)
        if game.state in ("win", "lose"):
            game.restart_game()
        if game.state == "play":
            game.update_play(1 / 60)
        elif game.state == "caught":
            game.update_caught(1 / 60)
        game.poll_action_keys()
        game.update_hud()
        snap = snapshot(game)
        seen.add(snap[0])
        seen.update(g[2] for g in snap[-1])
        digest.update(repr(snap).encode())
    return digest.hexdigest()[:16], seen


@pytest.mark.parametrize("cfg", DIFFICULTIES, ids=[cfg.key for cfg in DIFFICULTIES])
def test_behavior_is_unchanged(game_class, cfg):
    seed, expected = EXPECTED[cfg.key]
    fingerprint, seen = run(game_class, cfg, seed)
    assert fingerprint == expected, (
        f"{cfg.key} の鬼の動きが変わった。意図した変更なら EXPECTED['{cfg.key}'] の指紋を "
        f"'{fingerprint}' に書き換える"
    )
    # 指紋が合っていても、追跡や捕獲まで動かせていなければ確認として弱い
    assert "chase" in seen
    assert {"caught", "lose"} & seen


def test_same_seed_gives_same_result(game_class):
    """乱数の種が同じなら、毎回まったく同じ展開になる（指紋テストの前提）。"""
    cfg = DIFFICULTIES[-1]
    assert run(game_class, cfg, 2, frames=300) == run(game_class, cfg, 2, frames=300)
