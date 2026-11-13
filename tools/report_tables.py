# -*- coding: utf-8 -*-
"""从 out/audit.json 生成「识别报告」里的逐篇明细表 + 统计段落。

报告里的所有数字都必须由本脚本生成，避免手写出错。
输出到 out/_report_tables.md，再由人贴进 识别报告.md。
"""

import collections
import io
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CATS = [
    ("c1", "类别 1：单栏 / 双栏会议论文"),
    ("c2", "类别 2：三栏 / 期刊紧凑版式"),
    ("c3", "类别 3：首字下沉 / 期刊首页特殊排版"),
    ("c4", "类别 4：脚注特别多"),
    ("c5", "类别 5：参考文献 + 附录都很长（30 页以上）"),
    ("c6", "类别 6：一个 PDF 排两篇论文"),
    ("c7", "类别 7：扫描件 / 无文本层"),
    ("c8", "类别 8：中英混排 / 中文期刊"),
    ("c9", "类别 9：跨栏 / 跨页续写"),
]
BASE = ["resnet_1512.03385.pdf", "science.1133687.pdf", "attention_1706.03762.pdf",
        "bert_1810.04805.pdf", "ScalingOnlineExploration_2610.22496.pdf"]
BASE_SPEC = {   # 任务书第 5 节给的基线
    "resnet_1512.03385.pdf": (12, 87, "1/10/61/15", 28341),
    "science.1133687.pdf": (5, 17, "1/0/12/4", 12642),
    "attention_1706.03762.pdf": (15, 96, "1/23/66/6", 24204),
    "bert_1810.04805.pdf": (16, 116, "1/10/97/7", 33368),
    "ScalingOnlineExploration_2610.22496.pdf": (77, 287, "1/41/190/55", 136625),
}


def kstr(k):
    return "%d·%d·%d·%d" % (k.get("title", 0), k.get("heading", 0),
                            k.get("body", 0), k.get("caption", 0))


def issues_of(r):
    return "；".join(r["issues"]) if r["issues"] else "无"


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    src = os.path.join(ROOT, "out", "audit.json")
    if not os.path.isfile(src):
        src = os.path.join(ROOT, "out", "audit_A_v6.json")
    A = json.load(io.open(src, encoding="utf-8"))
    by = {r["file"]: r for r in A}
    L = []

    for pre, title in CATS:
        files = sorted(f for f in by if f.startswith(pre + "_"))
        if not files:
            continue
        L.append("### %s（%d 篇）\n" % (title, len(files)))
        if pre == "c7":
            L.append("| 文件 | 页 | 段 | 文本层字符 | 返回 | 抛异常？ | 秒 |")
            L.append("|---|---|---|---|---|---|---|")
            for f in files:
                r = by[f]
                L.append("| %s | %d | %d | %d | `[]` | 否 | %.1f |" % (
                    f[:-4], r["pages"], r["paras"], r["raw_chars"], r["secs"]))
        else:
            L.append("| 文件 | 页 | 段 | t·h·b·c | 正文字符 | 留存 | 可用率 | 秒 | 问题 |")
            L.append("|---|---|---|---|---|---|---|---|---|")
            for f in files:
                r = by[f]
                L.append("| %s | %d | %d | %s | %d | %.0f%% | %.3f | %.1f | %s |" % (
                    f[:-4], r["pages"], r["paras"], kstr(r["kinds"]), r["body_chars"],
                    r["keep_rate"] * 100, r["usable_ratio"], r["secs"], issues_of(r)))
        L.append("")

    L.append("### 基线 5 篇（与任务书第 5 节逐项对齐）\n")
    L.append("| 文件 | 页 | 段 | t/h/b/c | 正文字符 | 任务书基线（页/段/分布/字符） | 一致 | 留存 | 可用率 | 秒 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for f in BASE:
        r = by[f]
        k = r["kinds"]
        got = "%d/%d/%d/%d" % (k.get("title", 0), k.get("heading", 0), k.get("body", 0), k.get("caption", 0))
        sp = BASE_SPEC[f]
        ok = (r["pages"] == sp[0] and r["paras"] == sp[1] and got == sp[2] and r["body_chars"] == sp[3])
        L.append("| %s | %d | %d | %s | %d | %d / %d / %s / %d | %s | %.0f%% | %.3f | %.1f |" % (
            f[:-4], r["pages"], r["paras"], got, r["body_chars"],
            sp[0], sp[1], sp[2], sp[3], "是" if ok else "**否**",
            r["keep_rate"] * 100, r["usable_ratio"], r["secs"]))
    L.append("")

    # ---- 统计 ----
    cnt = collections.Counter()
    pap = collections.defaultdict(set)
    for r in A:
        for fd in r.get("findings", []):
            cnt[fd["check"]] += fd["n"]
            pap[fd["check"]].add(r["file"])
    L.append("### 检查项命中统计（全 %d 篇）\n" % len(A))
    L.append("| 检查项 | 命中次数 | 涉及篇数 |")
    L.append("|---|---|---|")
    for k, v in cnt.most_common():
        L.append("| %s | %d | %d |" % (k, v, len(pap[k])))
    L.append("")

    txt = [r for r in A if r["has_text_layer"]]
    tiers = collections.Counter()
    for r in txt:
        u = r["usable_ratio"]
        tiers["≥0.95" if u >= 0.95 else "0.90-0.95" if u >= 0.90 else
              "0.80-0.90" if u >= 0.80 else "<0.80"] += 1
    lost = [r for r in txt if r["keep_rate"] < 0.35]
    joint = [r for r in txt if r["keep_rate"] >= 0.35 and r["usable_ratio"] >= 0.90]
    secs = sorted(r["secs"] for r in A)
    L.append("### 总量\n")
    L.append("- 总篇数 %d；有文本层 %d；扫描件 %d" % (len(A), len(txt), len(A) - len(txt)))
    L.append("- usable_ratio 中位数 %.3f，平均 %.3f" % (
        statistics.median(r["usable_ratio"] for r in txt),
        statistics.mean(r["usable_ratio"] for r in txt)))
    L.append("- keep_rate 中位数 %.3f" % statistics.median(r["keep_rate"] for r in txt))
    L.append("- 可用率分档：" + "；".join("%s %d 篇（%.0f%%）" % (k, tiers[k], 100.0 * tiers[k] / len(txt))
                                     for k in ("≥0.95", "0.90-0.95", "0.80-0.90", "<0.80")))
    L.append("- 内容大面积丢失（留存 < 35%%）：%d 篇 —— %s" % (
        len(lost), "、".join(r["file"][:-4] for r in lost)))
    L.append("- **联合标准「留存 ≥ 35%% 且可用率 ≥ 0.90」= 可以直接用：%d/%d = %.0f%%**" % (
        len(joint), len(txt), 100.0 * len(joint) / len(txt)))
    L.append("- 耗时：< 1 秒 %d 篇；1–5 秒 %d 篇；5–10 秒 %d 篇；> 10 秒 %d 篇（%s）" % (
        sum(1 for s in secs if s < 1), sum(1 for s in secs if 1 <= s < 5),
        sum(1 for s in secs if 5 <= s <= 10), sum(1 for s in secs if s > 10),
        "、".join("%s %.1fs" % (r["file"][:-4], r["secs"]) for r in sorted(A, key=lambda x: -x["secs"]) if r["secs"] > 10)))
    L.append("- title≠1 的篇数：%d —— %s" % (
        sum(1 for r in A if r["title_check"]["titles"] != 1 and r["has_text_layer"]),
        "、".join(r["file"][:-4] for r in A if r["title_check"]["titles"] != 1 and r["has_text_layer"])))
    L.append("")

    out = os.path.join(ROOT, "out", "_report_tables.md")
    io.open(out, "w", encoding="utf-8", newline="\n").write("\n".join(L))
    print("\n".join(L))
    print("\n已写入", out)


if __name__ == "__main__":
    main()
