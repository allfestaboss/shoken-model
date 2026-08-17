#!/usr/bin/env python3
"""「どの業種が増えるか」をメッシュ単位で検定する。

県単位では信号が出なかった（r=+0.085・t=1.5）。ただ県はこのモデルが最も弱い粒度で、
そもそも「市町村では残差が意味を持たない」というのがこの企画の出発点だった。
モデルが強いのはメッシュ単位なので、そこで測り直す。

問いはこう:
  あるマスに1軒開いた。そのマスについてモデルが業種を並べたとき、
  実際に開いた業種は上位に来ていたか。

比べるのは**全国の開店しやすさで割ったあと**の値。そうしないと
「レストランはどこでもよく開く」だけで上位になってしまう。

  マスmでの業種fの見込み  =  λf(m) / Σλf(全国)

座標つきの開店データが要る。酒販免許（座標化済み）と
食品衛生（緯度経度が最初から入っている）を使う。

  .venv-duck/bin/python test_which_format_mesh.py
"""
import csv
import gzip
import io
import math
import re
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
import mesh_model as M  # noqa: E402
from formats import NAME  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
CUTOFF = (date.today() - timedelta(days=365)).isoformat()
FMTS = ["conv", "drug", "super", "restaurant", "bar", "cafe", "bakery"]
FOOD_KIND = [("bar", ("居酒屋", "バー", "スナック", "パブ", "クラブ")),
             ("cafe", ("カフェ", "喫茶", "軽食")),
             ("restaurant", ())]
MOBILE = ("自動車", "露店", "仮設", "臨時", "自動販売機", "行商", "移動")


def clean(s):
    return re.sub(r"^[\s①-⑿\d.、]+", "", (s or "").strip())


def mesh_index(lat, lon):
    return math.floor(lat * 240), math.floor((lon - 100) * 160)


def openings() -> list:
    """(lat_i, lon_i, 業種) の一覧。"""
    out = []
    m = {"コンビニ": "conv", "ドラッグ・薬局": "drug", "スーパー": "super"}
    for r in csv.DictReader((DATA / "openings_national_geo.csv").open(encoding="utf-8")):
        col = m.get(r["cat"])
        if col and (r.get("date") or "") >= CUTOFF:
            out.append((int(r["lat_i"]), int(r["lon_i"]), col))

    snaps = sorted(d for d in (DATA / "food" / "snapshots").glob("*") if d.is_dir())
    for path in sorted(list(snaps[-1].glob("*.csv.gz")) + list(snaps[-1].glob("*.csv"))):
        raw = path.read_bytes()
        if path.suffix == ".gz":
            raw = gzip.decompress(raw)
        for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="replace"))):
            d = (r.get("初回許可年月日") or "").replace("/", "-")
            if d < CUTOFF or not (r.get("緯度") or "").strip():
                continue
            gyotai = clean(r.get("業態", ""))
            if any(w in gyotai for w in MOBILE):
                continue
            kind = clean(r.get("営業の種類", ""))
            col = None
            if kind.startswith("菓子製造業"):
                col = "bakery"
            elif kind.startswith(("飲食店営業", "喫茶店営業")):
                col = next(c for c, w in FOOD_KIND if not w or any(x in gyotai for x in w))
            if col:
                try:
                    lat, lon = float(r["緯度"]), float(r["経度"])
                except ValueError:
                    continue
                la, lo = mesh_index(lat, lon)
                out.append((la, lo, col))
    return out


def main() -> None:
    ops = openings()
    print("開店（座標つき・直近12か月）:", dict(Counter(f for _, _, f in ops)), "\n")

    M.TARGET = "conv"
    mesh = M.load()
    idx = {(r["lat_i"], r["lon_i"]): i for i, r in enumerate(mesh)}
    X = M.features(mesh)

    prop = {}
    for f in FMTS:
        M.TARGET = f
        rows = M.load()
        n = np.array([r["stores"] for r in rows], dtype=float)
        lam = np.exp(np.clip(X @ M.fit_poisson(X, n), -30, 20))
        prop[f] = lam / lam.sum()          # 全国の開店しやすさで割る
        print(f"  {NAME[f]:<12}{int(n.sum()):>8,}店")

    P = np.column_stack([prop[f] for f in FMTS])
    col = {f: j for j, f in enumerate(FMTS)}

    ranks, tops = [], 0
    used = 0
    for la, lo, f in ops:
        i = idx.get((la, lo))
        if i is None or P[i].sum() <= 0:
            continue
        order = np.argsort(-P[i])
        pos = int(np.where(order == col[f])[0][0])
        ranks.append(pos / (len(FMTS) - 1))     # 0=最上位 1=最下位
        tops += pos == 0
        used += 1

    r = np.array(ranks)
    mean = r.mean()
    se = r.std(ddof=1) / math.sqrt(len(r))
    print(f"\n■ 実際に開いた業種は、モデルの並びで何番目だったか（{used:,}件）")
    print(f"   位置の平均      {mean:.4f}   （でたらめなら 0.5000）")
    print(f"   標準誤差        {se:.4f}")
    print(f"   でたらめとの差  {(mean - .5)/se:+.1f} 標準誤差"
          f"   {'（0.5より上位＝当たっている）' if mean < .5 else '（当たっていない）'}")
    print(f"   1位を当てた率   {tops/used:.1%}   （でたらめなら {1/len(FMTS):.1%}）")


if __name__ == "__main__":
    main()
