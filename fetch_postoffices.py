#!/usr/bin/env python3
"""OSM のマッピング密度が地理的に偏っていないかを検査するための材料を集める。

コンビニ残差の「少ない」側に県南部が並び、「多い」側に福岡市周辺が並んだ。
これが経済の話なのか、それとも**OSMが福岡市周辺ほど丁寧に描かれているだけ**なのかを
切り分けたい。

そこで、位置がほぼ動かず、公式の全数データがある **郵便局** を物差しに使う。
  公式: 国土数値情報 P30（郵便局・2013年）── 全数
  OSM : amenity=post_office

市町村ごとに OSM/公式 を出せば、それが**その自治体のマッピング網羅率**になる。
これがコンビニ残差と相関していたら、残差は経済ではなくマッピングを測っている。

  python3 fetch_postoffices.py   ->  data/postoffices.csv
"""
import csv
import json
import struct
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
DBF = DATA / "mlit" / "P30-13_40" / "P30-13_40.dbf"
ENDPOINT = "https://overpass-api.de/api/interpreter"

QUERY = """
[out:json][timeout:180];
area["name"="福岡県"]["admin_level"="4"]->.pref;
area["name"="{name}"]["admin_level"="7"](area.pref)->.m;
( node(area.m)["amenity"="post_office"]; way(area.m)["amenity"="post_office"]; ); out count;
"""


def read_dbf(path: Path) -> list:
    """依存なしの最小 DBF リーダ（P30 は dBASE III 形式）。"""
    b = path.read_bytes()
    n_records, header_len, record_len = struct.unpack("<IHH", b[4:12])
    fields = []
    pos = 32
    while b[pos] != 0x0D:
        # 国土数値情報のDBFはフィールド名が Shift-JIS のものがある
        name = b[pos:pos + 11].split(b"\x00")[0].decode("cp932", "replace")
        length = b[pos + 16]
        fields.append((name, length))
        pos += 32
    rows = []
    for i in range(n_records):
        off = header_len + i * record_len + 1      # 先頭1バイトは削除フラグ
        rec, p = {}, off
        for name, length in fields:
            raw = b[p:p + length]
            try:
                rec[name] = raw.decode("cp932").strip()
            except UnicodeDecodeError:
                rec[name] = raw.decode("cp932", "replace").strip()
            p += length
        rows.append(rec)
    return rows


def overpass(query: str) -> dict:
    data = urllib.parse.urlencode({"data": query}).encode()
    for attempt in range(5):
        try:
            req = urllib.request.Request(ENDPOINT, data=data,
                                         headers={"User-Agent": "shoken-model/0.1 (research)"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if attempt == 4:
                raise
            wait = 5 * (attempt + 1)
            print(f"    retry {attempt+1} in {wait}s: {e}")
            time.sleep(wait)
    return {}


def main() -> None:
    # P30 は政令市を「区」のコードで持つ（北九州市 40101-40107 / 福岡市 40131-40137）。
    # 人口データ側は市のコード（40100 / 40130）なので、区を市にまとめる。
    # 那珂川町(40305) は2018年に市制施行して那珂川市(40231)。P30は2013年なので旧コード。
    RENAMED = {"40305": "40231"}

    def to_city(code: str) -> str:
        code = RENAMED.get(code, code)
        if code.startswith("4010") and code != "40100":
            return "40100"
        if code.startswith("4013") and code != "40130":
            return "40130"
        return code

    official = Counter()
    for rec in read_dbf(DBF):
        code = rec.get("P30_001", "")
        if code.isdigit():
            official[to_city(code)] += 1
    print(f"公式（国土数値情報P30）: {sum(official.values())}局 / {len(official)}市区町村")

    muni = list(csv.DictReader((DATA / "population.csv").open(encoding="utf-8")))
    rows = []
    for i, m in enumerate(muni, 1):
        d = overpass(QUERY.format(name=m["name"]))
        counts = [e for e in d.get("elements", []) if e.get("type") == "count"]
        osm = int(counts[0]["tags"]["total"]) if counts else 0
        off = official.get(m["code"], 0)
        rows.append({"code": m["code"], "name": m["name"], "osm_post": osm,
                     "official_post": off,
                     "map_coverage": round(osm / off, 3) if off else ""})
        print(f"  {i:2}/60 {m['name']:8} OSM {osm:>3} / 公式 {off:>3}")
        time.sleep(1.2)

    path = DATA / "postoffices.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["code", "name", "osm_post", "official_post",
                                          "map_coverage"])
        w.writeheader()
        w.writerows(rows)
    to = sum(r["osm_post"] for r in rows)
    tf = sum(r["official_post"] for r in rows)
    print(f"\n-> {path}  OSM {to} / 公式 {tf} = 全体 {to/tf:.0%}")


if __name__ == "__main__":
    main()
