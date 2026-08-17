#!/usr/bin/env python3
"""コンビニ・ドラッグ・スーパーの3業態で、同じ前向き検証を回す。

酒販免許のPDFには、酒を扱う小売がすべて載る。コンビニだけでなく
ドラッグストアもスーパーも新規開店が拾える（12か月で 95 / 25 / 23 件）。

検証は業態ごとに独立に:
  1. その業態の新店を、店舗数から差し引く（＝開店前の状態に戻す）
  2. その状態でポアソンモデルを学習し直す（汚染ゼロ）
  3. 学習に使っていない新店が、モデル上位何%のメッシュに落ちたかを測る

  .venv-duck/bin/python validate_openings_multi.py
"""
import csv
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pdfplumber

ROOT = Path(__file__).resolve().parent
DATA, OUT = ROOT / "data", ROOT / "out"
sys.path.insert(0, str(ROOT))
import mesh_model as M  # noqa: E402

CATS = {
    "コンビニ": ("stores_fsq",
              r"セブン[－\-ー–ｰ]?イレブン|ファミリーマート|ローソン|ミニストップ|デイリーヤマザキ|ポプラ"),
    "ドラッグ・薬局": ("drug_fsq",
                r"ドラッグ|薬局|コスモス|マツモトキヨシ|サンドラッグ|スギ薬局|ツルハ|ココカラ|新生堂|大賀薬局"),
    "スーパー": ("super_fsq",
             r"スーパー|トライアル|ハローデイ|マルキョウ|サニー|ゆめタウン|イオン|マックスバリュ|ルミエール|西鉄ストア"),
}
GSI = "https://msearch.gsi.go.jp/address-search/AddressSearch?q="


def mesh_index(lat, lon):
    return math.floor(lat * 240), math.floor((lon - 100) * 160)


def to_date(s):
    m = re.search(r"令和\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日", s or "")
    return f"{2018 + int(m.group(1))}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


def parse_pdfs():
    rows = []
    for pdf_path in sorted((DATA / "nta").glob("*.pdf")):
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                for tbl in page.extract_tables() or []:
                    for r in tbl:
                        if len(r) < 8 or not r[3] or r[0] == "税務署名":
                            continue
                        name = re.sub(r"\s+", "", r[3])
                        cat = next((c for c, (_, pat) in CATS.items() if re.search(pat, name)), None)
                        if not cat or (r[7] or "").strip() != "新規":
                            continue
                        rows.append({"cat": cat, "date": to_date(r[1]), "shop": name[:60],
                                     "addr": re.sub(r"\s+", "", r[4] or "")})
    seen, uniq = set(), []
    for r in rows:
        k = (r["shop"], r["addr"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq


def geocode_all(rows):
    cache_path = DATA / "openings_all_geo.csv"
    cache = {}
    if cache_path.exists():
        for r in csv.DictReader(cache_path.open(encoding="utf-8")):
            cache[(r["shop"], r["addr"])] = r
    out = []
    for r in rows:
        k = (r["shop"], r["addr"])
        if k in cache:
            out.append(cache[k])
            continue
        url = GSI + urllib.parse.quote(f"福岡県{r['addr']}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "shoken-model/0.4 (research)"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                d = json.load(resp)
            if d:
                c = d[0]["geometry"]["coordinates"]
                la, lo = mesh_index(float(c[1]), float(c[0]))
                r = {**r, "lat": c[1], "lon": c[0], "lat_i": la, "lon_i": lo}
                out.append(r)
        except Exception:
            pass
        time.sleep(1.0)
    with cache_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["cat", "date", "shop", "addr", "lat", "lon",
                                          "lat_i", "lon_i"], extrasaction="ignore")
        w.writeheader()
        w.writerows(out)
    return out


def evaluate(cat: str, target: str, opens: list) -> dict:
    M.TARGET = target
    rows = M.load()
    sub = Counter((int(o["lat_i"]), int(o["lon_i"])) for o in opens)
    removed = 0
    for r in rows:                              # 開店前の状態に戻す
        k = (r["lat_i"], r["lon_i"])
        if k in sub:
            d = min(sub[k], r["stores"])
            r["stores"] -= d
            removed += d

    X = M.features(rows)
    n = np.array([r["stores"] for r in rows], dtype=float)
    beta = M.fit_poisson(X, n)
    lam = np.exp(np.clip(X @ beta, -30, 20))
    order = np.argsort(-lam)
    rank = np.empty(len(lam), int)
    rank[order] = np.arange(len(lam))
    pos_of = {(r["lat_i"], r["lon_i"]): rank[i] / len(rows) for i, r in enumerate(rows)}

    pos = np.array([pos_of[(int(o["lat_i"]), int(o["lon_i"]))] for o in opens
                    if (int(o["lat_i"]), int(o["lon_i"])) in pos_of])
    return {"cat": cat, "n_open": len(opens), "n_used": len(pos), "removed": removed,
            "median": float(np.median(pos)),
            "top1": float((pos <= .01).mean()), "top5": float((pos <= .05).mean()),
            "top10": float((pos <= .10).mean()), "top20": float((pos <= .20).mean()),
            "pos": pos}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    rows = parse_pdfs()
    print("PDFから拾った新規開店:", dict(Counter(r["cat"] for r in rows)))
    geo = geocode_all(rows)
    print("座標化できた:", dict(Counter(r["cat"] for r in geo)), "\n")

    results = []
    for cat, (target, _) in CATS.items():
        opens = [g for g in geo if g["cat"] == cat]
        if len(opens) < 5:
            print(f"{cat}: 件数が少なすぎるので見送り（{len(opens)}件）")
            continue
        results.append(evaluate(cat, target, opens))

    print(f"{'業態':<14}{'新店':>5}{'順位中央値':>10}{'上位1%':>9}{'上位5%':>9}"
          f"{'上位10%':>9}{'上位20%':>9}")
    for r in results:
        print(f"{r['cat']:<14}{r['n_used']:>5}{r['median']:>10.3f}"
              f"{r['top1']:>8.1%}{r['top5']:>9.1%}{r['top10']:>9.1%}{r['top20']:>9.1%}")
    print(f"{'でたらめなら':<14}{'':>5}{0.5:>10.3f}{0.01:>8.1%}{0.05:>9.1%}{0.10:>9.1%}{0.20:>9.1%}")

    print("\n倍率（でたらめとの比）")
    for r in results:
        print(f"   {r['cat']:<14}上位1% {r['top1']/.01:>5.1f}x  上位10% {r['top10']/.10:>4.1f}x"
              f"  上位20% {r['top20']/.20:>4.1f}x")

    plot(results)


def plot(results) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for cand in ("Hiragino Sans", "Hiragino Maru Gothic ProN", "YuGothic", "AppleGothic"):
        if any(cand in f.name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = cand
            break

    fig, axes = plt.subplots(1, len(results), figsize=(4.6 * len(results), 4.6), dpi=160)
    if len(results) == 1:
        axes = [axes]
    fig.patch.set_facecolor("#E9E7DF")
    for ax, r in zip(axes, results):
        ax.set_facecolor("#F2F0E9")
        ax.hist(r["pos"], bins=20, range=(0, 1), color="#1F5C55", alpha=.85)
        ax.axhline(len(r["pos"]) / 20, color="#8A3B2E", lw=1.3, ls="--")
        ax.set_title(f"{r['cat']}（{r['n_used']}店）\n中央値 {r['median']:.3f}", pad=10, fontsize=11)
        ax.set_xlabel("モデル評価での位置（0=最有力）")
        ax.grid(True, color="#C9C6B8", lw=.5, alpha=.7)
    axes[0].set_ylabel("新規開店の件数")
    fig.suptitle("実際に開いた店は、モデルが有力と見た場所に落ちたか（破線＝でたらめな場合）",
                 y=1.02, fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT / "openings_multi.png", facecolor=fig.get_facecolor(), bbox_inches="tight")
    print(f"\n-> {OUT/'openings_multi.png'}")


if __name__ == "__main__":
    main()
