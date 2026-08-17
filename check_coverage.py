#!/usr/bin/env python3
"""OSM のコンビニ網羅率を、外部の公表値と突き合わせて測る。

残差を出す前に、まず**物差しの狂いを測る**。OSM が業態・チェーンによって
偏って欠測していると、残差は経済ではなくマッピングの粗密を測ってしまう。

チェーン別に見るのは、欠測がチェーンに紐づくか（例: 特定チェーンだけ未入力）を
検出するため。全チェーンでほぼ同じ率なら、少なくとも「チェーン依存の欠測」ではない。
**地理的な偏り（都市ほどよく描かれている等）はこれでは検出できない。** そこは
経済センサス（e-Stat、要アプリケーションID）でしか潰せない。

  python3 check_coverage.py   ->  data/coverage.csv
"""
import csv
import json
import re
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
ENDPOINT = "https://overpass-api.de/api/interpreter"

QUERY = """
[out:json][timeout:180];
area["name"="福岡県"]["admin_level"="4"]->.pref;
( node(area.pref)["shop"="convenience"]; way(area.pref)["shop"="convenience"]; );
out tags center;
"""

# 主要6チェーンの福岡県内店舗数（2026年・日本ソフト販売の都道府県別集計）
REFERENCE = {
    "セブン-イレブン": 1063,
    "ファミリーマート": 543,
    "ローソン": 534,
    "ミニストップ": 111,
    "デイリーヤマザキ": 62,
}

# 表記ゆれ: OSM には「セブンイレブン」「7-ELEVEN」「7 ELEVEN」が混在する
PATTERNS = [
    ("セブン-イレブン", r"セブン|7[\s\-]?eleven"),
    ("ファミリーマート", r"ファミリーマート|family\s?mart"),
    ("ローソン", r"ローソン|lawson"),
    ("ミニストップ", r"ミニストップ|ministop"),
    ("デイリーヤマザキ", r"デイリーヤマザキ|daily\s?yamazaki"),
]


def brand_of(tags: dict) -> str:
    s = ((tags.get("brand") or "") + " " + (tags.get("name") or "")).lower()
    for name, pat in PATTERNS:
        if re.search(pat, s):
            return name
    return "その他（独立系ほか）"


def main() -> None:
    data = urllib.parse.urlencode({"data": QUERY}).encode()
    req = urllib.request.Request(ENDPOINT, data=data,
                                 headers={"User-Agent": "shoken-model/0.1 (research)"})
    with urllib.request.urlopen(req, timeout=200) as r:
        elements = json.load(r)["elements"]

    counts = Counter(brand_of(e.get("tags", {})) for e in elements)
    rows = []
    for name, ref in REFERENCE.items():
        rows.append({"brand": name, "osm": counts.get(name, 0), "published": ref,
                     "coverage": round(counts.get(name, 0) / ref, 3)})
    rows.append({"brand": "その他（独立系ほか）", "osm": counts.get("その他（独立系ほか）", 0),
                 "published": "", "coverage": ""})

    with (DATA / "coverage.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["brand", "osm", "published", "coverage"])
        w.writeheader()
        w.writerows(rows)

    major = sum(counts.get(n, 0) for n in REFERENCE)
    print(f"{'チェーン':18}{'OSM':>6}{'公表':>7}{'網羅率':>8}")
    for r in rows[:-1]:
        print(f"{r['brand']:18}{r['osm']:>6}{r['published']:>7}{r['coverage']:>7.0%}")
    print(f"{'6チェーン計':18}{major:>6}{sum(REFERENCE.values()):>7}"
          f"{major/sum(REFERENCE.values()):>7.0%}")
    print(f"{'その他（独立系ほか）':18}{counts.get('その他（独立系ほか）', 0):>6}")
    print("\nチェーン間で網羅率がほぼ揃っていれば、欠測はチェーン依存ではない。"
          "\n地理的な偏りはこの検査では見えない ── そこは経済センサスで潰す。")


if __name__ == "__main__":
    main()
