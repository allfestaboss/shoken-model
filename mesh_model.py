#!/usr/bin/env python3
"""500mメッシュの立地モデル。「この場所に店が何軒成立するか」を返す。

二値（店があるか）と、カウント（何軒あるか＝ポアソン）の両方を出して比べる。
二値は都心で飽和する（天神の3x3は実店舗81なのに、期待の上限が9）ので、
密集地まで扱うにはカウントが要る。

説明変数は4系統。**建物数は入れない**（よく描かれた場所ほど店も描かれているので、
需要ではなく測定のされ方を学んでしまう。建物数は候補の篩にだけ使う）。
  人口     : 自メッシュ / 3x3 / 5x5
  人の動き : 市町村の昼夜間比とその二乗（U字）
  土地     : 建物用地率・道路面積率
  通過需要 : 幹線道路の延長・二次幹線・生活道路・最寄り駅までの距離

  python3 mesh_model.py   ->  data/mesh_pred.csv, out/mesh.png
"""
import csv
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parent
DATA, OUT = ROOT / "data", ROOT / "out"
TARGET = sys.argv[1] if len(sys.argv) > 1 else "stores_ov"   # 既定はOverture


def load() -> list:
    rows = list(csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8")))
    for r in rows:
        for k in ("pop2020", "pop2030", "pop2040", "pop2050", "pop_r1", "pop_r2",
                  "day_night", "lat", "lon"):
            r[k] = float(r[k])
        for k in ("trunk_m", "second_m", "local_m", "station_m"):
            r[k] = float(r.get(k) or 0)
        # 店舗レイヤは切り替えられる: stores=OSM / stores_ov=Overture
        r["stores"] = int(r.get(TARGET) or 0)
        r["lat_i"], r["lon_i"] = int(r["lat_i"]), int(r["lon_i"])
        for k in ("workers", "workers_r1", "work_retail_r1", "work_food_r1",
                  "pax_near", "pax_r2"):
            r[k] = float(r.get(k) or 0)
        r["lu_known"] = 1.0 if r.get("build_share", "") != "" else 0.0
        r["build_share"] = float(r["build_share"]) if r.get("build_share", "") != "" else 0.0
        r["road_share"] = float(r["road_share"]) if r.get("road_share", "") != "" else 0.0
    return rows


FEATURES = ["定数", "log人口(自)", "log人口(3x3)", "log人口(5x5)",
            "log昼夜間比", "log昼夜間比^2", "建物用地率", "道路面積率", "土地利用有",
            "log幹線延長", "log二次幹線", "log生活道路", "log駅までの距離",
            "log従業者(自)", "log従業者(3x3)", "log他業種従業者(3x3)"]

# 自分と同じ業種の従業者数は使わない。小売従業者にはコンビニの店員が、
# 飲食従業者には飲食店の店員が入っており、答えの一部を特徴量に混ぜることになる。
# （実測では小売従業者は単独で +0.008 しか出さず、外しても精度は落ちない）
_RETAIL = ("stores_fsq", "drug_fsq", "super_fsq", "stores_ov", "drug_ov", "super_ov",
           "conv", "drug", "pharmacy", "super", "fashion", "elec", "furniture",
           "bookstore", "florist", "hardware", "sports", "depart", "autoretail")
_FOOD = ("dining", "restaurant", "bar", "cafe", "bakery")
SAME_INDUSTRY = {k: "work_retail_r1" for k in _RETAIL}
SAME_INDUSTRY.update({k: "work_food_r1" for k in _FOOD})


def features(rows: list, pop_key: str = "pop2020") -> np.ndarray:
    g = lambda k: np.array([r[k] for r in rows], dtype=float)
    dn = np.log(g("day_night") / 100)
    return np.column_stack([
        np.ones(len(rows)),
        np.log1p(np.array([r[pop_key] for r in rows], dtype=float)),
        np.log1p(g("pop_r1")), np.log1p(g("pop_r2")),
        dn, dn ** 2,
        g("build_share"), g("road_share"), g("lu_known"),
        np.log1p(g("trunk_m")), np.log1p(g("second_m")), np.log1p(g("local_m")),
        np.log1p(g("station_m")),
        # 昼間の需要。居住人口では見えないオフィス街を捉える。市町村単位の昼夜間比の
        # 代わりであり、これを入れると地価も他業態の集積も効かなくなる（どちらもこれの代理だった）
        np.log1p(g("workers")), np.log1p(g("workers_r1")),
        np.log1p(g("work_food_r1" if SAME_INDUSTRY.get(TARGET) == "work_retail_r1"
                   else "work_retail_r1")),
    ])


def _fit(X, y, nll, grad):
    mu, sd = X[:, 1:].mean(0), X[:, 1:].std(0) + 1e-9
    Z = np.column_stack([X[:, 0], (X[:, 1:] - mu) / sd])
    res = minimize(lambda b: nll(Z, y, b), np.zeros(Z.shape[1]),
                   jac=lambda b: grad(Z, y, b), method="L-BFGS-B")
    b = res.x
    out = np.empty_like(b)
    out[1:] = b[1:] / sd
    out[0] = b[0] - float((mu / sd) @ b[1:])
    return out


def fit_logistic(X, y):
    def nll(Z, y, b):
        z = np.clip(Z @ b, -30, 30)
        return -np.sum(y * z - np.log1p(np.exp(z))) + 1e-3 * np.sum(b[1:] ** 2)

    def grad(Z, y, b):
        z = np.clip(Z @ b, -30, 30)
        g = -Z.T @ (y - 1 / (1 + np.exp(-z)))
        g[1:] += 2e-3 * b[1:]
        return g
    return _fit(X, y, nll, grad)


def fit_poisson(X, y):
    """log(期待店舗数) = Xb。飽和しないので都心も扱える。"""
    def nll(Z, y, b):
        z = np.clip(Z @ b, -30, 20)
        return -np.sum(y * z - np.exp(z)) + 1e-3 * np.sum(b[1:] ** 2)

    def grad(Z, y, b):
        z = np.clip(Z @ b, -30, 20)
        g = -Z.T @ (y - np.exp(z))
        g[1:] += 2e-3 * b[1:]
        return g
    return _fit(X, y, nll, grad)


def auc(y, p) -> float:
    y = (np.asarray(y) > 0).astype(float)
    order = np.asarray(p).argsort()
    ranks = np.empty(len(p), float)
    ranks[order] = np.arange(1, len(p) + 1)
    pos, neg = y == 1, y == 0
    if pos.sum() == 0 or neg.sum() == 0:
        return float("nan")
    return float((ranks[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * neg.sum()))


def main() -> None:
    OUT.mkdir(exist_ok=True)
    rows = load()
    X = features(rows)
    n = np.array([r["stores"] for r in rows], dtype=float)     # 店舗数
    y = (n > 0).astype(float)                                   # 店の有無
    city = np.array([r["city"] for r in rows])
    print(f"メッシュ {len(rows):,} / 店ありメッシュ {int(y.sum()):,} / 総店舗 {int(n.sum()):,}\n")

    rng = np.random.default_rng(0)
    splits = [("福岡市を隠す", city == "40130"),
              ("北九州市を隠す", city == "40100"),
              ("ランダム半分", rng.random(len(rows)) < .5)]

    print(f"{'検証':<16}{'二値AUC':>9}{'ポアソンAUC':>12}{'予測店舗数':>11}{'実際':>8}")
    for name, te in splits:
        tr = ~te
        bl, bp = fit_logistic(X[tr], y[tr]), fit_poisson(X[tr], n[tr])
        p_bin = 1 / (1 + np.exp(-np.clip(X[te] @ bl, -30, 30)))
        lam = np.exp(np.clip(X[te] @ bp, -30, 20))
        print(f"{name:<16}{auc(y[te], p_bin):>9.3f}{auc(y[te], lam):>12.3f}"
              f"{lam.sum():>11.0f}{int(n[te].sum()):>8}")

    beta_p, beta_b = fit_poisson(X, n), fit_logistic(X, y)
    print("\nポアソンモデルの係数（log期待店舗数への寄与）")
    for f, b in zip(FEATURES, beta_p):
        print(f"   {f:<14}{b:+.3f}")

    lam = np.exp(np.clip(X @ beta_p, -30, 20))
    lam50 = np.exp(np.clip(features(rows, "pop2050") @ beta_p, -30, 20))
    p_bin = 1 / (1 + np.exp(-np.clip(X @ beta_b, -30, 30)))

    grid_l = {(r["lat_i"], r["lon_i"]): float(l) for r, l in zip(rows, lam)}
    grid_s = {(r["lat_i"], r["lon_i"]): r["stores"] for r in rows}

    def around(r, g):
        la, lo = r["lat_i"], r["lon_i"]
        return sum(g.get((la + i, lo + j), 0) for i in (-1, 0, 1) for j in (-1, 0, 1))

    for r, l, l50, pb in zip(rows, lam, lam50, p_bin):
        r["lambda"] = round(float(l), 4)
        r["lambda_2050"] = round(float(l50), 4)
        r["p_now"] = round(float(pb), 4)
        r["exp_r1"] = round(around(r, grid_l), 3)
        r["stores_r1"] = around(r, grid_s)
        r["deficit_r1"] = round(r["exp_r1"] - r["stores_r1"], 3)
        r["lambda_change"] = round(float(l50 - l), 4)

    print(f"\n期待店舗数の合計 {lam.sum():.0f}（実測 {int(n.sum()):,}）")
    dense = [r for r in rows if r["stores_r1"] >= 20]
    if dense:
        e = sum(r["exp_r1"] for r in dense) / len(dense)
        a = sum(r["stores_r1"] for r in dense) / len(dense)
        print(f"密集地（3x3に20店以上）{len(dense):,}メッシュ: 期待 平均{e:.1f} / 実際 平均{a:.1f}")
        print("   ※二値モデルでは期待の上限が9（3x3の枠数）で頭打ちになっていた箇所")

    path = DATA / "mesh_pred.csv"
    fields = ["lat_i", "lon_i", "lat", "lon", "city", "pop2020", "pop2050", "pop_r1", "pop_r2",
              "day_night", "build_share", "trunk_m", "station_m", "stores", "stores_r1",
              "lambda", "lambda_2050", "p_now", "exp_r1", "deficit_r1", "lambda_change"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\n-> {path}")
    plot(rows, lam)


def plot(rows, lam) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for cand in ("Hiragino Sans", "Hiragino Maru Gothic ProN", "YuGothic", "AppleGothic"):
        if any(cand in f.name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = cand
            break

    lat = np.array([r["lat"] for r in rows])
    lon = np.array([r["lon"] for r in rows])
    st = np.array([r["stores"] for r in rows], dtype=float)

    fig, axes = plt.subplots(1, 2, figsize=(13.5, 7.2), dpi=150)
    fig.patch.set_facecolor("#E9E7DF")
    for ax in axes:
        ax.set_facecolor("#F2F0E9")
        ax.set_aspect(1 / np.cos(np.deg2rad(33.5)))
        ax.set_xlabel("経度")
        ax.grid(True, color="#C9C6B8", lw=.4, alpha=.6)

    s = axes[0].scatter(lon, lat, c=np.clip(lam, 0, 3), s=1.6, cmap="YlGnBu")
    axes[0].set_title("期待店舗数（ポアソン・道路と駅を含む）", pad=10)
    axes[0].set_ylabel("緯度")
    fig.colorbar(s, ax=axes[0], shrink=.7, label="期待店舗数")

    resid = st - lam
    v = float(np.percentile(np.abs(resid), 99))
    s2 = axes[1].scatter(lon, lat, c=np.clip(resid, -v, v), s=1.6, cmap="RdYlGn_r")
    axes[1].set_title("実際 − 期待（赤＝多い / 緑＝少ない）", pad=10)
    fig.colorbar(s2, ax=axes[1], shrink=.7, label="差")

    fig.tight_layout()
    fig.savefig(OUT / "mesh.png", facecolor=fig.get_facecolor())
    print(f"-> {OUT/'mesh.png'}")


if __name__ == "__main__":
    main()
