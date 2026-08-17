#!/usr/bin/env python3
"""飲食店の前向き検証。2024年1月で時間を切って、それ以降の開店を当てられるか。

酒販免許でやった検証は「新店を差し引いてから学習し直す」形だった。今回はデータが
5年分あるので、**ある時点までの状態だけで学習し、その後に開いた店で答え合わせする**
という、より素直な時間の切り方ができる。

2つの学習の仕方を並べて出す。

  台帳のみ  … 2021年6月〜2023年12月に許可が下りた店だけを学習に使う。
              出所が1つなので前提が少ないが、それ以前からある店が入らない
  FSQ差引   … Foursquareの現在の店舗数から、2024年以降の開店を引いて
              2023年末の状態を復元して学習する。古い店も入るが出所が2つ混ざる

どちらでも同じ結論になるなら、その結論は出所の選び方に依存していない。

  .venv-duck/bin/python validate_food.py
"""
import csv
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DATA, OUT = ROOT / "data", ROOT / "out"
sys.path.insert(0, str(ROOT))
import mesh_model as M  # noqa: E402

CUTOFF = "2024-01-01"
NIGHT = ("居酒屋", "バー", "スナック", "パブ", "クラブ", "料亭")
DAY = ("カフェ", "喫茶", "軽食", "菓子", "パン")


def mesh_index(lat, lon):
    return math.floor(lat * 240), math.floor((lon - 100) * 160)


def load_openings() -> list:
    out = []
    for r in csv.DictReader((DATA / "food_open.csv").open(encoding="utf-8")):
        d = (r["初回許可年月日"] or "").replace("/", "-")
        if len(d) < 10:
            continue
        try:
            lat, lon = float(r["緯度"]), float(r["経度"])
        except ValueError:
            continue
        if not (32.9 <= lat <= 34.1 and 129.8 <= lon <= 131.4):
            continue
        g = r["業態"] or ""
        kind = ("夜" if any(w in g for w in NIGHT)
                else "昼" if any(w in g for w in DAY) else "不明")
        la, lo = mesh_index(lat, lon)
        out.append({"date": d, "lat_i": la, "lon_i": lo, "kind": kind,
                    "closed": bool((r["廃業年月日"] or "").strip())})
    return out


def rank_positions(rows, stock, opens):
    """stock を目的変数に学習し、opens が予測順位のどこに落ちたかを返す。"""
    X = M.features(rows)
    beta = M.fit_poisson(X, np.asarray(stock, dtype=float))
    lam = np.exp(np.clip(X @ beta, -30, 20))
    order = np.argsort(-lam)
    rank = np.empty(len(lam), int)
    rank[order] = np.arange(len(lam))
    pos_of = {(r["lat_i"], r["lon_i"]): rank[i] / len(rows) for i, r in enumerate(rows)}
    return np.array([pos_of[(o["lat_i"], o["lon_i"])] for o in opens
                     if (o["lat_i"], o["lon_i"]) in pos_of])


def report(name, pos, n_open):
    if len(pos) == 0:
        print(f"{name:<22}該当なし")
        return
    print(f"{name:<22}{len(pos):>6,}{np.median(pos):>10.3f}"
          f"{(pos <= .01).mean():>9.1%}{(pos <= .05).mean():>9.1%}"
          f"{(pos <= .10).mean():>9.1%}{(pos <= .20).mean():>9.1%}"
          f"{(pos <= .10).mean()/.10:>8.1f}x")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    opens_all = load_openings()
    pre = [o for o in opens_all if o["date"] < CUTOFF]
    post = [o for o in opens_all if o["date"] >= CUTOFF]
    print(f"台帳の開店 {len(opens_all):,}件 = 学習に使う{CUTOFF}より前 {len(pre):,}"
          f" ／ 答え合わせに使うそれ以降 {len(post):,}")
    print(f"   答え合わせ側の内訳 {dict(Counter(o['kind'] for o in post))}\n")

    M.TARGET = "dining"
    rows = M.load()
    idx = {(r["lat_i"], r["lon_i"]): i for i, r in enumerate(rows)}

    # (1) 台帳のみ: 2021年6月〜2023年12月の許可数を目的変数にする
    stock_led = np.zeros(len(rows))
    for o in pre:
        k = (o["lat_i"], o["lon_i"])
        if k in idx:
            stock_led[idx[k]] += 1

    # (2) FSQ差引: 現在の店舗数から2024年以降の開店を引いて2023年末を復元
    stock_fsq = np.array([r["stores"] for r in rows], dtype=float)
    sub = Counter((o["lat_i"], o["lon_i"]) for o in post)
    for k, c in sub.items():
        if k in idx:
            stock_fsq[idx[k]] = max(0.0, stock_fsq[idx[k]] - c)

    head = (f"{'学習の仕方 / 区分':<22}{'新店':>6}{'順位中央値':>10}"
            f"{'上位1%':>9}{'上位5%':>9}{'上位10%':>9}{'上位20%':>9}{'倍率':>9}")
    for label, stock in [("台帳のみ", stock_led), ("FSQ差引", stock_fsq)]:
        print(head)
        report(f"{label} 全部", rank_positions(rows, stock, post), len(post))
        for kind in ("夜", "昼"):
            sel = [o for o in post if o["kind"] == kind]
            if len(sel) >= 30:
                report(f"{label} {kind}の店", rank_positions(rows, stock, sel), len(sel))
        print(f"{'でたらめなら':<22}{'':>6}{0.5:>10.3f}{0.01:>9.1%}{0.05:>9.1%}"
              f"{0.10:>9.1%}{0.20:>9.1%}{1.0:>8.1f}x\n")


if __name__ == "__main__":
    main()
