"""速いクリアの記録の「後半だけ」をやり直して、さらに速いクリアを探す。

記録を途中まで再生し、そこからボットに続きを何通りか（動きを少しずつ変えて）やらせる。
戻る時点は、記録の終わりから CUT_STEP 秒ずつ前（CUTS か所）。
今の記録より速くクリアできたら記録を書き換え、新しい記録からもう一度くり返す（--rounds 回まで）。

使い方（プロジェクトのフォルダで）:
    uv run python -m tools.hell_bot.refine --seed 3203
    uv run python -m tools.hell_bot.refine --seed 3203 --rounds 5 --variants 6

読む・書く記録: tools/hell_bot/results/wins/seed_<種>.json（速くなったときだけ書き換える）。
書き換える前の記録は、初回だけ seed_<種>.orig.json として残す。
"""

import argparse
import json
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from stealth_game.world import World

from .danger import DangerMap
from .planner import Bot, decode_keys, encode_keys
from .levels import LEVELS, level_key, results_for, set_level
from .sim import DT, Sim

RESULTS = Path(__file__).resolve().parent / "results"
CUT_STEP = 5.0  # 戻る時点の間隔（秒）
CUTS = 8  # 戻る時点の数（終わりから CUT_STEP×CUTS 秒前まで）
MAX_COMPUTE_SECONDS = 300  # 1回のやり直しの計算時間の上限

_world = None


def replay_keys(seed, keys):
    """記録を最初から再生した結果の状態。"""
    global _world
    if _world is None:
        _world = World()
    sim = Sim(seed, world=_world)
    for k in keys:
        if sim.done:
            break
        sim.step(k)
    return sim


def retry_from(seed, encoded, cut_frame, variant, danger_map):
    """記録を cut_frame コマ目まで再生し、そこからボットに続きをやらせる。(結果, 最初からの入力の記録)。"""
    keys = decode_keys(encoded)[:cut_frame]
    sim = replay_keys(seed, keys)
    if sim.done:
        return None
    bot = Bot(sim, danger_map, variant)
    bot.last_collect_time = sim.elapsed
    result = bot.play(max_compute_seconds=MAX_COMPUTE_SECONDS)
    result["cut_time"] = round(cut_frame * DT, 2)
    result["variant"] = variant
    return result, encode_keys(keys + bot.log)


def guarded(*args):
    try:
        return retry_from(*args)
    except Exception:  # noqa: BLE001
        return {"error": traceback.format_exc()}, None


def main():
    parser = argparse.ArgumentParser(description="速いクリアの記録の後半をやり直して、さらに速くする")
    parser.add_argument("--seed", type=int, required=True, help="やり直す記録の種（wins/seed_<種>.json）")
    parser.add_argument("--rounds", type=int, default=3, help="速くなったら、新しい記録からくり返す回数の上限")
    parser.add_argument("--variants", type=int, default=4, help="1つの時点から試す動きの数")
    parser.add_argument("--workers", type=int, default=8, help="同時に走らせる数")
    parser.add_argument("--level", choices=LEVELS, default="hell", help="記録の難易度（theory＝理論値）")
    parser.add_argument("--results", type=Path, default=None, help="結果のフォルダ（省くと難易度ごとの標準の場所）")
    args = parser.parse_args()
    set_level(args.level)
    args.results = args.results or results_for(RESULTS)

    path = args.results / "wins" / f"seed_{args.seed}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    danger_map = DangerMap.load(args.results / "danger.json")
    started = time.perf_counter()
    print(f"種 {args.seed}: 今の記録 {record['time']}秒", flush=True)
    for round_no in range(1, args.rounds + 1):
        frames = len(decode_keys(record["keys"]))
        cut_frames = [frames - round(k * CUT_STEP / DT) for k in range(1, CUTS + 1)]
        cut_frames = [c for c in cut_frames if c > 0]
        best = None
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(guarded, args.seed, record["keys"], c, v, danger_map)
                       for c in cut_frames for v in range(args.variants)]
            for f in as_completed(futures):
                out = f.result()
                if out is None:
                    continue
                result, keys = out
                if "error" in result:
                    print("エラー\n" + result["error"], flush=True)
                    continue
                mark = ""
                if result["outcome"] == "win" and result["time"] < record["time"] and (
                        best is None or result["time"] < best[0]["time"]):
                    best = (result, keys)
                    mark = "  ← 速い"
                print(f"  [{round_no}回目] {result['cut_time']}秒から（動き{result['variant']}）: "
                      f"{result['outcome']} {result['time']}秒{mark}", flush=True)
        if best is None:
            print(f"{round_no}回目: 速くならなかったので終わります", flush=True)
            break
        result, keys = best
        # 念のため、最初から再生して同じ結果になることを確かめる
        check = replay_keys(args.seed, decode_keys(keys))
        if check.state != "win" or abs(check.elapsed - result["time"]) > 0.05:
            print(f"{round_no}回目: 再生で結果が合わなかったので、この記録は使いません", flush=True)
            break
        orig = path.with_name(f"seed_{args.seed}.orig.json")
        if not orig.exists():
            orig.write_text(json.dumps(record), encoding="utf-8")
        record = {"seed": args.seed, "dt": DT, "time": result["time"], "outcome": "win",
                  "variant": record.get("variant", 0), "refined": round_no, "level": level_key(), "keys": keys}
        path.write_text(json.dumps(record), encoding="utf-8")
        print(f"{round_no}回目: {result['time']}秒に更新（{result['cut_time']}秒の時点から）", flush=True)
    print(f"最終: {record['time']}秒  計算 {(time.perf_counter() - started) / 60:.1f}分", flush=True)


if __name__ == "__main__":
    main()
