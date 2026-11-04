"""地獄への挑戦をくり返し、結果と危険度の地図を保存する。

使い方（プロジェクトのフォルダで）:
    uv run python -m tools.hell_bot.run --attempts 20
    uv run python -m tools.hell_bot.run --attempts 40 --workers 4   （同時に走らせる数を4にする。最初は8つ同時）
    uv run python -m tools.hell_bot.run --attempts 8 --max-minutes 30   （1回の計算時間の上限を30分にする。最初は15分）

結果は tools/hell_bot/results/ に保存する（GitHub には上げない）。
- attempts.jsonl: 挑戦ごとの結果（1行に1回）
- danger.json: 危険度の地図（次回の実行はここから続ける）
- wins/seed_<種>.json: クリアできた回の入力の記録（replay.py で本物のゲーム画面で再生できる）
- runs/seed_<種>.json: クリアできなかった回の入力の記録（どこで失敗したかを見る用）
- errors.log: 挑戦の途中でエラーが起きたときの内容（その挑戦だけ飛ばして、ほかは続ける）
"""

import argparse
import json
import random
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from stealth_game.world import World

from .danger import DangerMap, choose_seed
from .sim import DT
from .worker import attempt

RESULTS = Path(__file__).resolve().parent / "results"
SEED_POOL = range(0, 5000)  # この範囲の種（アイテムの配置）から選ぶ


def tried_seeds(path):
    if not path.exists():
        return set()
    return {json.loads(line)["seed"] for line in path.read_text(encoding="utf-8").splitlines() if line}


def save_result(results, result, visited, keys, danger_map, danger_path, attempts_path):
    danger_map.record(visited, [tuple(c) for c in result["fail_cells"]])
    danger_map.save(danger_path)
    with attempts_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")
    record = {"seed": result["seed"], "dt": DT, "time": result["time"], "outcome": result["outcome"], "keys": keys}
    folder = results / ("wins" if result["outcome"] == "win" else "runs")
    folder.mkdir(exist_ok=True)
    (folder / f"seed_{result['seed']}.json").write_text(json.dumps(record), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="地獄への挑戦をくり返す")
    parser.add_argument("--attempts", type=int, default=10, help="挑戦する回数")
    parser.add_argument("--workers", type=int, default=8, help="同時に走らせる挑戦の数（最初は8。PCのコア数まで）")
    parser.add_argument("--seed", type=int, help="この種だけを試す（選び分けをしない）")
    parser.add_argument("--results", type=Path, default=RESULTS, help="結果を保存するフォルダ")
    parser.add_argument("--max-minutes", type=float, default=15.0, help="1回の挑戦の計算時間の上限（分）。超えたら打ち切る")
    args = parser.parse_args()

    world = World()
    results = args.results
    danger_path = results / "danger.json"
    attempts_path = results / "attempts.jsonl"
    danger_map = DangerMap.load(danger_path)
    tried = tried_seeds(attempts_path)
    rng = random.Random()
    results.mkdir(parents=True, exist_ok=True)

    def next_seed():
        if args.seed is not None:
            return args.seed
        seed = choose_seed(world, danger_map, SEED_POOL, tried, rng)
        if seed is not None:
            tried.add(seed)
        return seed

    started = finished = 0
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        running = {}  # {挑戦: 種}
        while started < args.attempts or running:
            # 空いている分だけ新しい挑戦を始める（終わった挑戦の結果で更新した危険度の地図を使う）
            while started < args.attempts and len(running) < args.workers:
                seed = next_seed()
                if seed is None:
                    print("試していない種がなくなりました")
                    args.attempts = started
                    break
                running[pool.submit(attempt, seed, danger_map, args.max_minutes * 60)] = seed
                started += 1
            if not running:
                break
            done, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in done:
                seed = running.pop(future)
                try:
                    result, visited, keys = future.result()
                except BrokenProcessPool:
                    print("挑戦を動かす仕組みが止まってしまいました（メモリ不足などの可能性があります）。ここで終わります", flush=True)
                    return
                except Exception:  # noqa: BLE001
                    finished += 1
                    with (results / "errors.log").open("a", encoding="utf-8") as f:
                        f.write(f"種 {seed}\n{traceback.format_exc()}\n")
                    print(f"[{finished}/{args.attempts}] 種 {seed}: エラー（内容は errors.log。ほかの挑戦は続けます）", flush=True)
                    continue
                save_result(results, result, visited, keys, danger_map, danger_path, attempts_path)
                finished += 1
                print(
                    f"[{finished}/{args.attempts}] 種 {result['seed']}: {result['outcome']}  アイテム {result['items']}/8（最高 {result['best_items']}）  巻き戻し {result['rewinds']}回  "
                    f"ゲーム内 {result['time']}秒  計算 {result['compute_seconds']}秒  配置の点数 {result['layout_score']}",
                    flush=True,
                )


if __name__ == "__main__":
    main()
