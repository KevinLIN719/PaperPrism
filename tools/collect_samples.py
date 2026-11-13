# -*- coding: utf-8 -*-
"""从 audit.json 里挑典型失败样本，按失败模式分目录写出「原文 / 期望 / 实际」。

输出到 失败样本/<模式>/<篇名>.md。不打包 PDF（任务书 3.1 的约束）。
"""

import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vendor", "pymupdf_pkg"))

OUTDIR = os.path.join(ROOT, "out", "失败样本")

# 失败模式 → (目录名, 期望行为)
MODES = {
    "0-内容大面积丢失": ("F1_内容大面积丢失", "正文应按原文顺序完整保留；参考文献之后的正文/附录不应被连带吞掉"),
    "0-无文本层": ("F2_扫描件无文本层", "parse_pdf 应正常返回 0 段并给出可区分的原因标记，而不是静默空白"),
    "6-heading漏识别": ("F3_标题漏识别", "顶层编号标题（1. Introduction）与结构标题应进 heading"),
    "2-段尾截断": ("F4_段落被切断", "被图表/换栏/换页打断的同一自然段应拼回一段"),
    "2-段首小写": ("F4_段落被切断", "以小写开头说明上一段没接上，应与上一段合并"),
    "5-脚注并入正文": ("F5_脚注并入正文", "页底小字脚注不应并进正文段落"),
    "1-标题": ("F6_标题识别失败", "kind=='title' 恰好 1 条，内容是论文大标题"),
    "1-作者名单进正文": ("F6_标题识别失败", "首页作者名单应被 drop_metadata 清掉，不进 body"),
    "4-参考文献漏成正文": ("F7_参考文献漏成正文", "参考文献条目不应出现在 body"),
    "4-附录丢失": ("F8_附录丢失", "参考文献之后的附录应恢复收录"),
    "3-caption漏判": ("F9_图注判定", "带「Figure N.」标签的块应判 caption，正文句不应判 caption"),
    "3-正文被判图注": ("F9_图注判定", "「Table N shows…」这类正文句不应判成 caption"),
    "7-耗时": ("F10_解析耗时", "单篇解析应在 10 秒内完成"),
}


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "out", "audit_A_v6.json")
    data = json.load(io.open(src, encoding="utf-8"))
    buckets = {}
    for r in data:
        for f in r.get("findings", []):
            if f["check"] not in MODES:
                continue
            d, expect = MODES[f["check"]]
            buckets.setdefault(d, {"expect": expect, "items": []})
            buckets[d]["items"].append((r["file"], f))

    if os.path.isdir(OUTDIR):
        # 旧样本不删（可能已被引用），直接覆盖同名文件；本轮没有的模式会留下旧文件，
        # 以 README.md 的索引为准。
        pass
    os.makedirs(OUTDIR, exist_ok=True)

    index = ["# 失败样本索引\n",
             "每个模式挑 1-2 篇最典型的，给「原文片段 / 期望 / 实际」。",
             "原始数据见 `out/audit.json`；按任务书 3.1 不回传 PDF 本身。\n"]
    for d in sorted(buckets):
        info = buckets[d]
        os.makedirs(os.path.join(OUTDIR, d), exist_ok=True)
        # 每个模式挑「n 最大的」前 2 篇
        picks = sorted(info["items"], key=lambda it: -it[1]["n"])[:2]
        index.append("## %s（%d 篇命中）" % (d, len({x[0] for x in info["items"]})))
        index.append("- 期望：%s" % info["expect"])
        for fname, f in picks:
            lines = ["# %s" % d, "",
                     "- 样本文件：`%s`" % fname,
                     "- 检查项：`%s`（命中 %d 处）" % (f["check"], f["n"]),
                     "- 说明：%s" % (f.get("note") or "-"),
                     "- **期望**：%s" % info["expect"], "",
                     "## 实际输出（解析器当前结果）", ""]
            if f["evidence"]:
                for e in f["evidence"]:
                    lines.append("### 第 %s 页" % e["page"])
                    lines.append("```")
                    lines.append(e["text"])
                    lines.append("```")
                    lines.append("")
            else:
                lines.append("（该模式是整篇级结论，证据见 `out/audit.json` 对应条目的 `note` 字段）")
                lines.append("")
            out = os.path.join(OUTDIR, d, re.sub(r"\.pdf$", "", fname) + ".md")
            io.open(out, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
            index.append("  - `%s/%s`" % (d, os.path.basename(out)))
        index.append("")
    io.open(os.path.join(OUTDIR, "README.md"), "w", encoding="utf-8", newline="\n").write("\n".join(index))
    print("已写出失败样本到", OUTDIR)


if __name__ == "__main__":
    main()
