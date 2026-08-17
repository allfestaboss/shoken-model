#!/usr/bin/env python3
"""閉店した店から「成立しなかった条件」を測る。

これまでは「店がある場所」しか見ていなかった。生き残りだけを見て法則を作るのは
生存者バイアスそのもので、「何人いれば成り立つか」には本来答えられない。

Foursquare は date_closed を持っており、福岡県のコンビニ3,337件のうち
**723件が閉店済み**（2014〜2025年）。これは「その場所では成立しなかった」という実例で、
他のどのソースにも無い。

出したいもの:
  1. 1店あたり人口ごとの**閉店率** ── 理屈ではなく実際の失敗で測った閾値
  2. どの条件が閉店を予測するか（ロジスティック回帰）

注意: 周辺店舗数は「いま」ではなく閉店・営業の全レコードで数える（当時の混み具合の代理）。
      FSQが閉店を捕捉する精度が地域で偏っていれば結果は歪むので、そこも併記する。

  python3 closures.py   ->  data/closures.csv, out/closure.png
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parent
DATA, OUT = ROOT / "data", ROOT / "out"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    mesh = {(int(r["lat_i"]), int(r["lon_i"])): r
            for r in csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8"))}
    pred = {(int(r["lat_i"]), int(r["lon_i"])): r
            for r in csv.DictReader((DATA / "mesh_pred.csv").open(encoding="utf-8"))}

    stores = [r for r in csv.DictReader((DATA / "fsq_places.csv").open(encoding="utf-8"))
              if r["category"] == "convenience_store"]

    # 3x3の店舗数（営業中＋閉店＝その場所が抱えていた密度の代理）
    per_mesh = defaultdict(int)
    for s in stores:
        per_mesh[(int(s["lat_i"]), int(s["lon_i"]))] += 1

    def around(idx, g):
        la, lo = idx
        return sum(g.get((la + i, lo + j), 0) for i in (-1, 0, 1) for j in (-1, 0, 1))

    rows = []
    for s in stores:
        idx = (int(s["lat_i"]), int(s["lon_i"]))
        m, p = mesh.get(idx), pred.get(idx)
        if not m or not p:
            continue
        pop_r1 = float(m["pop_r1"])
        n_r1 = around(idx, per_mesh)
        if pop_r1 < 500 or n_r1 == 0:
            continue
        rows.append({
            "name": s["name"], "lat": s["lat"], "lon": s["lon"],
            "closed": int(s["closed"]), "year": (s["date_closed"] or "")[:4],
            "city": m["city"], "pop_r1": pop_r1,
            "stores_r1": n_r1,
            "pop_per_store": pop_r1 / n_r1,
            "expected_r1": float(p["exp_r1"]),
            "over_supply": n_r1 - float(p["exp_r1"]),      # 期待より何店多いか
            "build_share": float(m["build_share"] or 0),
            "trunk_m": float(m["trunk_m"] or 0),
            "station_m": float(m["station_m"] or 0),
            "pop2020": float(m["pop2020"]), "pop2050": float(m["pop2050"]),
            "pop_decline": 1 - float(m["pop2050"]) / max(float(m["pop2020"]), 1),
        })

    n_cl = sum(r["closed"] for r in rows)
    print(f"対象 {len(rows):,} 店（閉店 {n_cl:,} = {n_cl/len(rows):.1%}）\n")

    # 1. 1店あたり人口ごとの閉店率
    buckets = [(0, 800), (800, 1200), (1200, 1600), (1600, 2200),
               (2200, 3000), (3000, 4500), (4500, 10 ** 9)]
    print("■ 周辺の1店あたり人口 と 閉店率")
    print(f"   {'1店あたり人口':<16}{'店数':>7}{'閉店':>7}{'閉店率':>9}")
    curve = []
    for lo, hi in buckets:
        sub = [r for r in rows if lo <= r["pop_per_store"] < hi]
        if len(sub) < 20:
            continue
        c = sum(r["closed"] for r in sub)
        label = f"{lo:,}〜{hi:,}" if hi < 10 ** 9 else f"{lo:,}人以上"
        print(f"   {label:<16}{len(sub):>7,}{c:>7,}{c/len(sub):>9.1%}")
        curve.append((label, len(sub), c / len(sub)))

    # 2. 何が閉店を予測するか
    def z(v):
        v = np.asarray(v, float)
        return (v - v.mean()) / (v.std() + 1e-9)

    X = np.column_stack([
        np.ones(len(rows)),
        z([math.log(r["pop_per_store"]) for r in rows]),
        z([r["over_supply"] for r in rows]),
        z([math.log1p(r["pop_r1"]) for r in rows]),
        z([r["build_share"] for r in rows]),
        z([math.log1p(r["trunk_m"]) for r in rows]),
        z([math.log1p(r["station_m"]) for r in rows]),
        z([r["pop_decline"] for r in rows]),
    ])
    y = np.array([r["closed"] for r in rows], dtype=float)
    names = ["定数", "log 1店あたり人口", "供給過剰度(実-期待)", "log 3x3人口",
             "建物用地率", "log 幹線延長", "log 駅までの距離", "2050年までの人口減少率"]

    def nll(b):
        zz = np.clip(X @ b, -30, 30)
        return -np.sum(y * zz - np.log1p(np.exp(zz))) + 1e-3 * np.sum(b[1:] ** 2)

    def grad(b):
        zz = np.clip(X @ b, -30, 30)
        g = -X.T @ (y - 1 / (1 + np.exp(-zz)))
        g[1:] += 2e-3 * b[1:]
        return g

    beta = minimize(nll, np.zeros(X.shape[1]), jac=grad, method="L-BFGS-B").x
    print("\n■ 閉店を予測する要因（標準化済み・正なら閉店しやすい）")
    for nm, b in zip(names, beta):
        arrow = "閉店↑" if b > .05 else ("閉店↓" if b < -.05 else "")
        print(f"   {nm:<22}{b:+.3f}  {arrow}")

    # 3. 捕捉の偏りの確認（都市と地方で閉店率が違うのは実態か、記録の差か）
    print("\n■ 確認: 閉店率の地域差（記録の偏りの疑いも込みで）")
    for label, sel in [("福岡市", lambda r: r["city"] == "40130"),
                       ("北九州市", lambda r: r["city"] == "40100"),
                       ("その他", lambda r: r["city"] not in ("40130", "40100"))]:
        sub = [r for r in rows if sel(r)]
        c = sum(r["closed"] for r in sub)
        print(f"   {label:<8}{len(sub):>6,}店  閉店 {c:>4,}  {c/max(len(sub),1):>7.1%}")

    path = DATA / "closures.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n-> {path}")
    plot(curve, rows)


def plot(curve, rows) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for cand in ("Hiragino Sans", "Hiragino Maru Gothic ProN", "YuGothic", "AppleGothic"):
        if any(cand in f.name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = cand
            break

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.4), dpi=160)
    fig.patch.set_facecolor("#E9E7DF")
    for ax in axes:
        ax.set_facecolor("#F2F0E9")
        ax.grid(True, color="#C9C6B8", lw=.5, alpha=.7)

    ax = axes[0]
    labels = [c[0] for c in curve]
    rates = [c[2] for c in curve]
    ax.bar(range(len(curve)), rates, color="#8A3B2E", alpha=.85)
    ax.set_xticks(range(len(curve)))
    ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=9)
    ax.set_ylabel("閉店率")
    ax.set_title("周辺の1店あたり人口 と 閉店率", pad=10)
    for i, (l, n, r) in enumerate(curve):
        ax.text(i, r + .004, f"{r:.0%}\nn={n:,}", ha="center", fontsize=8, color="#3D4F50")

    ax = axes[1]
    live = [r["over_supply"] for r in rows if not r["closed"]]
    dead = [r["over_supply"] for r in rows if r["closed"]]
    bins = np.linspace(-6, 10, 33)
    ax.hist(live, bins=bins, alpha=.75, label="営業中", color="#1F5C55", density=True)
    ax.hist(dead, bins=bins, alpha=.6, label="閉店", color="#8A3B2E", density=True)
    ax.axvline(0, color="#6B7A79", lw=1, ls="--")
    ax.set_xlabel("供給過剰度（3x3の実店舗数 − 期待店舗数）")
    ax.set_ylabel("割合")
    ax.set_title("閉店した店は、混んだ場所にあったか", pad=10)
    ax.legend(frameon=False)

    fig.tight_layout()
    fig.savefig(OUT / "closure.png", facecolor=fig.get_facecolor())
    print(f"-> {OUT/'closure.png'}")


if __name__ == "__main__":
    main()
