#!/usr/bin/env python3
"""モデルの頭打ちが「特徴量不足」なのか「式の形」なのかを切り分ける。

これまでのポアソン回帰は log(特徴量) の線形和という強い仮定を置いている。
AUC 0.86 で止まっているのが、
  (A) 使っている情報が足りない  のか
  (B) 情報はあるのに直線で結んでいるせいで取り出せていない のか
は、同じ特徴量のまま非線形なモデル（勾配ブースティング）に替えれば分かる。
上がれば (B)、変わらなければ (A) で、次にやるべきことが真逆になる。

検証は今までどおり空間ホールドアウト（市を丸ごと隠す）。

  .venv-duck/bin/python strengthen.py [業種...]
"""
import sys

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

sys.path.insert(0, ".")
import mesh_model as M  # noqa: E402

TARGETS = sys.argv[1:] or ["stores_fsq", "drug_fsq", "super_fsq"]
LABEL = {"stores_fsq": "コンビニ", "drug_fsq": "ドラッグ・薬局", "super_fsq": "スーパー",
         "childcare": "保育園・幼稚園", "juku": "学習塾", "hospital": "病院",
         "dentist": "歯科", "clinic": "診療所", "bakery": "パン屋"}


def splits(rows):
    rng = np.random.default_rng(0)
    city = np.array([r["city"] for r in rows])
    return [("福岡市", city == "40130"), ("北九州市", city == "40100"),
            ("ランダム半分", rng.random(len(rows)) < 0.5)]


def main() -> None:
    print(f"{'業種':<16}{'隠した所':<12}{'ポアソン':>9}{'勾配ブースティング':>14}{'差':>8}")
    for target in TARGETS:
        M.TARGET = target
        rows = M.load()
        X = M.features(rows)[:, :13]
        n = np.array([r["stores"] for r in rows], dtype=float)
        y = (n > 0).astype(float)
        got = []
        for name, te in splits(rows):
            tr = ~te
            beta = M.fit_poisson(X[tr], n[tr])
            a_glm = M.auc(y[te], np.exp(np.clip(X[te] @ beta, -30, 20)))

            gb = HistGradientBoostingRegressor(
                loss="poisson", max_iter=400, learning_rate=0.06,
                max_leaf_nodes=31, min_samples_leaf=40,
                l2_regularization=1.0, random_state=0)
            gb.fit(X[tr], n[tr])
            a_gb = M.auc(y[te], gb.predict(X[te]))

            got.append((a_glm, a_gb))
            print(f"{LABEL.get(target, target):<16}{name:<12}{a_glm:>9.3f}"
                  f"{a_gb:>14.3f}{a_gb - a_glm:>+8.3f}")
        g = np.array(got)
        print(f"{'':<16}{'平均':<12}{g[:,0].mean():>9.3f}{g[:,1].mean():>14.3f}"
              f"{g[:,1].mean()-g[:,0].mean():>+8.3f}\n")


if __name__ == "__main__":
    main()
