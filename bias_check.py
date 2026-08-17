#!/usr/bin/env python3
"""コンビニ残差が「経済」を測っているのか「OSMの描き込み具合」を測っているのかを切り分ける。

考え方:
  郵便局は位置がほぼ動かず、公式の全数（国土数値情報P30）がある。
  だから市町村ごとの OSM郵便局/公式郵便局 は、その自治体の**マッピング網羅率**の代理になる。

  もしコンビニの残差（実/期待）がこの網羅率と強く相関するなら、
  残差は経済ではなくマッピングを測っている ── つまり v0 の順位は使えない。

  相関が弱ければ、残差は少なくとも「描き込みの粗密」では説明できない。

  python3 bias_check.py   ->  data/bias_check.csv, out/bias.png
"""
import csv
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DATA, OUT = ROOT / "data", ROOT / "out"


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    def rank(v):
        order = v.argsort()
        r = np.empty_like(order, dtype=float)
        r[order] = np.arange(len(v), dtype=float)
        # 同順位は平均順位に
        _, inv, cnt = np.unique(v, return_inverse=True, return_counts=True)
        for i, c in enumerate(cnt):
            if c > 1:
                r[inv == i] = r[inv == i].mean()
        return r
    rx, ry = rank(x), rank(y)
    return float(np.corrcoef(rx, ry)[0, 1])


def main() -> None:
    res = {r["code"]: r for r in csv.DictReader((DATA / "residuals.csv").open(encoding="utf-8"))}
    post = list(csv.DictReader((DATA / "postoffices.csv").open(encoding="utf-8")))

    rows = []
    for p in post:
        r = res.get(p["code"])
        if not r or not r["ratio"] or not p["map_coverage"]:
            continue
        rows.append({
            "code": p["code"], "name": p["name"],
            "pop": int(r["pop"]),
            "store_ratio": float(r["ratio"]),          # コンビニ 実/期待
            "map_coverage": float(p["map_coverage"]),  # 郵便局 OSM/公式
            "osm_post": int(p["osm_post"]), "official_post": int(p["official_post"]),
            "stores": int(r["stores"]),
        })

    sr = np.array([r["store_ratio"] for r in rows])
    mc = np.array([r["map_coverage"] for r in rows])

    print(f"対象 {len(rows)} 市町村")
    print(f"郵便局の網羅率: 中央 {np.median(mc):.2f} / 最小 {mc.min():.2f} / 最大 {mc.max():.2f}")
    rho = spearman(mc, sr)
    r_p = float(np.corrcoef(mc, sr)[0, 1])
    print(f"\nコンビニ残差比 × 郵便局網羅率")
    print(f"  スピアマン順位相関 rho = {rho:+.3f}")
    print(f"  ピアソン相関       r   = {r_p:+.3f}")
    if abs(rho) >= 0.5:
        print("  -> 強い相関。残差はマッピングの粗密を測っている可能性が高い。順位は使えない。")
    elif abs(rho) >= 0.3:
        print("  -> 中程度の相関。残差の一部はマッピング由来。較正した順位を見るべき。")
    else:
        print("  -> 弱い相関。残差は少なくとも『描き込みの粗密』では説明できない。")

    # 較正: 郵便局の網羅率でコンビニ実数を割り戻し、真の店舗数を推定する
    for r in rows:
        cov = min(max(r["map_coverage"], .3), 1.5)      # 極端値で暴れないよう頭打ち
        r["stores_adj"] = round(r["stores"] / cov, 1)
        r["ratio_adj"] = round(r["store_ratio"] / cov, 3)

    print("\n■ 較正後も『少ない』（実/期待 を郵便局網羅率で補正）")
    for r in sorted(rows, key=lambda r: r["ratio_adj"])[:8]:
        print(f"  {r['name']:8} 補正後比 {r['ratio_adj']:.2f}（補正前 {r['store_ratio']:.2f}）"
              f"  郵便局 {r['osm_post']}/{r['official_post']}")
    print("\n■ 較正後も『多い』")
    for r in sorted(rows, key=lambda r: -r["ratio_adj"])[:8]:
        print(f"  {r['name']:8} 補正後比 {r['ratio_adj']:.2f}（補正前 {r['store_ratio']:.2f}）"
              f"  郵便局 {r['osm_post']}/{r['official_post']}")

    path = DATA / "bias_check.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["ratio_adj"]))
    print(f"\n-> {path}")

    plot(rows, rho)


def plot(rows: list, rho: float) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    for cand in ("Hiragino Sans", "Hiragino Maru Gothic ProN", "YuGothic", "AppleGothic"):
        if any(cand in f.name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = cand
            break

    mc = np.array([r["map_coverage"] for r in rows])
    sr = np.array([r["store_ratio"] for r in rows])

    fig, ax = plt.subplots(figsize=(8.4, 6), dpi=160)
    fig.patch.set_facecolor("#E9E7DF")
    ax.set_facecolor("#F2F0E9")
    ax.axhline(1, color="#6B7A79", lw=1, ls="--")
    ax.axvline(1, color="#6B7A79", lw=1, ls="--")
    ax.scatter(mc, sr, s=34, c="#1F5C55", alpha=.8, edgecolors="none", zorder=3)

    b, a = np.polyfit(mc, sr, 1)
    xs = np.linspace(mc.min(), mc.max(), 50)
    ax.plot(xs, a + b * xs, color="#8A3B2E", lw=1.4, zorder=2,
            label=f"回帰直線（順位相関 ρ={rho:+.2f}）")

    ax.set_xlabel("郵便局の OSM網羅率（OSM ÷ 公式）＝その自治体の描き込み具合")
    ax.set_ylabel("コンビニ 実測 ÷ 期待")
    ax.set_title("残差は経済か、マッピングか", pad=12)
    ax.grid(True, color="#C9C6B8", lw=.5, alpha=.7)
    ax.legend(frameon=False)

    for r in rows:
        if r["store_ratio"] > 1.8 or r["store_ratio"] < .5 or r["map_coverage"] < .6:
            ax.annotate(r["name"], (r["map_coverage"], r["store_ratio"]), fontsize=8,
                        xytext=(5, 3), textcoords="offset points", color="#3D4F50")

    fig.tight_layout()
    fig.savefig(OUT / "bias.png", facecolor=fig.get_facecolor())
    print(f"-> {OUT/'bias.png'}")


if __name__ == "__main__":
    main()
