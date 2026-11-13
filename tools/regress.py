# -*- coding: utf-8 -*-
"""改前 / 改后对比：把两次 parse 的段落按文本比对，列出新增、消失、变化。

用法：
    rem 先在旧代码上存一份
    python tools/regress.py --dump out/before.json papers/*.pdf
    rem 改完代码后
    python tools/regress.py --dump out/after.json papers/*.pdf
    python tools/regress.py --diff out/before.json out/after.json
"""

import argparse
import glob
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vendor", "pymupdf_pkg"))


def norm(t):
    return " ".join(t.split())[:120]


def dump(paths, out):
    import m1_parse as M
    data = {}
    for p in paths:
        paras = M.parse_pdf(p)
        kinds = {}
        for q in paras:
            kinds[q["kind"]] = kinds.get(q["kind"], 0) + 1
        data[os.path.basename(p)] = {
            "version": M.PARSE_VERSION,
            "paras": len(paras),
            "kinds": kinds,
            "body_chars": sum(len(q["text"]) for q in paras if q["kind"] == "body"),
            "all_chars": sum(len(q["text"]) for q in paras),
            "pages": sorted({q["page"] for q in paras}),
            "heads": [q["text"][:70] for q in paras if q["kind"] == "heading"],
            "levels": [q.get("level") for q in paras if q["kind"] == "heading"],
            "texts": [norm(q["text"]) for q in paras],
        }
        print("%-42s %4d 段" % (os.path.basename(p), len(paras)))
    d = os.path.dirname(os.path.abspath(out))
    if d:
        os.makedirs(d, exist_ok=True)
    io.open(out, "w", encoding="utf-8", newline="\n").write(json.dumps(data, ensure_ascii=False, indent=1))
    print("已写入", out)


def diff(a_path, b_path):
    A = json.load(io.open(a_path, encoding="utf-8"))
    B = json.load(io.open(b_path, encoding="utf-8"))
    print("%-42s %18s %18s %10s" % ("文件", "段数 前→后", "正文字符 前→后", "净变化"))
    print("-" * 94)
    for f in sorted(set(A) | set(B)):
        a, b = A.get(f), B.get(f)
        if not a or not b:
            print("%-42s %s" % (f, "仅存在于一侧"))
            continue
        d_ch = b["body_chars"] - a["body_chars"]
        pct = (100.0 * d_ch / a["body_chars"]) if a["body_chars"] else 0.0
        print("%-42s %8d→%-8d %8d→%-8d %+6.1f%%" % (
            f, a["paras"], b["paras"], a["body_chars"], b["body_chars"], pct))
    print()
    for f in sorted(set(A) & set(B)):
        a, b = A[f], B[f]
        sa, sb = set(a["texts"]), set(b["texts"])
        gone, new = sa - sb, sb - sa
        if not gone and not new and a["heads"] == b["heads"]:
            continue
        print("=" * 90)
        print(f, " 段数 %d→%d" % (a["paras"], b["paras"]))
        if a["heads"] != b["heads"]:
            hg = [h for h in a["heads"] if h not in b["heads"]]
            hn = [h for h in b["heads"] if h not in a["heads"]]
            if hn:
                print("  + 新增 heading (%d):" % len(hn))
                for h in hn[:12]:
                    print("      ", h)
            if hg:
                print("  - 消失 heading (%d):" % len(hg))
                for h in hg[:12]:
                    print("      ", h)
        if gone:
            print("  - 消失段落 %d 条，前 5 条：" % len(gone))
            for t in list(gone)[:5]:
                print("      ", t[:100])
        if new:
            print("  + 新增段落 %d 条，前 5 条：" % len(new))
            for t in list(new)[:5]:
                print("      ", t[:100])


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump")
    ap.add_argument("--diff", nargs=2)
    ap.add_argument("pdfs", nargs="*")
    args = ap.parse_args()
    if args.diff:
        diff(*args.diff)
        return
    paths = []
    for pat in args.pdfs:
        paths.extend(sorted(glob.glob(pat)) if any(c in pat for c in "*?") else [pat])
    dump(paths, args.dump)


if __name__ == "__main__":
    main()
