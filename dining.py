#!/usr/bin/env python3
"""飲食店で立地モデルを回し、物差しの設計を検討する。

飲食は今までの3業態と2つの点で違う。

1. **需要の出どころが違うはず**。居酒屋の客は住民でも昼間の従業者でもなく、
   夜そこにいる人。だから昼の店（カフェ）と夜の店（居酒屋）で効く変数が
   変わるなら、それは「飲食」でひとくくりにする粒度が粗すぎたということ。

2. **数の散らばりが桁違い**。コンビニは1メッシュに数店だが、飲食は最大1,225店。
   「有る/無い」のAUCでは1店と1,225店が同じ「有る」になってしまう。
   そこで店舗数を捉える物差しも並べて出す:
     捕捉率 … 予測上位10%のメッシュに、県内の店舗総数の何%が入っているか
     順位相関 … 予測の大小と実際の店舗数の大小がどれだけ揃っているか

  .venv-duck/bin/python dining.py
"""
import sys

import numpy as np

sys.path.insert(0, ".")
import mesh_model as M  # noqa: E402

CUT = 3000
TARGETS = [("bar", "居酒屋・バー（夜）"), ("cafe", "カフェ（昼）"),
           ("restaurant", "レストラン"), ("dining", "飲食すべて"),
           ("stores_fsq", "コンビニ（比較）"), ("super_fsq", "スーパー（比較）")]


def spearman(a, b):
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    ra -= ra.mean()
    rb -= rb.mean()
    return float(ra @ rb / (np.linalg.norm(ra) * np.linalg.norm(rb)))


def blocks(rows):
    """特徴量の3段階。基準13変数 / ＋従業者 / ＋従業者＋駅乗降客数"""
    g = lambda k: np.array([float(r.get(k) or 0) for r in rows])  # noqa: E731
    base = M.features(rows)[:, :13]
    work = np.column_stack([np.log1p(g("workers")), np.log1p(g("workers_r1"))])
    pax = np.column_stack([np.log1p(g("pax_near")), np.log1p(g("pax_grav")),
                           np.log1p(g("pax_r2"))])
    return {"基準": base, "＋従業者": np.column_stack([base, work]),
            "＋従業者＋駅乗降": np.column_stack([base, work, pax])}


def evaluate(X, n, y, keep, rows):
    rng = np.random.default_rng(0)
    city = np.array([r["city"] for r in rows])
    auc, cap, sp = [], [], []
    for te in [city == "40130", city == "40100", rng.random(len(rows)) < 0.5]:
        beta = M.fit_poisson(X[~te], n[~te])
        lam = np.exp(np.clip(X[te] @ beta, -30, 20))
        m = keep[te]
        auc.append(M.auc(y[te][m], lam[m]))
        # 捕捉率: 予測上位10%のメッシュに実際の店舗数の何%が入るか（隠した市の全域で）
        k = max(1, int(len(lam) * 0.10))
        top = np.argsort(-lam)[:k]
        cap.append(n[te][top].sum() / max(n[te].sum(), 1))
        sp.append(spearman(lam[m], n[te][m]))
    return np.mean(auc), np.mean(cap), np.mean(sp)


def main() -> None:
    print(f"{'業種':<20}{'変数':<18}{'市街地AUC':>10}{'上位10%の捕捉':>14}{'順位相関':>10}")
    for target, label in TARGETS:
        M.TARGET = target
        rows = M.load()
        n = np.array([r["stores"] for r in rows], dtype=float)
        y = (n > 0).astype(float)
        keep = np.array([r["pop_r1"] for r in rows], dtype=float) >= CUT
        for i, (name, X) in enumerate(blocks(rows).items()):
            a, c, s = evaluate(X, n, y, keep, rows)
            print(f"{label if i == 0 else '':<20}{name:<18}{a:>10.3f}{c:>14.1%}{s:>10.3f}")
        print()


if __name__ == "__main__":
    main()
