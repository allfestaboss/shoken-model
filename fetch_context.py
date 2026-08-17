#!/usr/bin/env python3
"""残差を説明しそうな変数を追加で取る（キー不要・統計ダッシュボードAPI）。

v0 は夜間人口しか使っておらず、残差が「昼間人口・通過需要」を拾っていた。
そこで次の2系統を足す。

  昼間人口 / 昼夜間人口比率   ── 働きに来る人・通学で来る人。工場や空港のある町が上がる
  人口集中地区(DID)人口/比率  ── 人口が1か所に集まっているか。同じ人口でも
                              散らばっている自治体は商圏が成立しにくい

指標コードは総当たりで見つけた（dashboard は指標一覧APIを公開していない）:
  0201060000000010000 昼間人口 / 0201060000000020000 昼夜間人口比率
  0201040000000010000 人口集中地区人口 / 0201040000000020000 人口集中地区人口比率

  python3 fetch_context.py   ->  data/context.csv
"""
import csv
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://dashboard.e-stat.go.jp/api/1.0/Json/"
DATA = Path(__file__).resolve().parent / "data"

INDICATORS = {
    "daytime_pop": "0201060000000010000",
    "day_night_ratio": "0201060000000020000",
    "did_pop": "0201040000000010000",
    # 分野07。産業別の内訳は無く「全産業の事業所数・従業者数」だけ。
    # コンビニ単位の事業所数は e-Stat 本体（要アプリケーションID）でしか取れない。
    "establishments": "0701010000000010000",
    "employees": "0701020000000010000",
}
# 人口集中地区(DID)が存在しない町村は「-」で返る。これは欠測ではなく 0。
# DID比率の指標(0201040000000020000)は市区町村では返らないので、こちらで割って作る。


def get(endpoint: str, **params) -> dict:
    url = BASE + endpoint + "?" + urllib.parse.urlencode({"Lang": "JP", **params})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                raise
            print(f"    retry {attempt+1}: {e}")
            time.sleep(2 + attempt * 2)
    return {}


def series(indicator: str, codes: list) -> dict:
    """コード -> {年: 値}"""
    out = {}
    for i in range(0, len(codes), 20):
        chunk = codes[i:i + 20]
        d = get("getData", IndicatorCode=indicator, RegionCode=",".join(chunk))
        sd = d["GET_STATS"].get("STATISTICAL_DATA")
        if not sd:
            continue
        for o in sd["DATA_INF"]["DATA_OBJ"]:
            v = o["VALUE"]
            raw = v["$"]
            if raw in ("-", "", "…", "***"):      # DIDが無い町村は「-」で返る（＝0扱い）
                continue
            out.setdefault(v["@regionCode"], {})[int(v["@time"][:4])] = float(raw)
        time.sleep(.4)
    return out


def main() -> None:
    muni = list(csv.DictReader((DATA / "population.csv").open(encoding="utf-8")))
    codes = [m["code"] for m in muni]
    # 統計ダッシュボードの地域一覧は取りこぼすことがある（志免町40305が返らなかった）。
    # メッシュ側に出てくる市町村コードを足して埋める。直接指定すれば値は返る
    mesh = DATA / "mesh.csv"
    if mesh.exists():
        extra = sorted({r["city"] for r in csv.DictReader(mesh.open(encoding="utf-8"))
                        if r.get("city") and r["city"] not in set(codes)})
        if extra:
            print(f"地域一覧に無いがメッシュに出てくる市町村を追加: {extra}")
            codes += extra
            muni += [{"code": c, "name": "", "pop": ""} for c in extra]

    got = {}
    for name, ind in INDICATORS.items():
        s = series(ind, codes)
        years = sorted({y for v in s.values() for y in v})
        print(f"{name:16} {len(s):2}/60 市町村  年次 {years[-3:] if years else '—'}")
        got[name] = s

    rows = []
    for m in muni:
        row = {"code": m["code"], "name": m["name"], "pop": m["pop"]}
        for name in INDICATORS:
            s = got[name].get(m["code"], {})
            if s:
                y = max(s)
                row[name] = s[y]
                row[f"{name}_year"] = y
            elif name == "did_pop":
                row[name] = 0.0            # DIDが無い＝0（欠測ではない）
                row[f"{name}_year"] = ""
            else:
                row[name] = ""
                row[f"{name}_year"] = ""
        # 補完で足した市町村は総人口を持たない（地域一覧に無かったので）。その場合は空
        row["did_share"] = (round(row["did_pop"] / float(m["pop"]), 4)
                            if row["did_pop"] != "" and str(m.get("pop") or "").strip() else "")
        rows.append(row)

    path = DATA / "context.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    full = sum(1 for r in rows if all(r[n] != "" for n in INDICATORS))
    with_did = sum(1 for r in rows if r["did_pop"])
    print(f"\n-> {path}  全指標そろい {full}/60／DIDあり {with_did}・DIDなし {60-with_did}")


if __name__ == "__main__":
    main()
