#!/usr/bin/env python3
"""モデルを「先客」と比べる。物差しの設計はここで決まった。

飲食で前向き検証をしたら、上位1%が新店の58%を捕まえるという出来過ぎた数字が出た。
飲食は元々一点集中する商売なので、**「今すでに店が多い場所」を並べるだけでも
同じ点が出るのではないか**と疑い、対抗馬を置いて測り直した。

  対抗馬 = 既存店舗数そのもので順位づけ（モデルなし）

結果は業態で正反対だった。この差は「新店がどこに出るか」の性質そのもので、
スーパーは87%が今まで店が無かったメッシュに出るのに対し、
飲食は85%が既に店があるメッシュに出る。

  棲み分け型（スーパー・コンビニ）… 先客は当たらない。モデルが要る
  集積型（飲食）                … 先客が最強。モデルは要らない

そして**まだ店が無いメッシュに絞ると、全業態でモデルが7〜9倍で当たる**。
そこでは先客は全メッシュが0で並ぶため、原理的に順位をつけられない。
これがモデルの本当の持ち場であり、以後この条件で評価する。

  .venv-duck/bin/python baseline.py
"""
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, ".")
import mesh_model as M  # noqa: E402
from validate_food import CUTOFF, load_openings  # noqa: E402
from validate_openings_multi import CATS, geocode_all, parse_pdfs  # noqa: E402

SEED = 0


def jobs():
    geo = geocode_all(parse_pdfs())
    for cat, (target, _) in CATS.items():
        yield cat, target, [(int(x["lat_i"]), int(x["lon_i"]))
                            for x in geo if x["cat"] == cat]
    food = load_openings()
    yield "飲食", "dining", [(x["lat_i"], x["lon_i"]) for x in food if x["date"] >= CUTOFF]


def setup(target, opens):
    """新店を差し引いて開店前の状態に戻し、モデルを学習する。"""
    M.TARGET = target
    rows = M.load()
    idx = {(r["lat_i"], r["lon_i"]): i for i, r in enumerate(rows)}
    stock = np.array([r["stores"] for r in rows], dtype=float)
    for k, c in Counter(opens).items():
        if k in idx:
            stock[idx[k]] = max(0.0, stock[idx[k]] - c)
    X = M.features(rows)
    lam = np.exp(np.clip(X @ M.fit_poisson(X, stock), -30, 20))
    return rows, idx, stock, lam


def positions(rows, score, opens, subset=None):
    """subset のメッシュだけで順位づけし、opens が落ちた位置（0=最上位）を返す。

    同点は乱数で崩す。既存店舗数は0が大量に並ぶので、崩さないと
    CSVの行順がそのまま順位になり、対抗馬を不当に不利にしてしまう。
    """
    sel = np.arange(len(rows)) if subset is None else np.asarray(subset)
    tie = np.random.default_rng(SEED).random(len(rows))
    order = sel[np.lexsort((tie[sel], -score[sel]))]
    rank = {(rows[i]["lat_i"], rows[i]["lon_i"]): j / len(order)
            for j, i in enumerate(order)}
    return np.array([rank[k] for k in opens if k in rank])


def line(label, pos, width=26):
    if len(pos) == 0:
        print(f"{label:<{width}}該当なし")
        return
    print(f"{label:<{width}}{len(pos):>7,}{np.median(pos):>9.3f}"
          f"{(pos <= .01).mean():>9.1%}{(pos <= .10).mean():>9.1%}"
          f"{(pos <= .10).mean()/.10:>8.1f}x")


def main() -> None:
    todo = list(jobs())

    print("■ モデル vs 先客（全メッシュで順位づけ）\n")
    print(f"{'業態 / 並べ方':<26}{'新店':>7}{'中央値':>9}{'上位1%':>9}{'上位10%':>9}{'倍率':>8}")
    for cat, target, opens in todo:
        rows, idx, stock, lam = setup(target, opens)
        line(f"{cat} ／ 既存店舗数（先客）", positions(rows, stock, opens))
        line(f"{cat} ／ モデル（地理だけ）", positions(rows, lam, opens))

    print("\n\n■ 新店はどこに出たか\n")
    print(f"{'業態':<12}{'新店':>8}{'既に店があった':>15}{'店が無かった':>14}")
    empties = {}
    for cat, target, opens in todo:
        rows, idx, stock, lam = setup(target, opens)
        valid = [k for k in opens if k in idx]
        zero = [k for k in valid if stock[idx[k]] == 0]
        empties[cat] = (rows, stock, lam, zero)
        print(f"{cat:<12}{len(valid):>8,}{1 - len(zero)/len(valid):>14.1%}"
              f"{len(zero)/len(valid):>14.1%}")

    print("\n\n■ まだ店が無いメッシュだけで順位づけ（先客が原理的に測れない場所）\n")
    print(f"{'業態':<26}{'新店':>7}{'中央値':>9}{'上位1%':>9}{'上位10%':>9}{'倍率':>8}")
    for cat, (rows, stock, lam, zero) in empties.items():
        line(f"{cat} ／ モデル", positions(rows, lam, zero, np.where(stock == 0)[0]))
    print(f"{'でたらめなら':<26}{'':>7}{0.5:>9.3f}{0.01:>9.1%}{0.10:>9.1%}{1.0:>8.1f}x")


if __name__ == "__main__":
    main()
