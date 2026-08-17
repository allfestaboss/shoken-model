#!/usr/bin/env python3
"""「残差は次の出店を当てるか」を、公式データの時系列で検証する（ステップ3）。

■ なぜコンビニそのものでやらないか
  市区町村別のコンビニ店舗数は**日本の公的統計に存在しない**。
  業態別（コンビニ／ドラッグストア等）の集計は、商業統計・経済センサスとも
  「都道府県別」または「区部・市部・郡部別」までで、市区町村別は公表されていない。
  OSMのatticクエリ（過去時点の取得）も公開サーバーでは拒否された。

  そこで、市区町村別に複数年そろう **産業小分類589「その他の飲食料品小売業」**
  （コンビニを含むが、米穀店・豆腐店なども含む広めの箱）で、**方法そのもの**を検証する。

■ 検証の形
  1. 2009年のデータだけでモデルを作る（人口・昼夜間比）
  2. 2009年の残差（実際 − 期待）を出す
  3. その残差が、その後 2009→2014 の店舗数の伸びを当てるかを見る
     供給が需要に追いつくなら、残差がマイナス（＝足りない）ほど、その後よく増えるはず
     → 相関は **負** になるべき。正または無相関なら、残差に予測力は無い。

  python3 validate.py   ->  data/validation.csv, out/validate.png
"""
import csv
import json
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DATA, OUT = ROOT / "data", ROOT / "out"
APPID = Path.home().joinpath(".config/estat/appid").read_text().strip()

# 経済センサス‐基礎調査（同じ調査系列で揃える）。産業小分類 × 市区町村
TABLES = {
    2009: ("0003353919", None),      # 産業（小分類）別民営事業所数及び従業者数
    2014: ("0003353932", "001"),     # 産業（小分類）別全事業所・民営事業所数及び従業者数
}
IND_NAME = "589"                     # その他の飲食料品小売業（コンビニを含む）


def estat(endpoint: str, **params) -> dict:
    url = (f"https://api.e-stat.go.jp/rest/3.0/app/json/{endpoint}?"
           + urllib.parse.urlencode({"appId": APPID, **params}))
    with urllib.request.urlopen(url, timeout=180) as r:
        return json.load(r)


def industry_code(stats_id: str) -> str:
    """表ごとに産業分類のコード体系が違うので、589 のコードを引き直す。"""
    meta = estat("getMetaInfo", statsDataId=stats_id)
    for c in meta["GET_META_INFO"]["METADATA_INF"]["CLASS_INF"]["CLASS_OBJ"]:
        if "産業" not in str(c.get("@name")):
            continue
        items = c.get("CLASS")
        items = items if isinstance(items, list) else [items]
        for i in items:
            if i["@name"].replace(" ", "").startswith(IND_NAME):
                return i["@code"]
    raise SystemExit(f"{stats_id}: 589 が見つからない")


def establishments(year: int, codes: list) -> dict:
    stats_id, org = TABLES[year]
    params = {"statsDataId": stats_id, "cdCat01": industry_code(stats_id),
              "cdTab": "003", "cdArea": ",".join(codes), "limit": "300"}
    if org:
        params["cdCat02"] = org
    d = estat("getStatsData", **params)
    vals = d["GET_STATS_DATA"]["STATISTICAL_DATA"]["DATA_INF"]["VALUE"]
    vals = vals if isinstance(vals, list) else [vals]
    return {v["@area"]: int(v["$"]) for v in vals if str(v["$"]).lstrip("-").isdigit()}


def population_series(codes: list) -> dict:
    """統計ダッシュボード（キー不要）から年次人口。"""
    out = {}
    for i in range(0, len(codes), 20):
        url = ("https://dashboard.e-stat.go.jp/api/1.0/Json/getData?"
               + urllib.parse.urlencode({
                   "Lang": "JP", "IndicatorCode": "0201010000000010000",
                   "RegionCode": ",".join(codes[i:i + 20]), "Cycle": "3"}))
        with urllib.request.urlopen(url, timeout=90) as r:
            d = json.load(r)
        for o in d["GET_STATS"]["STATISTICAL_DATA"]["DATA_INF"]["DATA_OBJ"]:
            v = o["VALUE"]
            out.setdefault(v["@regionCode"], {})[int(v["@time"][:4])] = int(v["$"])
    return out


def nearest(series: dict, year: int) -> float:
    return float(series[min(series, key=lambda y: abs(y - year))])


def main() -> None:
    OUT.mkdir(exist_ok=True)
    muni = list(csv.DictReader((DATA / "population.csv").open(encoding="utf-8")))
    ctx = {r["code"]: r for r in csv.DictReader((DATA / "context.csv").open(encoding="utf-8"))}
    codes = [m["code"] for m in muni]

    print("経済センサス‐基礎調査から 589 を取得")
    e09, e14 = establishments(2009, codes), establishments(2014, codes)
    pops = population_series(codes)
    print(f"  2009年 {len(e09)}件 / 2014年 {len(e14)}件")

    rows = []
    for m in muni:
        c = m["code"]
        if c not in e09 or c not in e14 or e09[c] < 5 or c not in pops:
            continue                       # 5事業所未満は比が暴れるので除く
        rows.append({
            "code": c, "name": m["name"],
            "pop_2010": nearest(pops[c], 2010),
            "ratio_dn": float(ctx[c]["day_night_ratio"]),
            "e2009": e09[c], "e2014": e14[c],
            "growth": np.log(e14[c] / e09[c]),
        })
    print(f"  検証対象 {len(rows)} 市町村\n")

    # 1. 2009年だけでモデルを作る
    y = np.log(np.array([r["e2009"] for r in rows], dtype=float))
    lpop = np.log(np.array([r["pop_2010"] for r in rows], dtype=float))
    lr = np.log(np.array([r["ratio_dn"] for r in rows], dtype=float) / 100)
    X = np.column_stack([np.ones_like(y), lpop, lr, lr ** 2])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    r2 = 1 - float(((y - X @ beta) ** 2).sum()) / float(((y - y.mean()) ** 2).sum())
    print(f"2009年モデル: R^2={r2:.3f}  係数 {np.round(beta, 3)}")

    # 2. その残差が、2009->2014 の伸びを当てるか
    growth = np.array([r["growth"] for r in rows])
    r_pearson = float(np.corrcoef(resid, growth)[0, 1])
    print(f"\n残差(2009) × その後の伸び(2009→2014)")
    print(f"  相関 r = {r_pearson:+.3f}")
    if r_pearson < -0.2:
        print("  -> 負の相関。足りない地域ほどその後に増えている＝残差に予測力がある")
    elif r_pearson > 0.2:
        print("  -> 正の相関。多い地域ほどさらに増えている＝集中が進む（残差は逆向きの意味）")
    else:
        print("  -> ほぼ無相関。**残差はその後の出店を当てない**")

    # 比較用: 人口だけの単純モデルより当たるのか
    Xs = np.column_stack([np.ones_like(y), lpop])
    bs, *_ = np.linalg.lstsq(Xs, y, rcond=None)
    resid_simple = y - Xs @ bs
    print(f"  参考: 人口だけのモデルの残差との相関 r = "
          f"{float(np.corrcoef(resid_simple, growth)[0, 1]):+.3f}")
    print(f"  参考: 2009年の店舗数そのもの × 伸び       r = "
          f"{float(np.corrcoef(y, growth)[0, 1]):+.3f}")

    for r, e, g in zip(rows, resid, growth):
        r["residual_2009"] = round(float(e), 3)
        r["growth_09_14"] = round(float(g), 3)

    print("\n■ 2009年に『足りない』と出た上位5つが、その後どうなったか")
    for r in sorted(rows, key=lambda r: r["residual_2009"])[:5]:
        print(f"  {r['name']:8} 残差 {r['residual_2009']:+.2f}  "
              f"{r['e2009']:>4} -> {r['e2014']:>4} 事業所  伸び {r['growth_09_14']:+.2f}")
    print("\n■ 2009年に『多すぎる』と出た上位5つ")
    for r in sorted(rows, key=lambda r: -r["residual_2009"])[:5]:
        print(f"  {r['name']:8} 残差 {r['residual_2009']:+.2f}  "
              f"{r['e2009']:>4} -> {r['e2014']:>4} 事業所  伸び {r['growth_09_14']:+.2f}")

    path = DATA / "validation.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["residual_2009"]))
    print(f"\n-> {path}")

    plot(rows, resid, growth, r_pearson)


def plot(rows: list, resid, growth, r: float) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    for cand in ("Hiragino Sans", "Hiragino Maru Gothic ProN", "YuGothic", "AppleGothic"):
        if any(cand in f.name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = cand
            break

    fig, ax = plt.subplots(figsize=(8.6, 6), dpi=160)
    fig.patch.set_facecolor("#E9E7DF")
    ax.set_facecolor("#F2F0E9")
    ax.axhline(0, color="#6B7A79", lw=1, ls="--")
    ax.axvline(0, color="#6B7A79", lw=1, ls="--")
    ax.scatter(resid, growth, s=34, c="#1F5C55", alpha=.8, edgecolors="none", zorder=3)
    b, a = np.polyfit(resid, growth, 1)
    xs = np.linspace(resid.min(), resid.max(), 50)
    ax.plot(xs, a + b * xs, color="#8A3B2E", lw=1.4, zorder=2, label=f"回帰直線 r={r:+.2f}")
    ax.set_xlabel("2009年の残差（左ほど『足りない』）")
    ax.set_ylabel("2009→2014 の事業所数の伸び（対数）")
    ax.set_title("足りない地域は、その後ほんとうに増えたか", pad=12)
    ax.grid(True, color="#C9C6B8", lw=.5, alpha=.7)
    ax.legend(frameon=False)
    for i, row in enumerate(rows):
        if abs(resid[i]) > .45 or abs(growth[i]) > .45:
            ax.annotate(row["name"], (resid[i], growth[i]), fontsize=8,
                        xytext=(5, 3), textcoords="offset points", color="#3D4F50")
    fig.tight_layout()
    fig.savefig(OUT / "validate.png", facecolor=fig.get_facecolor())
    print(f"-> {OUT/'validate.png'}")


if __name__ == "__main__":
    main()
