#!/usr/bin/env python3
"""「この地域はどの業種が増えるか」が言えるかを検定する。

モデルが出すのは業種ごとの期待店舗数。ある地域について
「見込み ÷ 現状」が大きい業種ほど、その後よく開店するなら、
「この地域はこれから○○が増える」と言えることになる。

前回は開店データが3業種しかなく、比べられる組が141で決着しなかった
（業種ごとの開店頻度の差を除くと 57.4%・1.8標準誤差）。
出所を足して 7〜10業種・47県・74,507件にした。

肝は**二重中心化**。そのままだと2つの当たり前で有意になってしまう:
  業種の差 … コンビニは元々よく開く
  地域の差 … 都市部は何でもよく開く
どちらも「どの業種が増えるか」の答えではない。だから
  z[県, 業種] = x −（その県の平均）−（その業種の平均）＋（全体平均）
に直してから比べる。残るのは「その県にしては、その業種が多いか」だけ。

  .venv-duck/bin/python test_which_format.py
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
import mesh_model as M  # noqa: E402
from formats import NAME  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"


def load_openings():
    out = defaultdict(int)
    for r in csv.DictReader((DATA / "openings_by_format.csv").open(encoding="utf-8")):
        out[(r["pref"], r["format"])] = int(r["openings"])
    return out


def double_center(mat, mask):
    """行（県）と列（業種）の平均を抜く。欠けているセルは mask=False。"""
    z = np.where(mask, mat, np.nan)
    for _ in range(50):                       # 欠けがあるので繰り返して収束させる
        z = z - np.nanmean(z, axis=1, keepdims=True)
        z = z - np.nanmean(z, axis=0, keepdims=True)
    return z


def main() -> None:
    op = load_openings()
    fmts = sorted({f for _, f in op})
    prefs = sorted({p for p, _ in op})

    gap = np.zeros((len(prefs), len(fmts)))
    rate = np.zeros((len(prefs), len(fmts)))
    mask = np.zeros((len(prefs), len(fmts)), bool)

    for j, f in enumerate(fmts):
        M.TARGET = f
        mesh = M.load()
        for r in mesh:
            r["pref"] = r.get("pref") or r["city"][:2]
        n = np.array([r["stores"] for r in mesh], dtype=float)
        if n.sum() < 1000:
            continue
        X = M.features(mesh)
        lam = np.exp(np.clip(X @ M.fit_poisson(X, n), -30, 20))
        pref = np.array([r["pref"] for r in mesh])
        for i, p in enumerate(prefs):
            m = pref == p
            stock = n[m].sum()
            if stock < 30 or (p, f) not in op:
                continue
            gap[i, j] = lam[m].sum() / stock
            rate[i, j] = op[(p, f)] / stock
            mask[i, j] = True
        print(f"  {NAME.get(f, f):<12}{int(n.sum()):>8,}店  "
              f"{int(mask[:, j].sum()):>2}県ぶん使える")

    lg = double_center(np.log(np.where(mask, gap, 1) + 1e-9), mask)
    lr = double_center(np.log(np.where(mask, rate, 1) + 1e-9), mask)
    ok = mask & np.isfinite(lg) & np.isfinite(lr)
    x, y = lg[ok], lr[ok]
    r = float(np.corrcoef(x, y)[0, 1])
    n = len(x)
    t = r * np.sqrt((n - 2) / max(1 - r * r, 1e-12))

    print("\n■ 二重中心化のあと（県の差と業種の差を抜いたあと）")
    print(f"   セル数        {n}")
    print(f"   相関          r = {r:+.3f}")
    print(f"   t値           {t:+.1f}  （|t|>2 なら偶然とは言いにくい）")

    agree = tot = 0
    for i in range(len(prefs)):
        js = [j for j in range(len(fmts)) if ok[i, j]]
        for a in range(len(js)):
            for b in range(a + 1, len(js)):
                tot += 1
                if (lg[i, js[a]] - lg[i, js[b]]) * (lr[i, js[a]] - lr[i, js[b]]) > 0:
                    agree += 1
    se = (0.25 / tot) ** 0.5
    print(f"\n   県の中で業種2つを比べて一致した割合  {agree}/{tot} = {agree/tot:.1%}")
    print(f"   でたらめ(50%)からの隔たり            {(agree/tot - .5)/se:+.1f} 標準誤差")


if __name__ == "__main__":
    main()
