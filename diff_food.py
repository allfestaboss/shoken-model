#!/usr/bin/env python3
"""版と版を突き合わせて、閉店を取り出す。

Foursquare の date_closed は現実の閉店を測っていなかった（人口が減る県ほど
閉店が多いはずなのに相関が +0.44 と逆符号で、閉店年が2017-18年に山を作る）。
食品衛生申請等システムの廃業年月日も、欄ができたばかりで0.26%しか入っていない。

残る道は**版の差分**。このデータは上書き更新されるので、
前の版に居て次の版に居ない事業所＝その間に営業をやめた事業所になる。

  消えた   … 次の版に行番号が無い。廃業・許可失効・掲載同意の取り下げのいずれか
  廃業印   … 次の版に居るが廃業年月日が付いた。こちらは理由が確定している

「掲載同意の取り下げ」が混ざるのが弱点で、閉店と区別できない。だから
**消えた件数は閉店数の上限**として扱い、廃業印のほうを本命の系列にする。
両方を出して差を見れば、混入がどの程度かも見える。

  python3 diff_food.py 2026-07 2026-09     ->  data/food_closed.csv
  python3 diff_food.py                     # 最も古い版と最も新しい版
"""
import csv
import sys
from pathlib import Path

from parse_food import DINING, MOBILE, SNAP, clean, load

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def versions() -> list:
    return sorted(d for d in SNAP.glob("*") if d.is_dir())


def index(rows: list) -> dict:
    """行番号 -> レコード。行番号は事業所ごとに振られ、版をまたいで変わらない。"""
    return {r["行番号"]: r for r in rows if r.get("行番号")}


def main() -> None:
    vs = versions()
    if len(sys.argv) > 2:
        a, b = SNAP / sys.argv[1], SNAP / sys.argv[2]
    elif len(vs) >= 2:
        a, b = vs[0], vs[-1]
    else:
        print(f"版が {len(vs)} 個しかない（{[v.name for v in vs]}）。")
        print("差分には2つ以上の版が要る。fetch_food.py は毎月12日・26日に走る設定。")
        return

    print(f"{a.name} と {b.name} を突き合わせる")
    old, new = index(load(a)), index(load(b))
    print(f"  {a.name}: {len(old):,} 件 / {b.name}: {len(new):,} 件")

    gone = [r for k, r in old.items() if k not in new]
    marked = [new[k] for k in old if k in new
              and not (old[k].get("廃業年月日") or "").strip()
              and (new[k].get("廃業年月日") or "").strip()]
    added = [r for k, r in new.items() if k not in old]

    print(f"\n  消えた   {len(gone):,}（閉店数の上限。掲載同意の取り下げを含む）")
    print(f"  廃業印   {len(marked):,}（廃業年月日が付いた。理由が確定している）")
    print(f"  増えた   {len(added):,}（新規開業。初回許可年月日で年が分かる）")

    def usable(r):
        return (clean(r["営業の種類"]).startswith(DINING)
                and not any(w in clean(r["業態"]) for w in MOBILE)
                and (r["緯度"] or "").strip() and (r["経度"] or "").strip())

    out = []
    for kind, items in (("消えた", gone), ("廃業印", marked)):
        for r in items:
            if usable(r):
                out.append({"種別": kind, "自治体コード": r["自治体コード"],
                            "市区町村名": r["市区町村名"], "業態": clean(r["業態"]),
                            "緯度": r["緯度"], "経度": r["経度"],
                            "初回許可年月日": r["初回許可年月日"],
                            "廃業年月日": r.get("廃業年月日", ""),
                            "前の版": a.name, "次の版": b.name})

    path = DATA / "food_closed.csv"
    if out:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
            w.writeheader()
            w.writerows(out)
        print(f"\n-> {path}  飲食で座標のあるもの {len(out):,} 件")
    else:
        print("\n閉店として取り出せるものが無い（同じ版どうしを比べた場合はこれが正しい）")


if __name__ == "__main__":
    main()
