#!/usr/bin/env python3
"""まだ店が無いマスに、どのチェーンが出しそうかを付ける。

集積の正体はドミナント出店だった。全チェーンが自社の近くに出しており、
周辺の「コンビニのうち自社が占める割合」で自社の新店を他社の新店と見分けられる
（ミニストップ0.934 / ファミマ0.706 / ローソン0.694 / セブン0.569）。

ただしそれは**2択の識別**であって、5択の予測ではない。実際に
「どのチェーンが出すか」を当てにいくと、周辺シェアが最大のチェーンを答えるだけでは
37.5%しか当たらない（当てずっぽうは29.7%）。

効いたのは**出店の勢いの差**だった。店舗数に対する年間の新規開店は
  ミニストップ 7.4% / ファミマ 4.9% / ローソン 4.5% / セブン 2.4%
と3倍の開きがある。周辺シェアにこれを掛けると **48.3%**（当てずっぽうの1.63倍）。
勢いは**当てる県を除いて**推定するので、その県のデータは使っていない。

  .venv-duck/bin/python chain_candidates.py [件数]
     ->  data/chain_candidates.csv
"""
import csv
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
import mesh_model as M  # noqa: E402
from simulate import Geocoder, SCOPE_DENSITY, THRESHOLD, city_names, ring  # noqa: E402

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

# 列名 -> (屋号を見分ける正規表現, 表示名)
CHAINS = {
    "c_seven": (r"セブン[\-－ー–ｰ]?イレブン", "セブン-イレブン"),
    "c_family": (r"ファミリーマート", "ファミリーマート"),
    "c_lawson": (r"ローソン", "ローソン"),
    "c_ministop": (r"ミニストップ", "ミニストップ"),
}
OTHERS = ["c_seico", "c_other"]        # 分母には入れるが、予測の候補にはしない


def openings(idx):
    """(チェーン列, メッシュの行番号, 県コード) の一覧。"""
    out = []
    path = DATA / "openings_national_geo.csv"
    for r in csv.DictReader(path.open(encoding="utf-8")):
        if r["cat"] != "コンビニ":
            continue
        c = next((c for c, (p, _) in CHAINS.items() if re.search(p, r["shop"])), None)
        k = (int(r["lat_i"]), int(r["lon_i"]))
        if c and k in idx:
            out.append((c, idx[k], r["pref_code"]))
    return out


def main() -> None:
    topn = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    M.TARGET = "stores_fsq"
    rows = M.load()
    idx = {(r["lat_i"], r["lon_i"]): i for i, r in enumerate(rows)}
    for r in rows:
        r["pref"] = r.get("pref") or r["city"][:2]

    n = np.array([r["stores"] for r in rows], dtype=float)
    cols = list(CHAINS) + OTHERS
    cnt = {c: np.array([float(r.get(c) or 0) for r in rows]) for c in cols}
    r1 = {c: ring(rows, v, idx) for c, v in cnt.items()}
    tot1 = sum(r1.values())
    share = {c: r1[c] / np.maximum(tot1, 1) for c in cols}

    ops = openings(idx)
    # 出店の勢い。全国のぶんで作る（候補には正解が無いのでホールドアウト不要）
    rate = {c: sum(1 for k, _, _ in ops if k == c) / max(cnt[c].sum(), 1) for c in CHAINS}
    print("出店の勢い（店舗数に対する直近12か月の新規開店）")
    for c, (_, name) in CHAINS.items():
        print(f"   {name:<16}{int(cnt[c].sum()):>8,}店  新店 "
              f"{sum(1 for k,_,_ in ops if k==c):>4}  {rate[c]:>6.1%}")

    X = M.features(rows)
    lam = np.exp(np.clip(X @ M.fit_poisson(X, n), -30, 20))
    density = np.array([r["pop_r1"] for r in rows], dtype=float) / 2.25
    limit = SCOPE_DENSITY.get("stores_fsq")

    # 候補: コンビニが1店も無く、周辺には有り、密集しすぎていない
    ok = (n == 0) & (tot1 > 0)
    if limit:
        ok &= density < limit
    cand = np.where(ok)[0]

    score = np.column_stack([share[c] * rate[c] for c in CHAINS])
    who = np.array(list(CHAINS))[score.argmax(axis=1)]
    ssum = score.sum(axis=1)
    conf = np.where(ssum > 0, score.max(axis=1) / np.maximum(ssum, 1e-12), 0.0)
    # 周辺のコンビニが4チェーン以外だけのとき、根拠がゼロなのに argmax が
    # 先頭（セブン）を拾ってしまう。当てられないものは当てられないと書く
    known = ssum > 0

    order = cand[np.argsort(-lam[cand])][:topn]
    geo, names = Geocoder(), city_names()
    pop_r1 = np.array([r["pop_r1"] for r in rows], dtype=float)
    workers = np.array([r["workers_r1"] for r in rows], dtype=float)
    demand = pop_r1 + workers

    out = []
    for rank, i in enumerate(order, 1):
        r = rows[i]
        near = tot1[i]
        per = demand[i] / near if near > 0 else float("inf")
        out.append({
            "順位": rank,
            "市区町村": names.get(r["city"], r["city"]),
            "町名": geo.town(r["lat"], r["lon"]),
            "緯度": round(r["lat"], 5), "経度": round(r["lon"], 5),
            "期待店舗数": round(float(lam[i]), 2),
            "出しそうなチェーン": CHAINS[who[i]][1] if known[i] else "不明",
            "その確からしさ": round(float(conf[i]), 2) if known[i] else "—",
            "周辺のコンビニ": int(near),
            "1店あたり商圏人口": int(per) if near > 0 else "—",
            "判定": "余地あり" if per >= THRESHOLD else "飽和ぎみ",
        })
    geo.save()

    path = DATA / "chain_candidates.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    print(f"\n候補にできるマス {len(cand):,}（コンビニ0・周辺に有り"
          + (f"・人口密度{limit:,}人/km²未満）" if limit else "）"))
    print(f"\n{'':<3}{'場所':<24}{'期待':>6}{'出しそうなチェーン':>18}{'確からしさ':>11}"
          f"{'周辺':>6}{'人/店':>8}  判定")
    for r in out[:12]:
        c = r["その確からしさ"]
        cs = f"{c:.0%}" if c != "—" else "—"
        per = r["1店あたり商圏人口"]
        ps = f"{per:,}" if per != "—" else "—"
        print(f"{r['順位']:<3}{r['市区町村']+r['町名']:<24}{r['期待店舗数']:>6.2f}"
              f"{r['出しそうなチェーン']:>18}{cs:>11}"
              f"{r['周辺のコンビニ']:>6}{ps:>8}  {r['判定']}")
    print(f"\n-> {path}  {len(out):,}件")
    print(f"   予測の内訳 {dict(Counter(r['出しそうなチェーン'] for r in out))}")


if __name__ == "__main__":
    main()
