"""地獄への挑戦をくり返し、結果と危険度の地図を保存する。

使い方（プロジェクトのフォルダで）:
    uv run python -m tools.hell_bot.run --attempts 20

結果は tools/hell_bot/results/ に保存する（GitHub には上げない）。
- attempts.jsonl: 挑戦ごとの結果（1行に1回）
- danger.json: 危険度の地図（次回の実行はここから続ける）
- wins/seed_<種>.json: クリアできた回の入力の記録（replay.py で本物のゲーム画面で再生できる）
- runs/seed_<種>.json: クリアできなかった回の入力の記録（どこで失敗したかを見る用）
"""

import argparse
import json
import random
import time
from pathlib import Path

from stealth_game.world import World

from .danger import DangerMap, choose_seed, layout_score
from .planner import Bot, encode_keys
from .sim import DT, Sim

RESULTS = Path(__file__).resolve().parent / "results"
SEED_POOL = range(0, 5000)  # この範囲の種（アイテムの配置）から選ぶ


def tried_seeds(path):
    if not path.exists():
        return set()
    return {json.loads(line)["seed"] for line in path.read_text(encoding="utf-8").splitlines() if line}


def main():
    parser = argparse.ArgumentParser(description="地獄への挑戦をくり返す")
    parser.add_argument("--attempts", type=int, default=10, help="挑戦する回数")
    parser.add_argument("--seed", type=int, help="この種だけを試す（選び分けをしない）")
    args = parser.parse_args()

    world = World()
    danger_path = RESULTS / "danger.json"
    attempts_path = RESULTS / "attempts.jsonl"
    danger_map = DangerMap.load(danger_path)
    tried = tried_seeds(attempts_path)
    rng = random.Random()
    RESULTS.mkdir(parents=True, exist_ok=True)

    for n in range(args.attempts):
        seed = args.seed if args.seed is not None else choose_seed(world, danger_map, SEED_POOL, tried, rng)
        if seed is None:
            print("試していない種がなくなりました")
            break
        tried.add(seed)
        sim = Sim(seed, world=world)
        score = layout_score(danger_map, sim.item_cells)
        started = time.perf_counter()
        bot = Bot(sim, danger_map)
        result = bot.play()
        result["layout_score"] = round(score, 3)
        result["compute_seconds"] = round(time.perf_counter() - started, 1)
        danger_map.record(bot.visited, tuple(result["fail_cell"]) if result["fail_cell"] else None)
        danger_map.save(danger_path)
        with attempts_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
        record = {"seed": seed, "dt": DT, "time": result["time"], "outcome": result["outcome"], "keys": encode_keys(bot.log)}
        folder = RESULTS / ("wins" if result["outcome"] == "win" else "runs")
        folder.mkdir(exist_ok=True)
        (folder / f"seed_{seed}.json").write_text(json.dumps(record), encoding="utf-8")
        print(
            f"[{n + 1}/{args.attempts}] 種 {seed}: {result['outcome']}  アイテム {result['items']}/8  "
            f"ゲーム内 {result['time']}秒  計算 {result['compute_seconds']}秒  配置の点数 {result['layout_score']}",
            flush=True,
        )


if __name__ == "__main__":
    main()
