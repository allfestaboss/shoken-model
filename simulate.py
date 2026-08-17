#!/usr/bin/env python3
"""空きメッシュ一覧を出す。これがこのモデルの持ち場。

「どこに店があるか」を当てるのはモデルの仕事ではない（地図を見ればいい）。
既存店舗数で並べるだけの対抗馬に、飲食では負ける。
モデルが唯一答えられるのは**まだ1店も無い場所の順位づけ**で、
そこでは対抗馬は全メッシュが0で並び原理的に測れず、モデルは7〜9倍で当たった。

だから出力は「まだ1店も無いメッシュを、出店の見込み順に並べたもの」にする。

各候補には、そのまま判断に使えるように次を付ける:

  期待店舗数   … モデルが見込む店舗数。順位の根拠
  周辺の状況   … 3x3の人口・従業者数・既存店舗数
  1店あたり人口 … 周辺の商圏人口を既存店の数で割った値。閾値は2,200人。
                 商圏人口は**居住人口＋従業者数**。居住人口だけだと、
                 工業団地のように住民が少なく昼間人口が多い場所を
                 「飽和」と誤判定する。全国の開店で検定すると、従業者を足したほうが
                 分離が良い（マスあたり開店率の比、余地あり÷飽和ぎみ）:
                   コンビニ 1.73（居住だけ 1.76）
                   ドラッグ 1.77（居住だけ 1.47）
                   スーパー 3.96（居住だけ 2.71）
  判定        … 余地あり / 飽和ぎみ / 空白地帯。実際の開店で検定済みで、
                 まだ店の無いメッシュ全体を1.0とすると開店率は
                     コンビニ  余地あり5.27 / 飽和ぎみ3.05
                   ドラッグ  余地あり6.39 / 飽和ぎみ3.61
                   スーパー  余地あり5.58 / 飽和ぎみ1.41
                 （全国471,024メッシュ・実際の開店1,521件で検定。福岡だけのときは
                   コンビニ2.81/1.80、ドラッグ4.71/2.75 で、順序は同じ）
                 **周りに1店も無い「空白地帯」はほぼ死んでいる**。まっさらな土地に
                 最初の1店ができることは、まず無い。だから既定では候補から外す
                 （スーパーだけは飽和ぎみ5.43が余地あり4.23を上回ったが、
                   飽和ぎみ側の実績が3件しかなく、差とは言えない）
  2050年     … 将来推計人口で作り直した期待店舗数の比。人口だけを差し替えて計算する
                （従業者数の将来推計は存在しないので据え置き。ここは仮定）

  .venv-duck/bin/python simulate.py            # 全業態、上位40件ずつ
  .venv-duck/bin/python simulate.py stores_fsq 100
  .venv-duck/bin/python simulate.py all 40 --include-empty   # 空白地帯も残す
"""
import csv
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DATA, OUT = ROOT / "data", ROOT / "out"
sys.path.insert(0, str(ROOT))
import mesh_model as M  # noqa: E402

FORMATS = [("stores_fsq", "コンビニ"), ("drug_fsq", "ドラッグ・薬局"),
           ("super_fsq", "スーパー"), ("dining", "飲食")]
THRESHOLD = 2200          # 閉店711店から測った、1店あたり人口の下限
# 密集地を対象外にするかどうかは**業態で違う**。周辺人口密度（5x5/6.25km2）で
# 区切って、実際の新規開店で上位10%捕捉倍率を測った結果:
#
#   周辺人口密度        コンビニ   ドラッグ   スーパー
#   〜500人/km2          5.7x      —        —
#   500〜1,500           4.2x     5.4x     5.8x
#   1,500〜3,000         2.9x     2.4x     5.2x
#   3,000〜6,000         2.8x     4.0x     5.2x
#   6,000人/km2〜        2.3x     4.1x     4.7x
#
# **落ちるのはコンビニだけ**で、スーパーは都心でも4.7倍を保つ。店の数が少ない業態は
# 密集地でも立地が地理で決まるため。だから一律に大都市圏を外すのではなく、
# 落ちる業態だけ、落ちる密度から外す。
# なお密集帯だけで学習し直しても直らない（-0.6/-0.3/+0.4）。情報の側の問題で、
# 密集地の空きマスは条件がどれも似ている（期待店舗数の四分位の開きが
# 全体14.8倍に対し密集帯では2.9倍）。式を変えて解ける問題ではない。
SCOPE_DENSITY = {"stores_fsq": 1500}      # 人/km2。ここに無い業態は制限なし
KEEP_EMPTY = "--include-empty" in sys.argv
GSI = "https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress?lat={}&lon={}"
UA = "shoken-model/0.5 (research; boss@allfesta.com)"


def city_names() -> dict:
    return {r["code"]: r["name"]
            for r in csv.DictReader((DATA / "population.csv").open(encoding="utf-8"))}


def ring(rows, values, idx, rad=1):
    out = np.zeros(len(rows))
    span = range(-rad, rad + 1)
    for i, r in enumerate(rows):
        la, lo = r["lat_i"], r["lon_i"]
        out[i] = sum(values[idx[(la + a, lo + b)]]
                     for a in span for b in span if (la + a, lo + b) in idx)
    return out


def filled_ratio(rows, n, idx):
    """周囲5x5のうち、既に1店以上あるマスの割合。密集度の物差し。"""
    has = (n > 0).astype(float)
    ones = np.ones(len(rows))
    return ring(rows, has, idx, rad=2) / np.maximum(ring(rows, ones, idx, rad=2), 1)


def future_lambda(rows, beta, idx):
    """人口だけを2050年の推計値に差し替えて、期待店舗数を作り直す。"""
    pop50 = np.array([r["pop2050"] for r in rows], dtype=float)
    r1 = ring(rows, pop50, idx)
    saved = [(r["pop2020"], r["pop_r1"], r["pop_r2"]) for r in rows]
    for i, r in enumerate(rows):
        r["pop2020"], r["pop_r1"] = pop50[i], r1[i]
        r["pop_r2"] = r["pop_r2"] * (r1[i] / max(saved[i][1], 1))   # 5x5は同じ比率で伸縮
    X = M.features(rows)
    lam = np.exp(np.clip(X @ beta, -30, 20))
    for r, (a, b, c) in zip(rows, saved):
        r["pop2020"], r["pop_r1"], r["pop_r2"] = a, b, c
    return lam


class Geocoder:
    """国土地理院の逆ジオコーディング（無料・キー不要）。結果はファイルに貯める。"""

    def __init__(self):
        self.path = DATA / "revgeo.json"
        self.cache = json.loads(self.path.read_text()) if self.path.exists() else {}

    def town(self, lat, lon):
        key = f"{lat:.4f},{lon:.4f}"
        if key not in self.cache:
            try:
                req = urllib.request.Request(GSI.format(lat, lon), headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=20) as r:
                    d = json.load(r)
                self.cache[key] = (d.get("results") or {}).get("lv01Nm", "") or ""
            except Exception:  # noqa: BLE001
                self.cache[key] = ""
            time.sleep(1.0)
        return self.cache[key]

    def save(self):
        self.path.write_text(json.dumps(self.cache, ensure_ascii=False))


def build(target, label, topn, geo, names):
    M.TARGET = target
    rows = M.load()
    idx = {(r["lat_i"], r["lon_i"]): i for i, r in enumerate(rows)}
    n = np.array([r["stores"] for r in rows], dtype=float)
    X = M.features(rows)
    beta = M.fit_poisson(X, n)
    lam = np.exp(np.clip(X @ beta, -30, 20))
    lam50 = future_lambda(rows, beta, idx)

    ring_stores = ring(rows, n, idx)              # 中心が0なので3x3＝周辺の店舗数
    pop_r1 = np.array([r["pop_r1"] for r in rows], dtype=float)
    workers = np.array([r["workers_r1"] for r in rows], dtype=float)
    demand = pop_r1 + workers                     # 商圏人口＝居住＋昼間

    # まだ1店も無いメッシュのうち、周りにも1店も無い「空白地帯」は既定で外す。
    # 開店率が全体の0.0〜0.17倍しかなく、候補として並べる意味がないため。
    # さらに密集地（SCOPE_MAX以上）も外す。そこでは当たらないと実測で分かっている。
    dense = filled_ratio(rows, n, idx)
    density = pop_r1 / 2.25                  # 3x3の人口 -> 人/km2（3x3 = 2.25km2）
    limit = SCOPE_DENSITY.get(target)
    ok = n == 0
    if limit:
        ok &= density < limit
    if not KEEP_EMPTY:
        ok &= ring_stores > 0
    empty = np.where(ok)[0]
    n_dense = int(((n == 0) & (density >= limit)).sum()) if limit else 0
    print(f"   {label}: 空きマス {int((n==0).sum()):,}"
          + (f" / 人口密度{limit:,}人/km²以上で対象外 {n_dense:,}" if limit else " / 密度制限なし")
          + f" / 候補にできる {len(empty):,}")
    order = empty[np.argsort(-lam[empty])][:topn]

    out = []
    for rank, i in enumerate(order, 1):
        r = rows[i]
        near = ring_stores[i]
        per = demand[i] / near if near > 0 else float("inf")
        if near == 0:
            verdict = "空白地帯"
        elif per >= THRESHOLD:
            verdict = "余地あり"
        else:
            verdict = "飽和ぎみ"
        out.append({
            "順位": rank, "業態": label,
            "市区町村": names.get(r["city"], r["city"]),
            "町名": geo.town(r["lat"], r["lon"]),
            "緯度": round(r["lat"], 5), "経度": round(r["lon"], 5),
            "期待店舗数": round(float(lam[i]), 2),
            "周辺人口": int(pop_r1[i]), "周辺従業者": int(workers[i]),
            "周辺の既存店": int(near),
            "1店あたり商圏人口": "—" if near == 0 else int(per),
            "判定": verdict,
            "周辺人口密度": int(density[i]),
            "密集度": round(float(dense[i]), 3),
            "2050年比": round(float(lam50[i] / max(lam[i], 1e-9)), 2),
        })
    return out


def show(items) -> None:
    if not items:
        print("      該当なし")
        return
    print(f"{'':<3}{'場所':<26}{'期待':>6}{'周辺人口':>9}{'従業者':>8}"
          f"{'既存店':>7}{'人/店':>8}  {'判定':<10}{'2050年比':>8}")
    for r in items:
        place = f"{r['市区町村']}{r['町名']}"
        per = r["1店あたり商圏人口"]
        print(f"{r['順位']:<3}{place:<26}{r['期待店舗数']:>6.2f}{r['周辺人口']:>9,}"
              f"{r['周辺従業者']:>8,}{r['周辺の既存店']:>7}"
              f"{(f'{per:,}' if per != '—' else '—'):>8}  {r['判定']:<10}{r['2050年比']:>8.2f}")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    fmts = [(t, l) for t, l in FORMATS if not args or args[0] in ("all", t)]
    topn = int(args[1]) if len(args) > 1 else 40

    geo, names = Geocoder(), city_names()
    rowsout = []
    for target, label in fmts:
        got = build(target, label, topn, geo, names)
        rowsout += got
        yochi = [r for r in got if r["判定"] == "余地あり"]
        print(f"\n■ {label} ── 余地あり（周辺がまだ飽和していない）上位{min(len(yochi),8)}件")
        show(yochi[:8])
        print(f"\n   {label} ── 期待店舗数の順に全部（上位{min(topn,10)}件）")
        show(got[:10])
    geo.save()

    path = DATA / "candidates_empty.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rowsout[0].keys()))
        w.writeheader()
        w.writerows(rowsout)
    (OUT / "candidates.json").write_text(
        json.dumps(rowsout, ensure_ascii=False), encoding="utf-8")
    print(f"\n-> {path}  {len(rowsout):,}件")
    print(f"-> {OUT/'candidates.json'}")


if __name__ == "__main__":
    main()
