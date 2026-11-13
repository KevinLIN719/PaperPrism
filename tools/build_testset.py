# -*- coding: utf-8 -*-
"""B 方案：10 篇解析批量测试 —— 抓论文、跑解析、出指标、叠框截图。"""
import collections, io, json, os, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vendor", "pymupdf_pkg"))

import m1_parse  # noqa: E402
import pymupdf   # noqa: E402

OUT = os.path.join(ROOT, "_relay", "testset")
PAPERS = os.path.join(ROOT, "papers_test")
os.makedirs(OUT, exist_ok=True)
os.makedirs(os.path.join(OUT, "overlay"), exist_ok=True)
os.makedirs(PAPERS, exist_ok=True)

TO_FETCH = [
    ("2103.14030", "swin_2103.14030.pdf", "双栏 arXiv（Swin，图多）"),      # 双栏
    ("2005.12872", "detr_2005.12872.pdf", "单栏 arXiv（DETR，公式多）"),   # 双栏
    ("2010.11929", "vit_2010.11929.pdf", "单栏 arXiv（ViT，ICLR 模板）"),  # 单栏
    ("1409.0473",  "bahdanau_1409.0473.pdf", "单栏 arXiv（2014 老模板）"),  # 单栏老式
    ("2303.08774", "gpt4_2303.08774.pdf", "单栏 arXiv（GPT-4 报告）"),    # 单栏报告
]

LOCAL = [
    (os.path.join(ROOT, "papers", "bert_1810.04805.pdf"), "bert_1810.04805.pdf", "双栏 arXiv"),
    (os.path.join(ROOT, "papers", "resnet_1512.03385.pdf"), "resnet_1512.03385.pdf", "双栏 arXiv（图多）"),
    (os.path.join(ROOT, "papers", "attention_1706.03762.pdf"), "attention_1706.03762.pdf", "单栏 arXiv"),
    (os.path.join(ROOT, "papers", "science.1133687.pdf"), "science.1133687.pdf", "Science 三栏紧凑"),
    (os.path.join(ROOT, "papers", "ScalingOnlineExploration_2610.22496.pdf"),
     "ScalingOnlineExploration_2610.22496.pdf", "77 页报告（含附录代码块）"),
]


def fetch(aid, name):
    path = os.path.join(PAPERS, name)
    if os.path.isfile(path) and os.path.getsize(path) > 50000:
        return path, "cached"
    url = "https://arxiv.org/pdf/%s" % aid
    req = urllib.request.Request(url, headers={"User-Agent": "PaperPrism-test/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    io.open(path, "wb").write(data)
    return path, "downloaded %d KB" % (len(data) // 1024)


def analyse(path, name, layout):
    t0 = time.time()
    paras = m1_parse.parse_pdf(path)
    ms = int((time.time() - t0) * 1000)
    pages = max((p["page"] for p in paras), default=0) or len(m1_parse.LAST_PAGE_SIZES)
    body = [p for p in paras if p["kind"] == "body"]
    longest = max(paras, key=lambda p: len(p["text"])) if paras else None
    lower_start = [p for p in body if p["text"][:1].islower()]
    # 跨页段：一个段落的热区分布在多页上（002 反馈：这部分不该算进 no_end）
    xpage = [p for p in paras if len({r["page"] for r in (p.get("rects") or [])}) > 1]
    xpage_keys = {id(p) for p in xpage}
    no_end = [p for p in body
              if id(p) not in xpage_keys and p["text"].rstrip()[-1:] not in ".?!:”’—"]
    rects = sum(len(p.get("rects") or []) for p in paras)
    texts = [p["text"] for p in body]
    dup = sum(1 for i in range(1, len(texts)) if texts[i] == texts[i - 1])
    bad_chars = sum(p["text"].count("\ufffd") for p in paras)
    nospace = 0
    for p in paras:
        for w in p["text"].split():
            if len(w) >= 25 and w.isalpha():
                nospace += 1
    lay = getattr(m1_parse, "LAST_PAGE_COLS", {})
    cols = 1
    if lay:
        cols = collections.Counter(lay.values()).most_common(1)[0][0]
    return {
        "file": name, "layout": layout, "cols": cols, "pages": pages, "paras": len(paras),
        "body": len(body), "heading": sum(1 for p in paras if p["kind"] == "heading"),
        "caption": sum(1 for p in paras if p["kind"] == "caption"),
        "chars": sum(len(p["text"]) for p in paras), "ms": ms,
        "longest": len(longest["text"]) if longest else 0,
        "longest_head": (longest["text"][:60] if longest else ""),
        "lower_start": len(lower_start), "no_end": len(no_end), "dup": dup,
        "rects": rects, "bad_chars": bad_chars, "nospace": nospace,
        "xpage": len(xpage),
        "median": sorted(len(p["text"]) for p in body)[len(body) // 2] if body else 0,
        "issues": [],
    }


COLORS = {  # 按 kind 上色，方便肉眼比对
    "body": (0.10, 0.42, 0.75),
    "heading": (0.80, 0.25, 0.15),
    "caption": (0.45, 0.25, 0.65),
    "title": (0.80, 0.25, 0.15),
    "code": (0.15, 0.55, 0.35),
}


def overlay(path, name, pages=(1,)):
    """按「每个 rect 自己的页码」画框。

    旧版先按 p["page"] == pno 过滤段落再画，跨页段落的后半截永远画不出来 ——
    而 web/reader.html 是按 rect 页码逐块渲染的，线上并没有这个问题。
    这里改成和前端一致的口径，否则截图会把「跨页」误报成「漏框」。
    """
    doc = pymupdf.open(path)
    paras = list(m1_parse.parse_pdf(path))
    outs = []
    for pno in pages:
        if pno < 1 or pno > doc.page_count:
            continue
        page = doc[pno - 1]
        for p in paras:
            color = COLORS.get(p["kind"], (0.5, 0.5, 0.5))
            for r in p.get("rects") or []:
                if r.get("page") != pno:
                    continue
                b = r["bbox"]
                page.draw_rect(pymupdf.Rect(*b), color=color, width=0.7)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(2.2, 2.2))
        out = os.path.join(OUT, "overlay", "%s_p%d.png" % (name.replace(".pdf", ""), pno))
        pix.save(out)
        outs.append(out)
    return outs


def main():
    rows = []
    for aid, name, layout in TO_FETCH:
        try:
            path, how = fetch(aid, name)
            print("%-38s %s" % (name, how))
            rows.append((path, name, layout))
        except Exception as exc:
            print("!! 下载失败 %s: %s" % (name, exc))
    rows = LOCAL + rows

    results = []
    for path, name, layout in rows:
        if not os.path.isfile(path):
            continue
        try:
            info = analyse(path, name, layout)
        except Exception as exc:
            print("!! 解析失败 %s: %s" % (name, exc))
            continue
        results.append(info)
        print("%-38s %3d 页 %4d 段 最长 %4d 字 %5d ms" % (name, info["pages"], info["paras"], info["longest"], info["ms"]))
        try:
            overlay(path, name, pages=(1, 2))
        except Exception as exc:
            print("   叠框失败：%s" % exc)

    io.open(os.path.join(OUT, "metrics.json"), "w", encoding="utf-8", newline="\n").write(
        json.dumps(results, ensure_ascii=False, indent=2)
    )

    def pct(a, b):
        return "%d%%" % round(100.0 * a / b) if b else "—"

    lines = []
    lines.append("# 10 篇解析批量测试 · 机器指标\n")
    lines.append("叠框图在 `overlay/`：蓝=正文、红=标题/小标题、紫=图注/表注。框应恰好盖住一个视觉段落。\n")
    lines.append("| 论文 | 版式 | 栏 | 页 | 段 | 正文 | 最长段 | 中位 | 跨页段 | 小写开头 | 无句末标点 | 重复段 | 乱码 | 缺空格 | 解析 ms |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        lines.append("| %s | %s | %d | %d | %d | %d | %d | %d | %d | %d (%s) | %d (%s) | %d | %d | %d | %d |" % (
            r["file"], r["layout"], r["cols"], r["pages"], r["paras"], r["body"], r["longest"], r["median"],
            r.get("xpage", 0),
            r["lower_start"], pct(r["lower_start"], r["body"]), r["no_end"], pct(r["no_end"], r["body"]),
            r["dup"], r["bad_chars"], r["nospace"], r["ms"],
        ))
    io.open(os.path.join(OUT, "metrics.md"), "w", encoding="utf-8", newline="\n").write("\n".join(lines))
    print("\n已写 %s" % os.path.join(OUT, "metrics.md"))


if __name__ == "__main__":
    main()
