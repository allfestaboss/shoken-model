#!/usr/bin/env python3
"""「どこが消えるか」を、過去で学習して未来で検証する。

■ なぜこれができるようになったか
  開店日は使えない（date_created は2010-11年に半数が集中＝FSQの一括投入で、実際の開店ではない）。
  だが閉店日は2014-2025年に均等に散っている。閉店だけなら時間方向に切れる。

  以前「予測の検証には時系列が要るが、それは存在しない」と結論した。半分は手に入った。

■ 検証の形
  2015年末に営業していた店だけを対象に、2016-2020年に閉じたかを学習する。
  そのモデルで、2020年末に営業していた店が2021-2025年に閉じるかを予測する。
  **学習期間と検証期間が重ならない。** 当てられればAUCが0.5を超える。

  競合の数も「その時点で開いていた店」で数え直す（今の店舗数を使うと未来の情報が混ざる）。

  python3 survival.py   ->  data/survival.csv, out/survival.png
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parent
DATA, OUT = ROOT / "data", ROOT / "out"


def year_of(s: str):
    try:
        return int((s or "")[:4])
    except ValueError:
        return None


def load():
    mesh = {(int(r["lat_i"]), int(r["lon_i"])): r
            for r in csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8"))}
    stores = []
    for r in csv.DictReader((DATA / "fsq_places.csv").open(encoding="utf-8")):
        if r["category"] != "convenience_store":
            continue
        idx = (int(r["lat_i"]), int(r["lon_i"]))
        m = mesh.get(idx)
        if not m or float(m["pop_r1"]) < 500:
            continue
        stores.append({"idx": idx, "name": r["name"], "lat": float(r["lat"]),
                       "lon": float(r["lon"]), "closed_year": year_of(r["date_closed"]),
                       "pop_r1": float(m["pop_r1"]), "city": m["city"],
                       "build_share": float(m["build_share"] or 0),
                       "trunk_m": float(m["trunk_m"] or 0),
                       "station_m": float(m["station_m"] or 0),
                       "pop_decline": 1 - float(m["pop2050"]) / max(float(m["pop2020"]), 1)})
    return stores


def snapshot(stores: list, cutoff: int, horizon: int):
    """cutoff年末に開いていた店と、その後horizon年以内に閉じたかを返す。"""
    alive = [s for s in stores if s["closed_year"] is None or s["closed_year"] > cutoff]
    per_mesh = defaultdict(int)
    for s in alive:
        per_mesh[s["idx"]] += 1

    def around(idx):
        la, lo = idx
        return sum(per_mesh.get((la + i, lo + j), 0) for i in (-1, 0, 1) for j in (-1, 0, 1))

    rows = []
    for s in alive:
        n = around(s["idx"])
        if n == 0:
            continue
        y = s["closed_year"]
        rows.append({**s, "n_r1": n, "pop_per_store": s["pop_r1"] / n,
                     "died": int(y is not None and cutoff < y <= cutoff + horizon)})
    return rows


def design(rows: list) -> np.ndarray:
    g = lambda f: np.array([f(r) for r in rows], dtype=float)
    def z(v):
        return (v - v.mean()) / (v.std() + 1e-9)
    return np.column_stack([
        np.ones(len(rows)),
        z(g(lambda r: math.log(r["n_r1"]))),                 # 競合
        z(g(lambda r: math.log1p(r["pop_r1"]))),             # 需要
        z(g(lambda r: math.log(r["pop_per_store"]))),        # 混み具合
        z(g(lambda r: r["build_share"])),
        z(g(lambda r: math.log1p(r["station_m"]))),
        z(g(lambda r: r["pop_decline"])),
    ])


def fit(X, y):
    def nll(b):
        zz = np.clip(X @ b, -30, 30)
        return -np.sum(y * zz - np.log1p(np.exp(zz))) + 1e-2 * np.sum(b[1:] ** 2)

    def grad(b):
        zz = np.clip(X @ b, -30, 30)
        g = -X.T @ (y - 1 / (1 + np.exp(-zz)))
        g[1:] += 2e-2 * b[1:]
        return g
    return minimize(nll, np.zeros(X.shape[1]), jac=grad, method="L-BFGS-B").x


def auc(y, p) -> float:
    y = np.asarray(y, float)
    order = np.asarray(p).argsort()
    ranks = np.empty(len(p), float)
    ranks[order] = np.arange(1, len(p) + 1)
    pos, neg = y == 1, y == 0
    if pos.sum() == 0 or neg.sum() == 0:
        return float("nan")
    return float((ranks[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * neg.sum()))


def main() -> None:
    OUT.mkdir(exist_ok=True)
    stores = load()
    print(f"コンビニ {len(stores):,} 店（閉店 {sum(1 for s in stores if s['closed_year']):,}）\n")

    train = snapshot(stores, cutoff=2015, horizon=5)     # 2016-2020 に閉じたか
    test = snapshot(stores, cutoff=2020, horizon=5)      # 2021-2025 に閉じたか
    print(f"学習: 2015年末に営業 {len(train):,}店 → 2016-2020に閉店 {sum(r['died'] for r in train):,}店"
          f"（{sum(r['died'] for r in train)/len(train):.1%}）")
    print(f"検証: 2020年末に営業 {len(test):,}店 → 2021-2025に閉店 {sum(r['died'] for r in test):,}店"
          f"（{sum(r['died'] for r in test)/len(test):.1%}）\n")

    Xtr, ytr = design(train), np.array([r["died"] for r in train], dtype=float)
    Xte, yte = design(test), np.array([r["died"] for r in test], dtype=float)
    beta = fit(Xtr, ytr)

    p_tr = 1 / (1 + np.exp(-np.clip(Xtr @ beta, -30, 30)))
    p_te = 1 / (1 + np.exp(-np.clip(Xte @ beta, -30, 30)))
    print(f"■ 学習期間内のAUC   {auc(ytr, p_tr):.3f}")
    print(f"■ **未来のAUC**     {auc(yte, p_te):.3f}  ← 学習に使っていない期間")

    # 比べる相手: 競合だけ / 人口だけ の単純な並べ方
    for label, key in [("競合（周辺店舗数）だけで並べる", lambda r: r["n_r1"]),
                       ("混み具合（1店あたり人口）だけ", lambda r: -r["pop_per_store"]),
                       ("人口だけ", lambda r: r["pop_r1"])]:
        v = np.array([key(r) for r in test], dtype=float)
        print(f"   参考: {label:<28}{auc(yte, v):.3f}")

    names = ["定数", "log 周辺店舗数", "log 3x3人口", "log 1店あたり人口",
             "建物用地率", "log 駅までの距離", "人口減少率"]
    print("\n係数（正なら閉店しやすい）")
    for n, b in zip(names, beta):
        print(f"   {n:<18}{b:+.3f}")

    # 十分位ごとの実際の閉店率（較正の確認）
    order = np.argsort(-p_te)
    print("\n■ 危険度の順に10等分したときの、実際の閉店率（2021-2025）")
    k = len(test) // 10
    for i in range(10):
        sel = order[i * k:(i + 1) * k]
        print(f"   第{i+1:>2}十分位  予測 {p_te[sel].mean():>6.1%}   実際 {yte[sel].mean():>6.1%}")

    for r, p in zip(test, p_te):
        r["risk"] = round(float(p), 4)
    path = DATA / "survival.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[k for k in test[0] if k != "idx"],
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(test, key=lambda r: -r["risk"]))
    print(f"\n-> {path}")
    plot(test, p_te, yte)


def plot(test, p, y) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for cand in ("Hiragino Sans", "Hiragino Maru Gothic ProN", "YuGothic", "AppleGothic"):
        if any(cand in f.name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = cand
            break

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.2), dpi=160)
    fig.patch.set_facecolor("#E9E7DF")
    for ax in axes:
        ax.set_facecolor("#F2F0E9")
        ax.grid(True, color="#C9C6B8", lw=.5, alpha=.7)

    order = np.argsort(-p)
    k = len(test) // 10
    xs, obs, pred = [], [], []
    for i in range(10):
        sel = order[i * k:(i + 1) * k]
        xs.append(i + 1)
        obs.append(y[sel].mean())
        pred.append(p[sel].mean())
    ax = axes[0]
    ax.bar([x - .18 for x in xs], pred, width=.36, label="予測", color="#1F5C55")
    ax.bar([x + .18 for x in xs], obs, width=.36, label="実際", color="#8A3B2E")
    ax.set_xticks(xs)
    ax.set_xlabel("危険度の順（1が最も危ない）")
    ax.set_ylabel("2021-2025の閉店率")
    ax.set_title("未来の閉店を当てられたか（学習は2016-2020）", pad=10)
    ax.legend(frameon=False)

    ax = axes[1]
    live = [r["pop_per_store"] for r, d in zip(test, y) if not d]
    dead = [r["pop_per_store"] for r, d in zip(test, y) if d]
    bins = np.linspace(0, 6000, 31)
    ax.hist(live, bins=bins, alpha=.75, density=True, color="#1F5C55", label="生き残った")
    ax.hist(dead, bins=bins, alpha=.6, density=True, color="#8A3B2E", label="2021-25に閉店")
    ax.axvline(2200, color="#6B7A79", lw=1.2, ls="--")
    ax.text(2260, ax.get_ylim()[1] * .9, "2,200人", fontsize=9, color="#3D4F50")
    ax.set_xlabel("2020年末時点の 周辺1店あたり人口")
    ax.set_ylabel("割合")
    ax.set_title("閉じた店は、混んだ場所にいた", pad=10)
    ax.legend(frameon=False)

    fig.tight_layout()
    fig.savefig(OUT / "survival.png", facecolor=fig.get_facecolor())
    print(f"-> {OUT/'survival.png'}")


if __name__ == "__main__":
    main()
