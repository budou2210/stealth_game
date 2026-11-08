"""タイムアタックの攻略ボット（鬼がいないので「8個のアイテムを集めて出口へ行く一番速い順番と道」を探すだけ）。

使い方（プロジェクトのフォルダで）:
    uv run python -m tools.bot.time_attack --seed 5           （種5の配置を1つ解く）
    uv run python -m tools.bot.time_attack --seeds 0-99       （種0〜99をまとめて解き、平均と最速を出す）
    uv run python -m tools.bot.play_record bot_results/time_attack/wins/seed_5.json   （本物の画面で再生）

道・順番・動かし方は、ゲームの中のゴーストと同じもの（stealth_game/ghost.py。計算の流れと工夫はそちらに書いた）。
ここでは、それに「仕上げ」を足す：残した入力を少しずつ変え（コマの入れ替え・逆向きの2コマを抜く・1コマ抜く）、
本物と同じ処理のシミュレーターで確かめて、速くなれば採る（--refine-seconds 秒まで）。
途中の状態を15コマごとに取っておき、変えたコマの手前から動かし直す。
"""

import argparse
import json
import random
import time
from pathlib import Path

from stealth_game.difficulty import TIME_ATTACK
from stealth_game.exact_route import SAMPLES, STRICT_RADIUS, solve_exact, strict_lower_bound
from stealth_game.ghost import DIRECTIONS, best_run, drive_through, keys_of
from stealth_game.world import World

from .levels import RESULTS_ROOT
from .planner import decode_keys, encode_keys
from .sim import DT, Sim

DEFAULT_CUTOFF = 24.5  # 足切りの秒数の初期値。2000配置の厳密な下限で、24.5秒未満が24.3%（上位20〜30%を残す）。README の「足切り」
CHECKPOINT_EVERY = 15  # 仕上げで取っておく途中の状態の間隔（コマ）
RESULTS = RESULTS_ROOT / "time_attack"


# --- 仕上げ（入力を直接ずらして縮める） ------------------------------------------
def run_log(sim, log, start, give_up):
    """sim（start コマ目の直前の状態）から log[start:] を流す。戻り値 (クリアまでのコマ数 または None, 拾ったコマの合計)。"""
    picked = 0
    have = len(sim.items_collected)
    for f in range(start, len(log)):
        sim.step(log[f])
        if len(sim.items_collected) != have:
            picked += f * (len(sim.items_collected) - have)
            have = len(sim.items_collected)
        if sim.state == "win":
            return f + 1, picked
        if f + 1 >= give_up:
            return None, picked
    return None, picked


def checkpoints(seed, world, log):
    """log を流しながら、CHECKPOINT_EVERY コマごとの状態と、それまでに拾ったコマの合計を取っておく。"""
    sim = Sim(seed, cfg=TIME_ATTACK, world=world)
    saved = {}
    picked, have = 0, 0
    for f, keys in enumerate(log):
        if f % CHECKPOINT_EVERY == 0:
            saved[f] = (sim.snapshot(), picked)
        sim.step(keys)
        if len(sim.items_collected) != have:
            picked += f * (len(sim.items_collected) - have)
            have = len(sim.items_collected)
    return saved


OPPOSITE = {keys_of(dx, dy): keys_of(-dx, -dy) for dx, dy in DIRECTIONS}
RELOCATE_RANGE = 40  # 入れ替えで、抜いたコマを差し込む先の範囲（前後のコマ数）


def mutate(log, rng):
    """入力の記録を1か所変えたもの。戻り値 (新しい記録, 変えた一番前のコマ)。変えられなければ (None, 0)。

    1か所だけずらすと後の位置が全部ずれて、後のアイテムを拾い損ねる。なので、ずれが後に残らない変え方を主に使う：
    - 入れ替え：あるコマの向きを抜き、近くの別の場所に差し込む（両方を過ぎれば位置は元どおり。道の形だけ変わる）
    - 打ち消し：逆向きのコマを2つ抜く（位置は元どおりで、2コマ縮む）
    - 1コマ抜く：約0.15ずれるが、拾える範囲・出口の範囲に余裕があれば、そのまま1コマ縮む
    """
    n = len(log)
    roll = rng.random()
    if roll < 0.5:
        i = rng.randrange(n)
        j = min(n - 1, max(0, i + rng.randint(-RELOCATE_RANGE, RELOCATE_RANGE)))
        if i == j or log[i] == log[j]:
            return None, 0
        trial = log[:i] + log[i + 1:]
        trial.insert(j, log[i])
        return trial, min(i, j)
    if roll < 0.8:
        i = rng.randrange(n)
        lo, hi = max(0, i - RELOCATE_RANGE), min(n, i + RELOCATE_RANGE + 1)
        want = OPPOSITE.get(log[i])
        matches = [j for j in range(lo, hi) if log[j] == want]
        if not matches:
            return None, 0
        j = rng.choice(matches)
        a, b = sorted((i, j))
        return log[:a] + log[a + 1:b] + log[b + 1:], a
    i = rng.randrange(n)
    return log[:i] + log[i + 1:], i


def refine(seed, world, log, seconds, rng):
    """入力の記録 log（クリアできたもの）を、制限時間まで少しずつ変えて縮める。戻り値は新しい記録。"""
    deadline = time.perf_counter() + seconds
    frames = len(log)
    saved = checkpoints(seed, world, log)
    score = (frames, run_log(Sim(seed, cfg=TIME_ATTACK, world=world), log, 0, frames + 1)[1])
    while time.perf_counter() < deadline:
        trial, first = mutate(log, rng)
        if trial is None:
            continue
        base = first - first % CHECKPOINT_EVERY
        snap, picked = saved[base]
        done, later = run_log(snap.snapshot(), trial, base, score[0] + 1)
        if done is None:
            continue
        new = (done, picked + later)
        if new < score:
            log, score = trial[:done], new
            saved = checkpoints(seed, world, log)
    return log


# --- まとめ ---------------------------------------------------------------------
def solve(seed, candidates=10, margin=0.08, refine_seconds=3.0, world=None, exact_samples=SAMPLES, cutoff=None):
    """種 seed の配置を解く（道と動かし方は stealth_game/ghost.py のゴーストと同じ）。戻り値は結果の辞書（入力の記録つき）。

    - はじめに、どの順番でどう動かしても越えられない厳密な下限（exact_route.strict_lower_bound。約0.01秒）を出す。
      cutoff（秒）を渡すと、下限が cutoff 以上の配置は、ここで打ち切る（outcome "cut"）。
    - 動かした結果が cutoff 以上なら、仕上げと「選んだ順番での最短の道」の計算も省く（outcome は "win" のまま）。
    - exact_samples > 0 のとき、選んだ順番での最短の道（体の大きさ0.3。保証の幅つき）を求めてその触れる点でも動かし、
      速いほうを残す。あわせて、体の大きさ STRICT_RADIUS の地図で「この順番でのクリアのコマ数の下限」を出す。"""
    started = time.perf_counter()
    world = world or World()
    item_cells = Sim(seed, cfg=TIME_ATTACK, world=world).item_cells  # 本物と同じ乱数の使い方で配置を作る
    bound_frames, _ = strict_lower_bound(world, item_cells)
    result = {"seed": seed, "lower_bound": round(bound_frames * DT, 4), "lower_bound_frames": bound_frames,
              "time": None, "driven_time": None, "order": None, "candidates": 0, "plan_seconds": 0.0,
              "exact_length": None, "exact_slack": None, "min_frames": None, "frames": None, "keys": []}
    if cutoff is not None and bound_frames * DT >= cutoff:
        result.update(outcome="cut", total_seconds=round(time.perf_counter() - started, 3))
        return result
    run = best_run(world, item_cells, candidates, margin)
    best_time, best_log = run["time"], run["log"]
    slow = cutoff is not None and best_time is not None and best_time >= cutoff
    exact = None
    if best_log is not None and exact_samples > 0 and not slow:
        exact = solve_exact(world, item_cells, run["order"], exact_samples)
        t, log, _ = drive_through(world, item_cells, run["order"], exact["touches"])
        if t is not None and t < best_time:
            best_time, best_log = t, log
        exact["min_frames"] = solve_exact(world, item_cells, run["order"], exact_samples, STRICT_RADIUS)["min_frames"]
    driven = best_time
    if best_log is not None and refine_seconds > 0 and not slow:
        best_log = refine(seed, world, best_log, refine_seconds, random.Random(seed))
        best_time = len(best_log) * DT
    win = best_log is not None
    result.update(
        outcome="win" if win else "fail",
        slow=slow,  # 動かした結果が cutoff 以上だったので、仕上げなどを省いた
        time=round(best_time, 4) if win else None,
        driven_time=round(driven, 4) if win else None,  # 仕上げの前のタイム
        order=run["order"],
        candidates=run["candidates"],
        plan_seconds=round(run["plan_seconds"], 4),
        total_seconds=round(time.perf_counter() - started, 3),
        # 選んだ順番での最短の道の長さ（体の大きさ0.3。保証の幅 slack：本当の最短は length − slack 以上）と、
        # この順番でのクリアのコマ数の下限（体の大きさ STRICT_RADIUS の地図で測った厳密な値）
        exact_length=round(exact["length"], 4) if exact else None,
        exact_slack=round(exact["slack"], 4) if exact else None,
        min_frames=exact["min_frames"] if exact else None,
        frames=len(best_log) if win else None,
        keys=encode_keys(best_log) if win else [],
    )
    return result


def replay_time(seed, keys, world=None):
    """記録を最初から流したときのクリアの秒数（クリアしなければ None）。"""
    sim = Sim(seed, cfg=TIME_ATTACK, world=world)
    for pressed in decode_keys(keys):
        sim.step(pressed)
        if sim.done:
            break
    return sim.elapsed if sim.state == "win" else None


def save(result, results=RESULTS):
    """クリアの記録を play_record で再生できる形で保存する（同じ種で前の記録のほうが速ければ残す）。"""
    if result["outcome"] != "win":
        return False
    folder = results / "wins"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"seed_{result['seed']}.json"
    if path.exists() and json.loads(path.read_text(encoding="utf-8"))["time"] <= result["time"]:
        return False
    record = {"seed": result["seed"], "dt": DT, "time": result["time"], "outcome": "win",
              "level": TIME_ATTACK.key, "order": result["order"], "lower_bound": result["lower_bound"],
              "exact_length": result["exact_length"], "exact_slack": result["exact_slack"],
              "min_frames": result["min_frames"], "keys": result["keys"]}
    path.write_text(json.dumps(record), encoding="utf-8")
    return True


def parse_seeds(text):
    if "-" in text:
        lo, hi = text.split("-")
        return list(range(int(lo), int(hi) + 1))
    return [int(s) for s in text.split(",")]


def main():
    parser = argparse.ArgumentParser(description="タイムアタックの攻略ボット")
    parser.add_argument("--seed", type=int, help="解く配置の種（1つ）")
    parser.add_argument("--seeds", help="まとめて解く種（例 0-99 や 1,5,9）")
    parser.add_argument("--candidates", type=int, default=10, help="実際に動かして比べる順番の数の上限")
    parser.add_argument("--margin", type=float, default=0.08, help="最短の距離から何割増しまでの順番を候補にするか")
    parser.add_argument("--refine-seconds", type=float, default=3.0, help="仕上げ（入力をずらして縮める）に使う秒数。0でしない")
    parser.add_argument("--exact-samples", type=int, default=SAMPLES,
                        help="選んだ順番の最短の道を求めるときの、円の周の候補の数（多いほど保証の幅が小さく、遅い）。0でしない")
    parser.add_argument("--cutoff", type=float, default=DEFAULT_CUTOFF,
                        help=f"足切りの秒数。厳密な下限がこれ以上の配置は計算しない（初期値 {DEFAULT_CUTOFF}）。0で足切りしない")
    parser.add_argument("--results", type=Path, default=RESULTS, help="結果のフォルダ")
    args = parser.parse_args()
    seeds = parse_seeds(args.seeds) if args.seeds else [args.seed if args.seed is not None else 0]
    cutoff = args.cutoff if args.cutoff > 0 else None
    world = World()
    times, cut = [], 0
    for seed in seeds:
        r = solve(seed, args.candidates, args.margin, args.refine_seconds, world, args.exact_samples, cutoff)
        if r["outcome"] == "cut":
            cut += 1
            print(f"種 {seed}: 足切り（下限 {r['lower_bound']:.2f}秒）")
            continue
        saved = save(r, args.results)
        if r["outcome"] != "win":
            print(f"種 {seed}: クリアできず  候補 {r['candidates']}本")
            continue
        times.append((r["time"], seed))
        detail = ""
        if r["min_frames"] is not None:
            detail = (f"  この順番の最短の道 {r['exact_length']:.3f}（保証の幅 {r['exact_slack']:.3f}）・"
                      f"この順番の下限 {r['min_frames']}コマ・ボット {r['frames']}コマ（差 {r['frames'] - r['min_frames']}コマ）")
        if r["slow"]:
            detail = f"  （{cutoff:.2f}秒以上なので、仕上げなどは省略）"
        print(f"種 {seed}: {r['time']:.2f}秒（仕上げ前 {r['driven_time']:.2f}秒・下限 {r['lower_bound']:.2f}秒）"
              f"  順番 {r['order']}{detail}  全体 {r['total_seconds']}秒{'  （保存）' if saved else ''}")
    summary = f"足切り {cut}/{len(seeds)}"
    if times:
        best = min(times)
        summary += (f"  クリア {len(times)}  平均 {sum(t for t, _ in times) / len(times):.2f}秒  "
                    f"最速 {best[0]:.2f}秒（種 {best[1]}）")
    print(summary)


if __name__ == "__main__":
    main()
