#!/usr/bin/env python3
"""特徴量の候補を「市街地に絞ったAUC」で測り直す。

全11,385メッシュで測るとAUC 0.87 出るが、その大半は
「田んぼの真ん中に店は無い」という自明な当たりで稼いでいる。
周辺人口3,000人以上（3,670メッシュ）に絞ると 0.77-0.82 まで落ちる。
**判断が要るのはこの3,670個のほう**なので、以後はこちらを主な物差しにする。

各候補は、基準（13変数）に足したときの差で評価する。
検証はいずれも空間ホールドアウト（市を丸ごと隠す）の平均。

  .venv-duck/bin/python ablation.py
"""
import sys

import numpy as np

sys.path.insert(0, ".")
import mesh_model as M  # noqa: E402

LAB = {"stores_fsq": "コンビニ", "drug_fsq": "ドラッグ・薬局", "super_fsq": "スーパー"}
CUT = 3000                      # 市街地とみなす周辺人口
OTHERS = ["stores_fsq", "drug_fsq", "super_fsq", "bakery", "clinic",
          "dentist", "hospital", "juku", "childcare"]


def ring(rows, values):
    idx = {(r["lat_i"], r["lon_i"]): i for i, r in enumerate(rows)}
    out = np.zeros(len(rows))
    for i, r in enumerate(rows):
        la, lo = r["lat_i"], r["lon_i"]
        out[i] = sum(values[idx[(la + a, lo + b)]]
                     for a in (-1, 0, 1) for b in (-1, 0, 1) if (la + a, lo + b) in idx)
    return out


def candidates(rows, target):
    g = lambda k: np.array([float(rows[i].get(k) or 0) for i in range(len(rows))])  # noqa: E731
    out = {}
    out["年齢構成"] = np.column_stack([g("young_share"), g("senior_share")])
    out["他業態の集積"] = np.column_stack(
        [np.log1p(ring(rows, g(c))) for c in OTHERS if c != target])
    out["地価"] = np.column_stack([np.log(g("land_price")), np.log(g("land_com"))])
    out["従業者数"] = np.column_stack([np.log1p(g("workers")), np.log1p(g("workers_r1")),
                                   np.log1p(g("work_retail_r1")), np.log1p(g("work_food_r1"))])
    out["建物数"] = np.column_stack([np.log1p(g("osm_buildings")),
                                  np.log1p(ring(rows, g("osm_buildings")))])
    return out


def score(X, n, y, keep, rows):
    rng = np.random.default_rng(0)
    city = np.array([r["city"] for r in rows])
    got = []
    for te in [city == "40130", city == "40100", rng.random(len(rows)) < 0.5]:
        beta = M.fit_poisson(X[~te], n[~te])
        s = np.exp(np.clip(X[te] @ beta, -30, 20))
        m = keep[te]
        got.append(M.auc(y[te][m], s[m]))
    return sum(got) / len(got)


def main() -> None:
    names = None
    table = {}
    for target, label in LAB.items():
        M.TARGET = target
        rows = M.load()
        base = M.features(rows)[:, :13]
        n = np.array([r["stores"] for r in rows], dtype=float)
        y = (n > 0).astype(float)
        keep = np.array([r["pop_r1"] for r in rows], dtype=float) >= CUT

        cand = candidates(rows, target)
        names = ["基準（13変数）"] + list(cand) + ["全部のせ"]
        vals = [score(base, n, y, keep, rows)]
        for c in cand.values():
            vals.append(score(np.column_stack([base, c]), n, y, keep, rows))
        vals.append(score(np.column_stack([base] + list(cand.values())), n, y, keep, rows))
        table[label] = vals

    print(f"市街地（周辺人口{CUT:,}人以上）に絞ったAUC\n")
    head = f"{'':<18}" + "".join(f"{k:>16}" for k in table)
    print(head)
    for i, name in enumerate(names):
        line = f"{name:<18}"
        for label in table:
            v = table[label][i]
            d = v - table[label][0]
            line += f"{v:>10.3f}{'' if i == 0 else f'{d:>+6.3f}'}" if i else f"{v:>16.3f}"
        print(line)


if __name__ == "__main__":
    main()
