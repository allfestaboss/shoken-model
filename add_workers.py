#!/usr/bin/env python3
"""メッシュに従業者数（＝昼間の需要）を足す。

このモデルには「そこに住んでいる人」しか入っていない。だがコンビニは
オフィス街のように**住人がいなくても人が集まる場所**に建つ。
昼夜間人口比は市町村単位の値しか無く、市の中では定数になるのでメッシュでは無効だった。
従業者数はメッシュ単位で存在する。これが最後の大きな穴。

出所: e-Stat 統計GIS「経済センサス-活動調査に関する地域メッシュ統計」500mメッシュ。
      統計表 T000918（平成28年）。事業所数20列＋従業者数20列（産業大分類別）。
      https://www.e-stat.go.jp/gis/statmap-search/data?statsId=T000918&code=<1次メッシュ>&downloadType=2

列の並びに注意。事業所数が19業種（001-019）、続いて従業者数が19業種（020-038）、
最後に男女別の従業者数（039,040）。「20列ずつ」ではないので、素直に数えると1つずれる。

  T000918001 = 全産業 事業所数     T000918020 = 全産業 従業者数
  T000918010 = 卸売・小売 事業所数  T000918029 = 卸売・小売 従業者数
  T000918014 = 宿泊・飲食 事業所数  T000918033 = 宿泊・飲食 従業者数

注意: 平成28年（2016年）時点。人口は2020年なので**年次がずれている**。
オフィス街かどうかという構造は数年では動かないので特徴量としては使えるが、
「2016年の値だ」と分かった上で使うこと。

  python3 add_workers.py   ->  data/mesh.csv に workers / work_retail / work_food / estab を追加
"""
import csv
import io
import time
import urllib.request
import zipfile
from pathlib import Path

from build_mesh import mesh_id_to_index
from region import primary_meshes

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DEST = DATA / "estat"
URL = "https://www.e-stat.go.jp/gis/statmap-search/data?statsId=T000918&code={}&downloadType=2"
# 対象範囲をおおう1次メッシュ。data/mesh.csv から作るので県を足せば自動で増える
PRIMARY = primary_meshes()
COLS = {"estab": "T000918001", "workers": "T000918020",
        "work_retail": "T000918029", "work_food": "T000918033"}
UA = "shoken-model/0.4 (research; boss@allfesta.com)"


def fetch() -> dict:
    DEST.mkdir(parents=True, exist_ok=True)
    out = {}
    for code in PRIMARY:
        path = DEST / f"tblT000918H{code}.txt"
        if not path.exists():
            try:
                req = urllib.request.Request(URL.format(code), headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=120) as r:
                    body = r.read()
                with zipfile.ZipFile(io.BytesIO(body)) as z:
                    name = z.namelist()[0]
                    path.write_bytes(z.read(name))
                print(f"取得 {path.name}  {path.stat().st_size/1024:.0f}KB")
            except Exception as e:  # noqa: BLE001
                print(f"取れず {code}: {type(e).__name__}")
                continue
            time.sleep(1.5)

        # 文字コードは自治体・年次で混在する（cp932 と UTF-8 の両方が来る）。
        # 決め打ちすると1タイルで落ちて全国が止まる
        raw = path.read_bytes()
        for enc in ("cp932", "utf-8-sig", "utf-8"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            print(f"  読めず {path.name}")
            continue
        with io.StringIO(text) as f:
            rd = csv.DictReader(f)
            next(rd)                       # 2行目は日本語の見出し行なので飛ばす
            for row in rd:
                key = (row.get("KEY_CODE") or "").strip()
                if len(key) != 9:
                    continue
                idx = mesh_id_to_index(key)
                v = {}
                for name, col in COLS.items():
                    s = (row.get(col) or "").strip()
                    v[name] = int(s) if s.lstrip("-").isdigit() and not s.startswith("-") else 0
                out[idx] = v
    return out


def main() -> None:
    src = fetch()
    print(f"従業者数が取れたメッシュ {len(src):,}")

    rows = list(csv.DictReader((DATA / "mesh.csv").open(encoding="utf-8")))
    grid = {(int(r["lat_i"]), int(r["lon_i"])): src.get((int(r["lat_i"]), int(r["lon_i"])), {})
            for r in rows}

    def around(idx, key):
        la, lo = idx
        return sum(grid.get((la + i, lo + j), {}).get(key, 0)
                   for i in (-1, 0, 1) for j in (-1, 0, 1))

    hit = 0
    for r in rows:
        idx = (int(r["lat_i"]), int(r["lon_i"]))
        v = grid.get(idx, {})
        hit += 1 if v else 0
        for name in COLS:
            r[name] = v.get(name, 0)
            r[f"{name}_r1"] = around(idx, name)
        pop = float(r["pop2020"]) or 1
        r["work_pop_ratio"] = round(v.get("workers", 0) / pop, 3)

    with (DATA / "mesh.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    tot = sum(int(r["workers"]) for r in rows)
    print(f"-> data/mesh.csv （{hit:,}/{len(rows):,}メッシュに値が付いた）")
    print(f"   従業者総数 {tot:,}人 / 事業所総数 {sum(int(r['estab']) for r in rows):,}")
    top = sorted(rows, key=lambda r: -int(r["workers"]))[:5]
    print(f"\n   従業者の多いメッシュ")
    for r in top:
        print(f"     {r['city']:<10}従業者 {int(r['workers']):>7,}  居住 {float(r['pop2020']):>7,.0f}人"
              f"  昼/夜 {float(r['work_pop_ratio']):>6.1f}")


if __name__ == "__main__":
    main()
