"""8個のアイテムを回る順番の計算（動的計画法 Held-Karp）。ゲーム内のゴーストと攻略ボットの両方が使う。

8個の並べ方 8! = 40320 通りを全部比べず、「残りの集合と今いる場所」ごとに最短の残り距離を表にして、
2^8 × 8 × 8 ≈ 1.6万回の計算で最短の順番を出す。その表は「ここから先の最短」が正確に分かるので、
最短の少し上までの順番だけを、無駄な枝をたどらずに挙げられる（near_best_orders）。
"""

import math


def solve_order(start_to_item, item_to_item, item_to_exit):
    """Held-Karp：cost[mask][i] = アイテム i にいて、mask のアイテムをまだ拾っていないとき、
    残りを全部拾って出口に着くまでの最短距離。戻り値は (cost の表, スタートからの最短距離)。"""
    n = len(item_to_exit)
    full = (1 << n) - 1
    cost = [[math.inf] * n for _ in range(1 << n)]
    for i in range(n):
        cost[0][i] = item_to_exit[i]
    for mask in range(1, full + 1):  # mask が小さい（残りが少ない）順に埋まる：部分集合は必ず mask より小さい
        for i in range(n):
            if mask >> i & 1:
                continue  # i は今いる場所なので、残りに入っていない
            best = math.inf
            rest = mask
            while rest:
                j = (rest & -rest).bit_length() - 1
                rest &= rest - 1
                c = item_to_item[i][j] + cost[mask & ~(1 << j)][j]
                if c < best:
                    best = c
            cost[mask][i] = best
    total = min(start_to_item[j] + cost[full & ~(1 << j)][j] for j in range(n))
    return cost, total


def near_best_orders(cost, start_to_item, item_to_item, limit, count):
    """距離が limit 以下の順番を、短い順に最大 count 本。cost の表が「ここから先の最短」を正確に教えるので、
    limit を超える枝には入らない（たどるのは条件を満たす順番の道だけ）。"""
    n = len(start_to_item)
    full = (1 << n) - 1
    found = []

    def walk(order, last, mask, so_far):
        if not mask:
            found.append((so_far, order))  # so_far は出口までの距離を含む
            return
        for j in range(n):
            if not mask >> j & 1:
                continue
            step = item_to_item[last][j] if last is not None else start_to_item[j]
            rest = mask & ~(1 << j)
            if so_far + step + cost[rest][j] <= limit + 1e-9:
                walk(order + [j], j, rest, so_far + step + (cost[0][j] if not rest else 0.0))

    walk([], None, full, 0.0)
    found.sort()
    return found[:count]
