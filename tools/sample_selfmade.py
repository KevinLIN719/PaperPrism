"""抽 30 条「本文自创术语」标注，给人（或另一个 Agent）做正确率抽查。

背景：brief 的「三条最小证据」第 ③ 条要求抽查 30 条自创术语标记的正确率。
这些标记是批注阶段模型自己打的（llm.py 里 `selfmade` 字段），从来没人工验证过。

抽样规则（固定、可复现）：
  1. 扫 store/*.json，收集所有 annots[*].selfmade == True 的批注；
  2. 按论文分组，每篇按段落序号升序；
  3. 各篇名额按「该篇自创数 / 总数 × 30」四舍五入，最少 2 条、最多 15 条；
  4. 篇内等距抽取（第 1 条、最后 1 条必取，中间均匀分布），保证可复现；
  5. 输出 out/自创术语抽查_样本.csv（UTF-8 BOM，Excel 直接开）+ .json（给脚本用）。

用法：
    python tools/sample_selfmade.py            # 生成样本（会覆盖同名文件）
    python tools/sample_selfmade.py --n 40     # 改样本量
"""
import argparse
import csv
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_CSV = os.path.join(ROOT, "out", "自创术语抽查_样本.csv")
OUT_JSON = os.path.join(ROOT, "out", "自创术语抽查_样本.json")


def rows_from_store():
    """把 store 里所有 selfmade 批注摊平成行。"""
    out = []
    for f in sorted(glob.glob(os.path.join(ROOT, "store", "*.json"))):
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        paras = (d.get("parse") or {}).get("paras") or []
        rel = d.get("path") or os.path.basename(f)
        paper = os.path.basename(rel)
        for k, a in (d.get("annots") or {}).items():
            if not isinstance(a, dict) or not a.get("selfmade"):
                continue
            try:
                i = int(k)
            except (TypeError, ValueError):
                continue
            p = paras[i] if 0 <= i < len(paras) else {}
            text = (p.get("text") or "").strip()
            out.append({
                "paper": paper,
                "store": os.path.basename(f),
                "idx": i,
                "page": p.get("page"),
                "terms": "; ".join((t.get("t") or "") + ("（" + t["zh"] + "）" if t.get("zh") else "")
                                   for t in (a.get("terms") or []) if isinstance(t, dict)),
                "one_line": a.get("one_line") or "",
                "note": a.get("note") or "",
                "anchor": (a.get("anchor") or {}).get("head") or "",
                "para_text": text[:700],
            })
    return out


def quota(per_paper, total, n):
    """按比例分配名额：最少 2、最多 15、合计不超过 n。"""
    q = {}
    for paper, items in per_paper.items():
        want = max(2, min(15, int(round(len(items) * n / max(1, total)))))
        q[paper] = min(want, len(items))
    # 总量修正：多了从最大的篇减，少了补给最大的篇
    while sum(q.values()) > n:
        k = max(q, key=lambda x: q[x])
        q[k] -= 1
    while sum(q.values()) < n:
        k = max((p for p in per_paper if q[p] < len(per_paper[p])),
                key=lambda x: len(per_paper[x]), default=None)
        if not k:
            break
        q[k] += 1
    return q


def pick_even(items, k):
    """等距抽 k 条（首尾必取）。"""
    m = len(items)
    if k >= m:
        return list(items)
    if k == 1:
        return [items[0]]
    pos = sorted({int(round(i * (m - 1) / (k - 1))) for i in range(k)})
    return [items[p] for p in pos]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30, help="抽样条数（默认 30，brief 要求的数字）")
    args = ap.parse_args()

    rows = rows_from_store()
    if not rows:
        raise SystemExit("store/ 里没有 selfmade 标注，先跑几篇论文的批注再来抽。")

    per_paper = {}
    for r in rows:
        per_paper.setdefault(r["paper"], []).append(r)
    for v in per_paper.values():
        v.sort(key=lambda r: r["idx"])

    q = quota(per_paper, len(rows), args.n)
    sample = []
    for paper in sorted(per_paper):
        sample.extend(pick_even(per_paper[paper], q[paper]))
    sample.sort(key=lambda r: (r["paper"], r["idx"]))

    os.makedirs(os.path.join(ROOT, "out"), exist_ok=True)
    cols = ["paper", "idx", "page", "terms", "one_line", "note", "anchor", "para_text",
            "判定", "依据", "若为既有需给出处", "置信度", "备注"]
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in sample:
            w.writerow({c: r.get(c, "") for c in cols})
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(sample, fh, ensure_ascii=False, indent=2)

    print("样本池：%d 条自创标记，来自 %d 篇" % (len(rows), len(per_paper)))
    for paper in sorted(per_paper):
        print("  %-42s 池 %3d → 抽 %2d" % (paper, len(per_paper[paper]), q[paper]))
    print("合计抽取 %d 条 → %s" % (len(sample), OUT_CSV))


if __name__ == "__main__":
    main()
