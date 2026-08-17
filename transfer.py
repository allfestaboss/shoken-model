#!/usr/bin/env python3
"""福岡で学習した係数が、佐賀・長崎で通用するか。

これまで学習も検証も福岡県内で完結していた。市を隠すホールドアウトはやったが、
県をまたいだことは一度も無い。県内ですら北九州（車社会）は道路が効き、
福岡市（鉄道）は駅が効くので、県が変われば係数が変わる可能性は高い。

  移るなら … 全国1つのモデルで済む
  移らないなら … 地域ごとにモデルが要る

これで事業の形が変わるので、他の何より先に測る。

比べるのは3つ。
  福岡で学習   … 佐賀のデータを1行も見ていない。これが本番の条件
  現地で学習   … その県の半分で学習し、残り半分で測る。**到達しうる上限**
  でたらめ     … 下限

上限と本番の差が「県をまたぐ代償」で、これが小さければ移る。

  .venv-duck/bin/python transfer.py
"""
import sys

import numpy as np

sys.path.insert(0, ".")
import mesh_model as M  # noqa: E402

CUT = 3000
LAB = {"stores_fsq": "コンビニ", "drug_fsq": "ドラッグ・薬局",
       "super_fsq": "スーパー", "dining": "飲食"}
PREF_NAME = {"40": "福岡", "41": "佐賀", "42": "長崎", "23": "愛知", "05": "秋田"}
TRAIN = "40"          # 学習に使う県（ここだけで学習し、他県はデータを1行も見ない）


def load(target):
    M.TARGET = target
    rows = M.load()
    for r in rows:
        r["pref"] = r.get("pref") or r["city"][:2]
    return rows


def auc_on(rows, beta, sel):
    X = M.features([rows[i] for i in sel])
    n = np.array([rows[i]["stores"] for i in sel], dtype=float)
    y = (n > 0).astype(float)
    keep = np.array([rows[i]["pop_r1"] for i in sel], dtype=float) >= CUT
    lam = np.exp(np.clip(X @ beta, -30, 20))
    return M.auc(y[keep], lam[keep]), int(keep.sum()), int(y[keep].sum())


def main() -> None:
    rng = np.random.default_rng(0)
    print(f"{'業態':<16}{'予測する県':<10}{'福岡で学習':>11}{'現地で学習':>11}"
          f"{'代償':>8}{'市街地メッシュ':>13}{'店あり':>8}")
    for target, label in LAB.items():
        rows = load(target)
        pref = np.array([r["pref"] for r in rows])
        n_all = np.array([r["stores"] for r in rows], dtype=float)
        X_all = M.features(rows)

        beta_fk = M.fit_poisson(X_all[pref == TRAIN], n_all[pref == TRAIN])
        for p in [q for q in PREF_NAME if q != TRAIN and (pref == q).any()]:
            sel = np.where(pref == p)[0]
            a_fk, m, pos = auc_on(rows, beta_fk, sel)

            half = rng.random(len(sel)) < 0.5      # 現地で学習した場合の上限
            beta_lo = M.fit_poisson(X_all[sel[half]], n_all[sel[half]])
            a_lo, _, _ = auc_on(rows, beta_lo, sel[~half])

            print(f"{label:<16}{PREF_NAME[p]:<10}{a_fk:>11.3f}{a_lo:>11.3f}"
                  f"{a_lo - a_fk:>+8.3f}{m:>13,}{pos:>8,}")
        print()

    # どの係数が県で変わるのかを見る
    print("\n■ 係数はどれくらい変わるか（標準化・コンビニ）")
    rows = load("stores_fsq")
    pref = np.array([r["pref"] for r in rows])
    n = np.array([r["stores"] for r in rows], dtype=float)
    X = M.features(rows)
    sd = X.std(axis=0)
    sd[sd == 0] = 1
    Xs = np.column_stack([np.ones(len(rows)), (X[:, 1:] - X[:, 1:].mean(0)) / sd[1:]])
    plist = [q for q in PREF_NAME if (pref == q).any()]
    betas = {p: M.fit_poisson(Xs[pref == p], n[pref == p]) for p in plist}
    print(f"{'変数':<18}" + "".join(f"{PREF_NAME[p]:>9}" for p in plist) + f"{'ばらつき':>10}")
    order = sorted(range(1, len(M.FEATURES)),
                   key=lambda i: -np.std([betas[p][i] for p in betas]))
    for i in order[:8]:
        vals = [betas[p][i] for p in plist]
        print(f"{M.FEATURES[i]:<18}" + "".join(f"{v:>9.3f}" for v in vals)
              + f"{np.std(vals):>10.3f}")


if __name__ == "__main__":
    main()
