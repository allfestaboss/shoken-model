#!/usr/bin/env python3
"""全国の開店データでモデルを測り直す。

福岡だけだとコンビニの新店が12か月で50件しかなく、倍率の95%区間が
5.8〜8.3倍と広かった。全国なら2,229件になるので、区間が締まる。

物差しはこれまでどおり **まだ1店も無いマスの中での順位づけ**。
「どこに店があるか」は既存店舗数を並べるだけで当たるので、モデルの仕事ではない。

3つ出す。
  全国       … 全国で学習し、全国のまだ1店も無いマスで測る
  県を隠す   … その県を学習から外して、その県で測る（47回）。移転の総仕上げ
  先客       … 既存店舗数で並べただけの対抗馬。ゼロのマスでは全部0で並ぶため測れない

  .venv-duck/bin/python measure_national.py
"""
import csv
import math
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, ".")
import mesh_model as M  # noqa: E402
from prefs import NAME  # noqa: E402

CATS = {"コンビニ": ("stores_fsq", r"セブン[－\-ー–ｰ]?イレブン|ファミリーマート|ローソン|"
                            r"ミニストップ|デイリーヤマザキ|ポプラ"),
        "ドラッグ・薬局": ("drug_fsq", ""), "スーパー": ("super_fsq", "")}


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def openings() -> dict:
    out = {}
    for r in csv.DictReader(open("data/openings_national_geo.csv", encoding="utf-8")):
        out.setdefault(r["cat"], []).append(
            (int(r["lat_i"]), int(r["lon_i"]), r["pref_code"]))
    return out


def rank_in(zone, score, tie, mesh, hits):
    """zone のマスだけで順位づけし、hits が落ちた位置を返す。"""
    order = zone[np.lexsort((tie[zone], -score[zone]))]
    rank = {(mesh[i]["lat_i"], mesh[i]["lon_i"]): j / len(order)
            for j, i in enumerate(order)}
    return np.array([rank[k] for k in hits if k in rank])


def main() -> None:
    opens = openings()
    print("開店（座標つき）:", {k: len(v) for k, v in opens.items()}, "\n")

    for cat, (target, _) in CATS.items():
        if cat not in opens:
            continue
        M.TARGET = target
        mesh = M.load()
        for r in mesh:
            r["pref"] = r.get("pref") or r["city"][:2]
        idx = {(r["lat_i"], r["lon_i"]): i for i, r in enumerate(mesh)}
        pref = np.array([r["pref"] for r in mesh])
        n = np.array([r["stores"] for r in mesh], dtype=float)
        X = M.features(mesh)
        tie = np.random.default_rng(0).random(len(mesh))

        pts = [(la, lo) for la, lo, _ in opens[cat]]
        stock = n.copy()                            # 開店前の状態に戻す
        for k, c in Counter(pts).items():
            if k in idx:
                stock[idx[k]] = max(0.0, stock[idx[k]] - c)
        hits = [k for k in pts if k in idx and stock[idx[k]] == 0]

        # 1) 全国で学習して全国で測る
        beta = M.fit_poisson(X, stock)
        lam = np.exp(np.clip(X @ beta, -30, 20))
        zone = np.where(stock == 0)[0]
        p = rank_in(zone, lam, tie, mesh, hits)
        k10 = int((p <= .10).sum())
        lo, hi = wilson(k10, len(p))
        print(f"■ {cat}")
        print(f"  対象の新店 {len(p):,}（うちマスが0だったもの）／"
              f"順位づけの母数 {len(zone):,}マス")
        print(f"  全国で学習   上位1% {(p<=.01).mean():>6.1%}  上位10% {(p<=.10).mean():>6.1%}"
              f"  = {(p<=.10).mean()/.10:>4.1f}倍  95%区間 {lo/.10:.1f}〜{hi/.10:.1f}")

        # 2) 県を隠す（その県のデータを1行も使わずに、その県を予測する）
        outs = []
        for pc in sorted(set(pref)):
            sel = [k for k, (la, lo_, p_) in zip(pts, opens[cat])
                   if p_ == pc and k in idx and stock[idx[k]] == 0]
            if len(sel) < 5:
                continue
            tr = pref != pc
            b = M.fit_poisson(X[tr], stock[tr])
            lm = np.exp(np.clip(X @ b, -30, 20))
            z = np.where((pref == pc) & (stock == 0))[0]
            q = rank_in(z, lm, tie, mesh, sel)
            if len(q):
                outs.append((pc, len(q), (q <= .10).mean() / .10))
        if outs:
            v = np.array([x[2] for x in outs])
            tot = sum(x[1] for x in outs)
            print(f"  県を隠す     {len(outs)}県・{tot:,}店  倍率の中央値 {np.median(v):.1f}倍"
                  f"（最小 {v.min():.1f} / 最大 {v.max():.1f}）")
            worst = sorted(outs, key=lambda x: x[2])[:3]
            print("    低いほう: " + " / ".join(
                f"{NAME[c]}{r:.1f}倍(n={m})" for c, m, r in worst))
        print()


if __name__ == "__main__":
    main()
