#!/usr/bin/env python3
"""用途地域をメッシュに載せる。業種ごとに違う唯一の「制度」の情報。

人口・従業者・道路・駅・土地利用は、どの業種にも同じ向きに効く。だから
「このマスに何が出るか」が当てられなかった。用途地域は違う。
商業地域・工業地域・第一種低層住居専用地域で、**建てられる業種が法で決まる**。
業種ごとに違う情報の筆頭で、しかも無料で県別に取れる。

出所: 国土数値情報 A29 用途地域
  https://nlftp.mlit.go.jp/ksj/gml/data/A29/A29-19/A29-19_<県>_GML.zip
属性: A29_004 区分コード / A29_005 区分名 / A29_006 建蔽率 / A29_007 容積率

ポリゴンをメッシュに落とすとき、中心1点だけで判定すると境界のマスを取りこぼす。
1マスにつき3x3の9点を打って**面積の割合**にする。用途地域は都市計画区域にしか
無いので、指定が無いマスは全部0（指定ありかどうかの列も持たせる）。

  .venv-duck/bin/python add_zoning.py          # 未取得の県をダウンロードして載せる
  .venv-duck/bin/python add_zoning.py 40 23    # 県を指定
"""
import csv
import json
import sys
import time
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np

from prefs import PREFS

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DEST = DATA / "mlit" / "a29"
URL = "https://nlftp.mlit.go.jp/ksj/gml/data/A29/A29-19/A29-19_{}_GML.zip"
UA = {"User-Agent": "shoken-model/0.5 (research; boss@allfesta.com)"}
SUB = 3                       # 1マスにつき SUB x SUB 点を打つ

# 用途地域13種を、業種の立地に関係する7つにまとめる
GROUP = {
    1: "z_low", 2: "z_low",                       # 低層住居専用（店をほぼ建てられない）
    3: "z_mid", 4: "z_mid",                       # 中高層住居専用
    5: "z_res", 6: "z_res", 7: "z_res", 13: "z_res",   # 住居・準住居・田園住居
    8: "z_ncom",                                  # 近隣商業
    9: "z_com",                                   # 商業
    10: "z_qind",                                 # 準工業
    11: "z_ind", 12: "z_ind",                     # 工業・工業専用
}
COLS = ["z_low", "z_mid", "z_res", "z_ncom", "z_com", "z_qind", "z_ind"]


def fetch(pref: str) -> Path:
    DEST.mkdir(parents=True, exist_ok=True)
    path = DEST / f"{pref}.zip"
    if not path.exists():
        with urllib.request.urlopen(
                urllib.request.Request(URL.format(pref), headers=UA), timeout=300) as r:
            path.write_bytes(r.read())
        time.sleep(1.0)
    return path


def polygons(pref: str):
    """(区分コード, 容積率, 外周のnumpy配列) を返す。"""
    z = zipfile.ZipFile(fetch(pref))
    for info in z.infolist():
        try:
            name = info.filename.encode("cp437").decode("cp932")
        except Exception:  # noqa: BLE001
            name = info.filename
        if not name.lower().endswith(".geojson"):
            continue
        for f in json.loads(z.read(info).decode("utf-8"))["features"]:
            p = f["properties"]
            try:
                code = int(p.get("A29_004") or 0)
            except (TypeError, ValueError):
                continue
            if code not in GROUP:
                continue
            try:
                far = float(p.get("A29_007") or 0)
            except (TypeError, ValueError):
                far = 0.0
            g = f["geometry"]
            rings = ([g["coordinates"]] if g["type"] == "Polygon"
                     else g["coordinates"])
            for r in rings:
                if r and r[0]:
                    yield code, far, np.asarray(r[0], dtype=float)


def inside(pts, poly):
    """交差数による内外判定。pts は (N,2)、poly は (M,2)。"""
    x, y = pts[:, 0], pts[:, 1]
    x1, y1 = poly[:-1, 0], poly[:-1, 1]
    x2, y2 = poly[1:, 0], poly[1:, 1]
    cross = np.zeros(len(pts), dtype=bool)
    for a, b, c, d in zip(x1, y1, x2, y2):
        if b == d:
            continue
        hit = ((b > y) != (d > y)) & (x < (c - a) * (y - b) / (d - b) + a)
        cross ^= hit
    return cross


def main() -> None:
    prefs = sys.argv[1:] or [c for c, _, _ in PREFS]
    hits = defaultdict(lambda: defaultdict(float))
    far_sum = defaultdict(float)
    far_cnt = defaultdict(float)

    for pi, pref in enumerate(prefs, 1):
        n_poly = 0
        try:
            polys = list(polygons(pref))
        except Exception as e:  # noqa: BLE001
            print(f"  {pref}: 取れず {type(e).__name__}")
            continue
        for code, far, ring in polys:
            n_poly += 1
            lo_x, hi_x = ring[:, 0].min(), ring[:, 0].max()
            lo_y, hi_y = ring[:, 1].min(), ring[:, 1].max()
            # メッシュの行・列の範囲。1マスを SUB x SUB に割った点を打つ
            la0, la1 = int(np.floor(lo_y * 240)), int(np.floor(hi_y * 240))
            lo0, lo1 = int(np.floor((lo_x - 100) * 160)), int(np.floor((hi_x - 100) * 160))
            if (la1 - la0 + 1) * (lo1 - lo0 + 1) > 40000:
                continue                      # 異常に大きいポリゴンは飛ばす（無いはず）
            las = np.arange(la0, la1 + 1)
            los = np.arange(lo0, lo1 + 1)
            off = (np.arange(SUB) + 0.5) / SUB
            ys = ((las[:, None] + off[None, :]) / 240).ravel()
            xs = (100 + (los[:, None] + off[None, :]) / 160).ravel()
            gx, gy = np.meshgrid(xs, ys)
            pts = np.column_stack([gx.ravel(), gy.ravel()])
            ok = inside(pts, ring)
            if not ok.any():
                continue
            ry = np.repeat(las, SUB)
            rx = np.repeat(los, SUB)
            iy, ix = np.divmod(np.where(ok)[0], len(xs))
            col = GROUP[code]
            for a, b in zip(ry[iy], rx[ix]):
                hits[(a, b)][col] += 1.0
                if far > 0:
                    far_sum[(a, b)] += far
                    far_cnt[(a, b)] += 1.0
        print(f"  [{pi}/{len(prefs)}] {pref}: ポリゴン {n_poly:,} / "
              f"指定のあるマス 累計 {len(hits):,}")

    rows = list(csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8")))
    n_sub = SUB * SUB
    for r in rows:
        k = (int(r["lat_i"]), int(r["lon_i"]))
        h = hits.get(k, {})
        for c in COLS:
            r[c] = round(min(h.get(c, 0.0) / n_sub, 1.0), 3)
        r["z_any"] = 1 if h else 0
        r["z_far"] = round(far_sum.get(k, 0.0) / far_cnt[k], 0) if far_cnt.get(k) else ""

    with (DATA / "mesh.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    n_any = sum(1 for r in rows if int(r["z_any"]))
    print(f"\n-> data/mesh.csv  用途地域の指定があるマス {n_any:,}/{len(rows):,}")
    print(f"{'区分':<10}{'面積割合の合計':>14}{'1マスでも入るマス数':>20}")
    for c in COLS:
        s = sum(float(r[c]) for r in rows)
        m = sum(1 for r in rows if float(r[c]) > 0)
        print(f"{c:<10}{s:>14,.0f}{m:>20,}")
    far = [float(r["z_far"]) for r in rows if r["z_far"] != ""]
    if far:
        far.sort()
        print(f"容積率  中央値 {far[len(far)//2]:.0f}%  上位10% {far[-len(far)//10]:.0f}%")


if __name__ == "__main__":
    main()
