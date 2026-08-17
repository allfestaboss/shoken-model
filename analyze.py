#!/usr/bin/env python3
"""福岡県60市町村で「人口 -> コンビニ店舗数」の係数を推定し、残差を出す。

出したいのは2つ。
  1. 係数そのもの（1店あたり人口 K と、規模弾力性 b）。
     「◯人に1店」が定数なら b=1、都市ほど密なら b>1、町ほど密なら b<1。
  2. 残差 = 実際 - 期待。マイナスに大きい＝供給不足＝次に生まれる候補。

v0 は夜間人口だけで、残差が「昼間人口・通過需要」を拾っていた。
いまは昼間人口とDID（人口集中地区）も入れて、モデルを並べて比べる。

  python3 analyze.py   ->  data/residuals.csv, out/fit.png, 標準出力に要約
"""
import csv
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DATA, OUT = ROOT / "data", ROOT / "out"

# 外部の参照値: 主要6チェーンの福岡県店舗数（2026年・日本ソフト販売の都道府県別集計）
REFERENCE_STORES = 2313


def load() -> list:
    rows = list(csv.DictReader((DATA / "stores_convenience.csv").open(encoding="utf-8")))
    ctx = {r["code"]: r for r in csv.DictReader((DATA / "context.csv").open(encoding="utf-8"))}
    for r in rows:
        r["pop"] = int(r["pop"])
        r["stores"] = int(r["stores"])
        c = ctx[r["code"]]
        r["daytime_pop"] = float(c["daytime_pop"])
        r["day_night_ratio"] = float(c["day_night_ratio"])
        r["did_pop"] = float(c["did_pop"])
        r["did_share"] = float(c["did_share"])
    return rows


def ols(X: np.ndarray, y: np.ndarray) -> tuple:
    """係数, R^2, 自由度調整済みR^2, LOO交差検証のRMSE"""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ beta
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot
    n, k = X.shape
    adj = 1 - (1 - r2) * (n - 1) / (n - k)
    # leave-one-out は hat 行列の対角から解析的に出せる
    H = X @ np.linalg.pinv(X.T @ X) @ X.T
    h = np.clip(np.diag(H), 0, 1 - 1e-9)
    loo = float(np.sqrt((((y - pred) / (1 - h)) ** 2).mean()))
    return beta, r2, adj, loo


def main() -> None:
    OUT.mkdir(exist_ok=True)
    rows = load()
    m = [r for r in rows if r["stores"] > 0]          # log を取るので0店は落とす

    pop = np.array([r["pop"] for r in rows], dtype=float)
    stores = np.array([r["stores"] for r in rows], dtype=float)
    tot_p, tot_s = pop.sum(), stores.sum()

    print(f"市町村 {len(rows)}／人口 {tot_p:,.0f}／OSM店舗 {tot_s:,.0f}")
    print(f"OSM の網羅率  {tot_s/REFERENCE_STORES:5.1%}  （外部参照 {REFERENCE_STORES:,}店）")
    print(f"1店あたり人口  OSM基準 {tot_p/tot_s:,.0f} 人 / 参照値基準 {tot_p/REFERENCE_STORES:,.0f} 人\n")

    y = np.log(np.array([r["stores"] for r in m], dtype=float))
    lpop = np.log(np.array([r["pop"] for r in m], dtype=float))
    lday = np.log(np.array([r["daytime_pop"] for r in m], dtype=float))
    lratio = np.log(np.array([r["day_night_ratio"] for r in m], dtype=float) / 100)
    did = np.array([r["did_share"] for r in m], dtype=float)
    one = np.ones_like(y)

    models = {
        "M1 夜間人口だけ（v0）": np.column_stack([one, lpop]),
        "M2 昼間人口だけ": np.column_stack([one, lday]),
        "M3 夜間 + 昼夜間比": np.column_stack([one, lpop, lratio]),
        "M4 M3 + DID率": np.column_stack([one, lpop, lratio, did]),
        # 通勤で「入ってくる町」も「出ていく町」も店が多い＝100からの距離が効く、という仮説
        "M5 M3 + 昼夜比のズレ二乗": np.column_stack([one, lpop, lratio, lratio ** 2]),
        "M6 M5 + DID率": np.column_stack([one, lpop, lratio, lratio ** 2, did]),
    }

    print(f"{'モデル':24}{'R^2':>7}{'調整R^2':>9}{'LOO-RMSE':>10}")
    results = {}
    for name, X in models.items():
        beta, r2, adj, loo = ols(X, y)
        results[name] = (beta, X, r2, adj, loo)
        print(f"{name:24}{r2:>7.3f}{adj:>9.3f}{loo:>10.3f}")

    best = min(results, key=lambda k: results[k][4])
    beta, X, r2, adj, loo = results[best]
    print(f"\n採用: {best}（LOO-RMSE が最小）")
    labels = {"M1 夜間人口だけ（v0）": ["定数", "log人口"],
              "M2 昼間人口だけ": ["定数", "log昼間人口"],
              "M3 夜間 + 昼夜間比": ["定数", "log人口", "log昼夜間比"],
              "M4 M3 + DID率": ["定数", "log人口", "log昼夜間比", "DID率"],
              "M5 M3 + 昼夜比のズレ二乗": ["定数", "log人口", "log昼夜間比", "(log昼夜間比)^2"],
              "M6 M5 + DID率": ["定数", "log人口", "log昼夜間比", "(log昼夜間比)^2", "DID率"]}[best]
    for lab, b in zip(labels, beta):
        print(f"  {lab:12} {b:+.3f}")

    pred = np.exp(X @ beta)
    for r, p in zip(m, pred):
        r["expected"] = round(float(p), 1)
        r["residual"] = round(r["stores"] - float(p), 1)
        r["ratio"] = round(r["stores"] / float(p), 3)
        r["pop_per_store"] = round(r["pop"] / r["stores"])
    for r in rows:
        r.setdefault("expected", "")
        r.setdefault("residual", "")
        r.setdefault("ratio", "")
        r.setdefault("pop_per_store", "")

    solid = [r for r in m if r["expected"] >= 3]
    by_ratio = sorted(solid, key=lambda r: r["ratio"])
    print("\n■ 期待に対して少ない（実/期待・期待3店以上）")
    for r in by_ratio[:8]:
        print(f"  {r['name']:8} 人口 {r['pop']:>9,}  昼夜比 {r['day_night_ratio']:5.1f}  "
              f"実 {r['stores']:>3}  期待 {r['expected']:>6.1f}  比 {r['ratio']:.2f}")
    print("\n■ 期待に対して多い（実/期待・期待3店以上）")
    for r in by_ratio[-8:][::-1]:
        print(f"  {r['name']:8} 人口 {r['pop']:>9,}  昼夜比 {r['day_night_ratio']:5.1f}  "
              f"実 {r['stores']:>3}  期待 {r['expected']:>6.1f}  比 {r['ratio']:.2f}")

    pps = np.array([r["pop"] / r["stores"] for r in m])
    print(f"\n1店あたり人口の分布: 最小 {pps.min():,.0f} / 中央 {np.median(pps):,.0f} / "
          f"最大 {pps.max():,.0f} 人")

    path = DATA / "residuals.csv"
    fields = ["code", "name", "kind", "pop", "daytime_pop", "day_night_ratio", "did_share",
              "stores", "expected", "residual", "ratio", "pop_per_store"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: -r["pop"]))
    print(f"\n-> {path}")

    plot(m, results)


def plot(rows: list, results: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    for cand in ("Hiragino Sans", "Hiragino Maru Gothic ProN", "YuGothic", "AppleGothic"):
        if any(cand in f.name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = cand
            break

    st = np.array([r["stores"] for r in rows], dtype=float)
    exp = np.array([r["expected"] for r in rows], dtype=float)
    pop = np.array([r["pop"] for r in rows], dtype=float)
    ratio = np.array([r["ratio"] for r in rows], dtype=float)

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.6), dpi=160)
    fig.patch.set_facecolor("#E9E7DF")

    # 左: v0（夜間人口だけ）のあてはめ
    beta1 = results["M1 夜間人口だけ（v0）"][0]
    ax = axes[0]
    ax.set_facecolor("#F2F0E9")
    ax.scatter(pop, st, s=30, c="#8A3B2E", alpha=.8, edgecolors="none", zorder=3)
    xs = np.linspace(pop.min() * .8, pop.max() * 1.2, 200)
    ax.plot(xs, np.exp(beta1[0]) * xs ** beta1[1], color="#1F5C55", lw=1.4, zorder=2)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("人口（対数）"); ax.set_ylabel("コンビニ店舗数（対数）")
    ax.set_title(f"v0：夜間人口だけ  R²={results['M1 夜間人口だけ（v0）'][2]:.3f}", pad=10)
    ax.grid(True, which="both", color="#C9C6B8", lw=.5, alpha=.7)

    # 右: 採用モデルの 実測 vs 期待
    ax = axes[1]
    ax.set_facecolor("#F2F0E9")
    lim = [0.7, max(st.max(), exp.max()) * 1.3]
    ax.plot(lim, lim, color="#6B7A79", lw=1, ls="--", zorder=2)
    ax.scatter(exp, st, s=30, c=np.where(ratio < 1, "#8A3B2E", "#1F5C55"),
               alpha=.85, edgecolors="none", zorder=3)
    ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlim(lim); ax.set_ylim(lim)
    ax.set_xlabel("期待店舗数（昼夜間比を入れたモデル）"); ax.set_ylabel("実際の店舗数")
    ax.set_title("昼間人口を入れたあと：実測 vs 期待", pad=10)
    ax.grid(True, which="both", color="#C9C6B8", lw=.5, alpha=.7)

    order = np.argsort(ratio)
    for i in list(order[:4]) + list(order[-4:]):
        ax.annotate(rows[i]["name"], (exp[i], st[i]), fontsize=8,
                    xytext=(5, 3), textcoords="offset points", color="#3D4F50")

    fig.tight_layout()
    fig.savefig(OUT / "fit.png", facecolor=fig.get_facecolor())
    print(f"-> {OUT/'fit.png'}")


if __name__ == "__main__":
    main()
