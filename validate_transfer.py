#!/usr/bin/env python3
"""福岡だけで学習したモデルで、佐賀・長崎に実際に開いた店を当てられるか。

AUCで「移る」ことは分かったが、AUCは既にある店の分布を説明できるかを見ているだけ。
本番は**まだ1店も無いマスに、その後ほんとうに店ができたか**なので、
福岡国税局が出す酒販免許（福岡・佐賀・長崎の3県が同じ形式）で答え合わせする。

学習に佐賀・長崎のデータは1行も使わない。福岡の係数をそのまま持ち込む。

  .venv-duck/bin/python validate_transfer.py
"""
import csv
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import numpy as np
import pdfplumber

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT))
import mesh_model as M  # noqa: E402
from validate_openings_multi import CATS  # noqa: E402

PREF_JP = {"fukuoka": "福岡県", "saga": "佐賀県", "nagasaki": "長崎県",
           "aichi": "愛知県", "akita": "秋田県"}
PREF_CODE = {"fukuoka": "40", "saga": "41", "nagasaki": "42",
             "aichi": "23", "akita": "05"}
TARGETS = [("41", "佐賀"), ("42", "長崎"), ("23", "愛知"), ("05", "秋田")]
GSI = "https://msearch.gsi.go.jp/address-search/AddressSearch?q="
UA = "shoken-model/0.5 (research; boss@allfesta.com)"


def mesh_index(lat, lon):
    return math.floor(lat * 240), math.floor((lon - 100) * 160)


def parse() -> list:
    out = []
    for path in sorted((DATA / "nta").glob("*.pdf")):
        pref = path.stem.split("_")[-1]
        if pref not in PREF_JP:
            continue
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                for tbl in page.extract_tables() or []:
                    for r in tbl:
                        if len(r) < 8 or not r[3] or r[0] == "税務署名":
                            continue
                        name = re.sub(r"\s+", "", r[3])
                        cat = next((c for c, (_, pat) in CATS.items()
                                    if re.search(pat, name)), None)
                        if not cat or (r[7] or "").strip() != "新規":
                            continue
                        out.append({"pref": pref, "cat": cat, "shop": name[:60],
                                    "addr": re.sub(r"\s+", "", r[4] or "")})
    seen, uniq = set(), []
    for r in out:
        k = (r["pref"], r["shop"], r["addr"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq


def geocode(rows) -> list:
    path = DATA / "openings_3pref_geo.csv"
    cache = {}
    if path.exists():
        for r in csv.DictReader(path.open(encoding="utf-8")):
            cache[(r["pref"], r["shop"], r["addr"])] = r
    out = []
    for r in rows:
        k = (r["pref"], r["shop"], r["addr"])
        if k in cache:
            out.append(cache[k])
            continue
        # 住所は県名から書かれていないので、ファイル名の県を頭に付ける。
        # ここを福岡固定にすると佐賀の住所が福岡県内で誤ヒットする
        q = GSI + urllib.parse.quote(PREF_JP[r["pref"]] + r["addr"])
        try:
            req = urllib.request.Request(q, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                d = json.load(resp)
            if d:
                c = d[0]["geometry"]["coordinates"]
                la, lo = mesh_index(float(c[1]), float(c[0]))
                out.append({**r, "lat": c[1], "lon": c[0], "lat_i": la, "lon_i": lo})
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.0)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["pref", "cat", "shop", "addr", "lat", "lon",
                                          "lat_i", "lon_i"], extrasaction="ignore")
        w.writeheader()
        w.writerows(out)
    return out


def main() -> None:
    rows = parse()
    print("PDFから拾った新規開店:", dict(Counter(f"{r['pref']}/{r['cat']}" for r in rows)))
    geo = geocode(rows)
    print(f"座標化できた {len(geo):,}\n")

    print(f"{'業態':<14}{'予測する県':<8}{'対象の新店':>10}{'順位中央値':>10}"
          f"{'上位10%':>9}{'倍率':>8}{'先客で並べた場合':>16}")
    for cat, (target, _) in CATS.items():
        M.TARGET = target
        mesh = M.load()
        for r in mesh:
            r["pref"] = r.get("pref") or r["city"][:2]
        idx = {(r["lat_i"], r["lon_i"]): i for i, r in enumerate(mesh)}
        pref = np.array([r["pref"] for r in mesh])
        n = np.array([r["stores"] for r in mesh], dtype=float)
        X = M.features(mesh)

        for pcode, pname in TARGETS:
            opens = [(int(o["lat_i"]), int(o["lon_i"])) for o in geo
                     if o["cat"] == cat and PREF_CODE[o["pref"]] == pcode]
            if not opens:
                continue
            stock = n.copy()                       # 開店前に戻す
            for k, c in Counter(opens).items():
                if k in idx:
                    stock[idx[k]] = max(0.0, stock[idx[k]] - c)

            tr = pref == "40"                      # 学習は福岡だけ
            beta = M.fit_poisson(X[tr], stock[tr])
            lam = np.exp(np.clip(X @ beta, -30, 20))

            # その県の、まだ1店も無いマスの中だけで順位づけする
            zone = np.where((pref == pcode) & (stock == 0))[0]
            tie = np.random.default_rng(0).random(len(mesh))
            hit = [k for k in opens if k in idx and stock[idx[k]] == 0]
            res = []
            for score in (lam, stock):
                order = zone[np.lexsort((tie[zone], -score[zone]))]
                rank = {(mesh[i]["lat_i"], mesh[i]["lon_i"]): j / len(order)
                        for j, i in enumerate(order)}
                p = np.array([rank[k] for k in hit if k in rank])
                res.append(p)
            p, pb = res
            if len(p) == 0:
                continue
            print(f"{cat:<14}{pname:<8}{len(p):>10}{np.median(p):>10.3f}"
                  f"{(p <= .10).mean():>9.1%}{(p <= .10).mean()/.10:>8.1f}x"
                  f"{'（全マス0で測れず）':>16}")


if __name__ == "__main__":
    main()
