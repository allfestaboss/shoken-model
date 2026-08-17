#!/usr/bin/env python3
"""福岡県の全市区町村（60）の人口を統計ダッシュボードAPIから取る。

統計ダッシュボード(dashboard.e-stat.go.jp)は**APIキー不要**で、国勢調査／人口推計の
時系列を市区町村単位で返す。e-Stat 本体のAPIはアプリケーションIDが要るので、
まずキー不要のこちらで組む。

  python3 fetch_population.py   ->  data/population.csv
"""
import csv
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://dashboard.e-stat.go.jp/api/1.0/Json/"
import sys
# 県コードは引数で差し替えられる（40=福岡 41=佐賀 42=長崎）。
# 複数指定すると1つのファイルにまとめて書く
# 引数に all を渡すと47都道府県。シェルによっては "01 02 …" が1語のまま渡るので
# （zshは$変数を単語分割しない）、全国は引数を並べずに all で指定する
_args = sys.argv[1:] or ["40"]
if _args == ["all"]:
    from prefs import PREFS as _P
    _args = [c for c, _, _ in _P]
PREFS = [f"{c}000" for c in _args]
POP = "0201010000000010000"   # 総人口（国勢調査／人口推計）
OUT = Path(__file__).resolve().parent / "data"


def get(endpoint: str, need: str = None, **params) -> dict:
    """need を渡すと、200で返っても中身にその鍵が無ければ失敗とみなして再試行する。

    47県ぶんを連続で叩くと、正常なJSONの形をしていない応答がたまに返る
    （例外にならないので素通りし、KeyError で落ちる）。ここで吸収する。
    """
    url = BASE + endpoint + "?" + urllib.parse.urlencode({"Lang": "JP", **params})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                d = json.load(r)
            if need is None or need in next(iter(d.values()), {}):
                return d
            raise ValueError(f"{need} が無い応答")
        except Exception as e:  # noqa: BLE001 - リトライして続ける
            if attempt == 4:
                raise
            print(f"    retry {attempt+1} ({params}): {e}")
            time.sleep(3 + attempt * 3)
    return {}


def municipalities() -> list:
    """市（政令市含む）と、郡の下の町村を集める。県を複数指定したらまとめて返す。"""
    out = []
    for i, pref in enumerate(PREFS, 1):
        got = _one_pref(pref)
        out += got
        print(f"  {pref[:2]}: {len(got)} 市町村（累計 {len(out)}）")
        time.sleep(.5)
    return out


def _one_pref(pref: str) -> list:
    """県の下を降りて市区町村を集める。

    階層は県によって深さが違う。実際に返ってくる level は:
      5 振興局（北海道）/ 6 郡 / 7 特別区部（東京）… 入れ物なので降りる
      8 政令市 / 9 市 / 10 特別区 / 12 町 / 13 村   … これが市区町村
    北海道は 県->振興局->郡->町村 と3段あり、東京23区は 県->特別区部->区。
    「郡だけ展開する」と書くと**北海道の町村144件と東京23区が丸ごと抜ける**
    （県の人口と積み上げを突き合わせて気づいた。東京で997万人・北海道で84万人）。

    **拾う側を列挙しない**のが肝。levelの番号は連番でも網羅的でもないので
    （町が12で村が13、市が9で政令市が8）、列挙すると今度は別の型が抜ける。
    入れ物だけを列挙して、それ以外は全部拾う。
    """
    CONTAINER = {"5", "6", "7"}
    out, queue, seen = [], [pref], set()
    while queue:
        code = queue.pop(0)
        if code in seen:
            continue
        seen.add(code)
        d = get("getRegionInfo", need="METADATA_INF", ParentRegionCode=code)
        for c in d["GET_META_REGION_INF"]["METADATA_INF"]["CLASS_INF"]["CLASS_OBJ"][0]["CLASS"]:
            if c["@toDate"] != "999912":
                continue                      # 合併で消えた旧市町村
            lv = c["@level"]
            if lv in CONTAINER:
                queue.append(c["@regionCode"])
            else:
                out.append((c["@regionCode"], c["@name"],
                            {"8": "市", "9": "市", "10": "区",
                             "12": "町", "13": "村"}.get(lv, "他")))
        time.sleep(.3)
    return out


def population(codes: list) -> dict:
    """コード -> {年: 人口}。20件ずつまとめて取る。"""
    series = {}
    for i in range(0, len(codes), 20):
        chunk = codes[i:i + 20]
        d = get("getData", IndicatorCode=POP, RegionCode=",".join(chunk), Cycle="3")
        objs = d["GET_STATS"]["STATISTICAL_DATA"]["DATA_INF"]["DATA_OBJ"]
        for o in objs:
            v = o["VALUE"]
            year = int(v["@time"][:4])
            series.setdefault(v["@regionCode"], {})[year] = int(v["$"])
        print(f"  {i+len(chunk)}/{len(codes)} 件")
        time.sleep(.4)
    return series


def main() -> None:
    OUT.mkdir(exist_ok=True)
    muni = municipalities()
    print(f"市区町村: {len(muni)}（市 {sum(1 for m in muni if m[2]=='市')} / "
          f"町村 {sum(1 for m in muni if m[2]=='町村')}）")

    series = population([m[0] for m in muni])

    rows = []
    for code, name, kind in muni:
        s = series.get(code, {})
        if not s:
            print(f"  !! 人口が取れない: {code} {name}")
            continue
        latest = max(s)
        rows.append({
            "code": code, "name": name, "kind": kind,
            "pop_year": latest, "pop": s[latest],
            "pop_2015": s.get(2015, ""), "pop_2000": s.get(2000, ""),
        })

    path = OUT / "population.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    total = sum(r["pop"] for r in rows)
    print(f"-> {path}  {len(rows)}件  合計 {total:,}人（{rows[0]['pop_year']}年）")


if __name__ == "__main__":
    main()
