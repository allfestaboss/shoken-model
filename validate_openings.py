#!/usr/bin/env python3
"""実際に開いた店が、モデルの高評価メッシュに落ちたかを検証する。

これがずっとやりたかったテスト。これまでは「いま店がある場所」を当てられるかしか
測れず、**新しく生まれる場所**を当てられるかは検証できなかった（開店データが無いため）。
国税庁の酒販免許から2025年7月〜2026年6月の新規開店95件が取れたので、初めて測れる。

  住所 -> 座標: 国土地理院のジオコーディング（無料・キー不要）
  https://msearch.gsi.go.jp/address-search/AddressSearch?q=...

■ 汚染について
  モデルの λ は人口・土地利用・道路だけから作る。店舗数は係数の推定にしか使われず、
  各メッシュの λ にそのメッシュの店舗数が直接入ることはない。
  新店95件が2,614店の係数推定に与える影響は無視できる範囲。

  .venv-duck/bin/python validate_openings.py   ->  data/openings_geo.csv
"""
import csv
import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DATA, OUT = ROOT / "data", ROOT / "out"
GSI = "https://msearch.gsi.go.jp/address-search/AddressSearch?q="


def mesh_index(lat: float, lon: float) -> tuple:
    return math.floor(lat * 240), math.floor((lon - 100) * 160)


def geocode(addr: str):
    url = GSI + urllib.parse.quote(f"福岡県{addr}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "shoken-model/0.4 (research)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        if not d:
            return None
        c = d[0]["geometry"]["coordinates"]
        return float(c[1]), float(c[0])
    except Exception:
        return None


def main() -> None:
    OUT.mkdir(exist_ok=True)
    cache = DATA / "openings_geo.csv"
    if cache.exists():
        geo = list(csv.DictReader(cache.open(encoding="utf-8")))
    else:
        rows = [r for r in csv.DictReader((DATA / "openings.csv").open(encoding="utf-8"))
                if r["kind"] == "新規"]
        geo = []
        for i, r in enumerate(rows, 1):
            pt = geocode(r["addr"])
            if pt:
                r["lat"], r["lon"] = pt
                la, lo = mesh_index(*pt)
                r["lat_i"], r["lon_i"] = la, lo
                geo.append(r)
            print(f"  {i:3}/{len(rows)} {r['shop'][:22]:<24}{'OK' if pt else '座標なし'}")
            time.sleep(1.0)
        with cache.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(geo[0].keys()))
            w.writeheader()
            w.writerows(geo)
        print(f"\n-> {cache}")

    pred = {(r["lat_i"], r["lon_i"]): r
            for r in csv.DictReader((DATA / "mesh_pred.csv").open(encoding="utf-8"))}
    lam_all = np.array([float(r["lambda"]) for r in pred.values()])
    order = np.argsort(-lam_all)
    ranks = np.empty(len(lam_all), int)
    ranks[order] = np.arange(len(lam_all))
    key_list = list(pred.keys())
    rank_of = {k: ranks[i] for i, k in enumerate(key_list)}
    n_mesh = len(key_list)

    hit, ranks_hit = 0, []
    for g in geo:
        k = (str(g["lat_i"]), str(g["lon_i"]))
        if k in rank_of:
            hit += 1
            ranks_hit.append(rank_of[k] / n_mesh)     # 0=最上位, 1=最下位

    ranks_hit = np.array(ranks_hit)
    print(f"\n新規開店 {len(geo)} 件中、メッシュに載った {hit} 件")
    print(f"\n■ 新店が落ちたメッシュの、モデル評価での位置（0=最有力・1=最下位）")
    print(f"   中央値 {np.median(ranks_hit):.3f}   平均 {ranks_hit.mean():.3f}")
    print(f"   （でたらめなら 0.5 になる）")

    print("\n■ モデルの上位何%に入っていたか")
    for q in (0.01, 0.05, 0.10, 0.20, 0.50):
        c = (ranks_hit <= q).sum()
        print(f"   上位 {q:>4.0%}  {c:>3}/{len(ranks_hit)} 件 = {c/len(ranks_hit):>5.1%}"
              f"   （でたらめなら {q:.0%}）  倍率 {c/len(ranks_hit)/q:>4.1f}x")

    with (DATA / "openings_geo.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(geo[0].keys()))
        w.writeheader()
        w.writerows(geo)
    plot(ranks_hit)


def plot(ranks_hit) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for cand in ("Hiragino Sans", "Hiragino Maru Gothic ProN", "YuGothic", "AppleGothic"):
        if any(cand in f.name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = cand
            break

    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=160)
    fig.patch.set_facecolor("#E9E7DF")
    ax.set_facecolor("#F2F0E9")
    ax.hist(ranks_hit, bins=20, range=(0, 1), color="#1F5C55", alpha=.85)
    ax.axhline(len(ranks_hit) / 20, color="#8A3B2E", lw=1.4, ls="--",
               label="でたらめに開いた場合")
    ax.set_xlabel("モデル評価での位置（0＝最有力メッシュ / 1＝最下位）")
    ax.set_ylabel("新規開店の件数")
    ax.set_title("実際に開いた95店は、モデルが有力と見た場所に落ちたか", pad=12)
    ax.grid(True, color="#C9C6B8", lw=.5, alpha=.7)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(OUT / "openings.png", facecolor=fig.get_facecolor())
    print(f"-> {OUT/'openings.png'}")


if __name__ == "__main__":
    main()
