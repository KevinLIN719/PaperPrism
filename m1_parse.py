# -*- coding: utf-8 -*-
"""M1：把 PDF 变成「段落列表」的命令行工具。

用法：
    python m1_parse.py papers\\bert_1810.04805.pdf
    python m1_parse.py papers\\bert_1810.04805.pdf --full       # 打印每段全文
    python m1_parse.py papers\\bert_1810.04805.pdf --page 3     # 只看第 3 页
    python m1_parse.py papers\\bert_1810.04805.pdf --json out.json

做的事：
  1. 逐页取出文本块（block）和行（line）
  2. 去掉页眉页脚
  3. 判断单栏 / 双栏，双栏按「左栏读完再读右栏」排序
  4. 把上下紧挨着的块并成一段
  5. 输出：[页码] 段号 长度 正文
"""

import sys
import json
import argparse
from pathlib import Path
from statistics import median

# 本机沙箱里 pip 装不上，所以把 wheel 解压到了 vendor/，这里补一下搜索路径
try:
    import pymupdf
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor" / "pymupdf_pkg"))
    import pymupdf

import re

LIGATURES = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
             "\ufb04": "ffl", "\ufb05": "ft", "\ufb06": "st"}
ARXIV_STAMP = re.compile(r"^arXiv:\d{4}\.\d{4,5}v\d+\s*(\[[^\]]+\])?\s*\d{1,2}\s+\w+\s+\d{4}\s*", re.I)


def clean_text(t):
    """统一花体连字、去掉 arXiv 角标。"""
    for k, v in LIGATURES.items():
        t = t.replace(k, v)
    t = CTRL.sub(" ", t)          # PDF 里偶尔混进来的控制字符残渣
    return ARXIV_STAMP.sub("", t)


CTRL = re.compile("[" + "".join(chr(c) for c in list(range(0, 9)) + [11] + list(range(14, 32)) + [127]) + "]")


def prose_score(t):
    """像人话的程度：字母词（>=2 字母）占全部 token 的比例。表格/公式碎片的分数很低。"""
    toks = t.split()
    if not toks:
        return 0.0
    good = sum(1 for w in toks if len(w) >= 2 and w.strip(".,;:()[]").isalpha())
    return good / len(toks)


# ---------- 小工具 ----------

def build_hyphen_vocab(doc):
    """全文扫一遍带连字符的词（如 left-to-right），用来修补断行连字符。"""
    words = set()
    for page in doc:
        for w in page.get_text("text").split():
            w = w.strip(".,;:()[]\"'")
            if "-" in w and len(w) > 3:
                words.add(w.lower())
    return words


HYPHEN_VOCAB = set()


def join_lines(lines):
    """把一行的文本拼成一段；行尾有连字符时尽量还原。"""
    out = ""
    for raw in lines:
        t = raw.strip().replace("\u00ad", "")
        if not t:
            continue
        if not out:
            out = t
        elif out.endswith("-") and t[:1].isalpha():
            stem = out[:-1].rsplit(" ", 1)[-1].lower()      # 断行处前面的那截词
            nxt = t.split(" ", 1)[0].lower()                # 断行处后面那截词
            if not t[:1].islower():
                out = out + t                               # "Berkeley-" + "Parser" → 保留连字符
            # 全文里出现过 "stem-nxt" 这种带连字符的写法，说明连字符是真词的一部分
            elif any(w.startswith(stem + "-" + nxt) for w in HYPHEN_VOCAB):
                out = out + t
            else:
                out = out[:-1] + t
        else:
            out = out + " " + t
    return out


def median_line_height(blocks):
    hs = [b["h"] for b in blocks if b["nlines"] > 0]
    return median(hs) if hs else 12.0


# ---------- 单页处理 ----------

def merge_same_line(lines):
    """PyMuPDF 有时把一行文字拆成两段（两段 y 相同、x 相接）。

    例如 "powerful." 和 "It obtains new state-of-the-art re-" 在同一行上，
    会被当成两行 -> 行首缩进误判成段首。这里先按 y 把它们拼回一行。
    """
    # 用本块最宽的一行当尺子：一行文字不可能比本块最宽的行还宽太多；
    # 用中位数会把「短尾巴 + 后半句」这种（"ers considered." + "The function F(x,…)"）
    # 误判成两栏而拒绝合并。
    if not lines:
        return lines
    max_w = max(l["bbox"][2] - l["bbox"][0] for l in lines)
    out = []
    # 输入必须已经按阅读顺序排好（page_blocks 先调 reading_order_lines）：
    # 这里再按 y 重排的话，"ers considered."(y=660.8) 会排到
    # "The function F(x,…)"(y=660.5) 后面，一行就再也拼不回去了。
    for l in lines:
        if out:
            prev = out[-1]
            same_y = abs(l["bbox"][1] - prev["bbox"][1]) < 2.0
            adjacent = l["bbox"][0] - prev["bbox"][2] < 20
            # 拼起来不能比本块最宽的行宽太多，否则就是把并排的两栏拼成一行了
            fits = (l["bbox"][2] - prev["bbox"][0]) <= max_w * 1.02 + 2
            if same_y and adjacent and fits and l["bbox"][0] >= prev["bbox"][2] - 2:
                t_prev = "".join(sp["text"] for sp in prev["spans"])
                sep = "" if t_prev.endswith("-") else " "
                size = max((sp["size"] for sp in prev["spans"]), default=10.0)
                merged = {
                    "bbox": (prev["bbox"][0], min(prev["bbox"][1], l["bbox"][1]),
                             max(prev["bbox"][2], l["bbox"][2]),
                             max(prev["bbox"][3], l["bbox"][3])),
                    "spans": list(prev["spans"]) + [{"text": sep, "size": size}] + list(l["spans"]),
                    "dir": prev.get("dir", (1, 0)),
                }
                out[-1] = merged
                continue
        out.append(dict(l))
    return out


def reading_order_lines(lines, tol=2.5):
    """把一块里的行按阅读顺序排：同一行（y 相近）内先左后右，整体再从上到下。

    PyMuPDF 给的 lines 顺序不一定是阅读顺序。ResNet 3.2 那个段落里，
    "ers considered." 排在 "The function F(x, {Wi}) represents the" 前面
    （两个 span 的 y 差 0.3pt），照原顺序拼出来两句话就交错成一句了。
    """
    if len(lines) < 2:
        return lines
    rows = []
    for l in sorted(lines, key=lambda l: (l["bbox"][1], l["bbox"][0])):
        for row in rows:
            if abs(l["bbox"][1] - row["y"]) <= tol:
                row["items"].append(l)
                break
        else:
            rows.append({"y": l["bbox"][1], "items": [l]})
    rows.sort(key=lambda r: r["y"])
    out = []
    for row in rows:
        out.extend(sorted(row["items"], key=lambda l: l["bbox"][0]))
    return out


def _figure_regions(page):
    """这一页上「图/表占据的区域」：位图 + 矢量绘图聚簇。

    为什么要它：
    - 图注常被 PyMuPDF 和图里的文字标签并成一个大 block（bmp），bbox 横跨整张图；
    - 正文绕着图走（L 形）时，同一段的窄半截和宽半截 x0 差几十 pt。
    有了区域，就能把「图里的小字」从 block 里摘掉、把正文段落按栏内 band 切开。
    """
    W, H = page.rect.width, page.rect.height
    rects = []
    try:
        for im in page.get_image_info():
            r = pymupdf.Rect(im["bbox"])
            if r.width >= 18 and r.height >= 18:
                rects.append(r)
    except Exception:
        pass
    try:
        for d in page.get_drawings():
            r = d["rect"]
            # 贯穿整页的细线是页边框/栏分隔线；小于 10x6 的是刻度、符号
            if r.width >= W * 0.85 or r.height >= H * 0.85:
                continue
            if r.width < 6 or r.height < 3:
                continue
            rects.append(pymupdf.Rect(r))
    except Exception:
        pass
    if not rects:
        return []
    # 聚簇：图由多个面板/位图拼成，面板之间常隔着 20–40pt。
    # 判据用「一个方向贴得近 + 另一个方向有明显重叠」：既能拼回同一张图，
    # 又不会把上下两段正文和它旁边的图粘成一片。
    def _near(a, b):
        x_gap = max(b.x0 - a.x1, a.x0 - b.x1)
        y_gap = max(b.y0 - a.y1, a.y0 - b.y1)
        x_ov = min(a.x1, b.x1) - max(a.x0, b.x0)
        y_ov = min(a.y1, b.y1) - max(a.y0, b.y0)
        min_w = max(min(a.width, b.width), 1.0)
        min_h = max(min(a.height, b.height), 1.0)
        if x_gap <= 30 and y_ov >= min_h * 0.35:
            return True
        if y_gap <= 30 and x_ov >= min_w * 0.35:
            return True
        return x_gap <= 6 and y_gap <= 6

    merged = True
    while merged and len(rects) > 1:
        merged = False
        out = []
        for r in rects:
            for o in out:
                if _near(r, o):
                    o.include_rect(r)
                    merged = True
                    break
            else:
                out.append(pymupdf.Rect(r))
        rects = out
    page_area = W * H
    keep = []
    for r in rects:
        # 太小的（一条下划线、一个箭头）不算图
        if r.get_area() < page_area * 0.004 or r.width < 40 or r.height < 40:
            continue
        keep.append((round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)))
    return keep


# v12c：栅格膨胀格数与图注并框间距（两者都会让框往外长，宁小不大）
GRID_DILATE = 1
CAP_UNION_GAP = 20.0


def _figure_regions_grid(page):
    """这一页上「图/表占据的区域」。

    为什么不用「把绘图矩形聚簇」：很多图（散点、波形、虚线）是画布上成百上千个
    小 dot，单个矩形很小、彼此不重叠，按矩形聚簇只能拼出半张图。
    这里改成栅格法：把图片和绘图标记都打到 6pt 的网格上，膨胀三格（18pt）后取连通块，
    连通块的包围盒就是图区——散点云、多面板、图例都能连成一片。
    """
    W, H = page.rect.width, page.rect.height
    cell = 6.0
    nx, ny = int(W / cell) + 1, int(H / cell) + 1
    grid = [[0] * nx for _ in range(ny)]

    def _mark(x0, y0, x1, y1):
        for yy in range(max(0, int(y0 // cell)), min(ny - 1, int(y1 // cell)) + 1):
            row = grid[yy]
            for xx in range(max(0, int(x0 // cell)), min(nx - 1, int(x1 // cell)) + 1):
                row[xx] = 1

    try:
        for im in page.get_image_info():
            r = pymupdf.Rect(im["bbox"])
            if r.width >= 6 and r.height >= 6:
                _mark(r.x0, r.y0, r.x1, r.y1)
    except Exception:
        pass
    try:
        for d in page.get_drawings():
            r = d["rect"]
            if r.width <= 0 or r.height <= 0:
                continue
            # 贯穿整页的细线是页边框/栏分隔线；页边竖排水印与页码装饰也不算图
            if r.width >= W * 0.85 or r.height >= H * 0.85:
                continue
            if r.x1 < 46 or r.x0 > W - 46:
                continue
            _mark(r.x0, r.y0, r.x1, r.y1)
    except Exception:
        pass

    # 膨胀：把同一张图里间隔几个点的面板/图例连起来（格数越大框越往外长）
    for _ in range(GRID_DILATE):
        nxt = [row[:] for row in grid]
        for yy in range(ny):
            row = grid[yy]
            for xx in range(nx):
                if not row[xx]:
                    continue
                for dy in (-1, 0, 1):
                    y2 = yy + dy
                    if 0 <= y2 < ny:
                        o = nxt[y2]
                        for dx in (-1, 0, 1):
                            x2 = xx + dx
                            if 0 <= x2 < nx:
                                o[x2] = 1
        grid = nxt

    seen = [[0] * nx for _ in range(ny)]
    page_area = W * H
    regions = []
    for yy in range(ny):
        for xx in range(nx):
            if not grid[yy][xx] or seen[yy][xx]:
                continue
            stack = [(yy, xx)]
            seen[yy][xx] = 1
            x0 = x1 = xx
            y0 = y1 = yy
            n = 0
            while stack:
                cy, cx = stack.pop()
                n += 1
                if cx < x0: x0 = cx
                if cx > x1: x1 = cx
                if cy < y0: y0 = cy
                if cy > y1: y1 = cy
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    y2, x2 = cy + dy, cx + dx
                    if 0 <= y2 < ny and 0 <= x2 < nx and grid[y2][x2] and not seen[y2][x2]:
                        seen[y2][x2] = 1
                        stack.append((y2, x2))
            bx0, by0 = x0 * cell, y0 * cell
            bx1, by1 = (x1 + 1) * cell, (y1 + 1) * cell
            if bx1 - bx0 < 30 or by1 - by0 < 30:
                continue
            # v12c：单块阈值放宽（多面板图的一块可能只有 2000pt²），靠后面的「并排/上下」
            # 判定与面板合并把它们并成整张图，宁小不大
            if (bx1 - bx0) * (by1 - by0) < page_area * 0.002:
                continue
            if n < 20:
                continue
            regions.append((round(bx0, 1), round(by0, 1), round(bx1, 1), round(by1, 1)))
    return regions


def _inside_region(bbox, regions, inset=2.0):
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    for rx0, ry0, rx1, ry1 in regions:
        if rx0 + inset <= cx <= rx1 - inset and ry0 + inset <= cy <= ry1 - inset:
            return True
    return False


def _union_region(bbox, regions, gap=None):
    """图注挨着图/表时，把相连的图区一块并进来（用户要的「图注与图表框在一起」）。

    逐个并、并完还能碰到新的就继续（多面板图会一层层连起来），但只并「贴着」的，
    不会把半页之外的图也拉进来。
    """
    if gap is None:
        gap = CAP_UNION_GAP
    x0, y0, x1, y1 = bbox
    changed = True
    while changed:
        changed = False
        for rx0, ry0, rx1, ry1 in regions:
            if ry0 - gap <= y1 and ry1 + gap >= y0 and rx0 - gap <= x1 and rx1 + gap >= x0:
                nx0, ny0 = min(x0, rx0), min(y0, ry0)
                nx1, ny1 = max(x1, rx1), max(y1, ry1)
                if (nx0, ny0, nx1, ny1) != (x0, y0, x1, y1):
                    x0, y0, x1, y1 = nx0, ny0, nx1, ny1
                    changed = True
    return (x0, y0, x1, y1)


def page_blocks(page, regions=None):
    """返回这一页的文本块：bbox、文本、行数、平均行高。

    PyMuPDF 的一个 block 有时会把相邻两段并在一起，这里按行间距再切一次：
    行距明显大于本块中位数的地方，认为是一处段首。
    """
    d = page.get_text("dict")
    H = page.rect.height
    if regions is None:
        regions = _figure_regions(page)
    blocks = []
    for b in d["blocks"]:
        if b.get("type") != 0:          # 0 = 文本块，1 = 图片
            continue
        lines = b.get("lines") or []
        # 旋转 90 度的竖排水印（"Downloaded from … on …"）直接丢掉
        lines = [l for l in lines if abs(l.get("dir", (1, 0))[1]) < 1e-3]
        if regions:
            # 只丢「整行都在图区里、且很短」的行——那是图里的「a b c」「400 pA」这类标注。
            # 长行可能是真正文（文字压在图上），不能按区域一刀切。
            def _keep_line(l):
                txt = "".join(sp["text"] for sp in l["spans"]).strip()
                if len(txt) > 16:            # 长行可能是正文，宁可留着
                    return True
                if re.fullmatch(r"\d{1,3}", txt):   # 代码清单的行号
                    return True
                for sp in l["spans"]:        # 代码行再短也要留（v10 的代码块规则优先）
                    if MONO_FONT.search(sp.get("font") or ""):
                        return True
                return not _inside_region(l["bbox"], regions, inset=0.0)

            lines = [l for l in lines if _keep_line(l)]
        # 先按阅读顺序排（同一行内左→右），再把被拆开的同一行拼回去。
        # 顺序不能反：PyMuPDF 的两段同一行可能 y 差 0.3pt，按 y 排序会把右半截排在前面，
        # 拼回一行时被判成「不在右边」而拼不上。
        lines = reading_order_lines(lines)
        lines = merge_same_line(lines)
        if not lines:
            continue
        _, y0, _, y1 = b["bbox"]
        # 页眉页脚：整块都落在上下边缘 6% 以内就丢掉
        if y1 < H * 0.06 or y0 > H * 0.94:
            continue

        gaps = [lines[i]["bbox"][1] - lines[i - 1]["bbox"][3] for i in range(1, len(lines))]
        base = median(gaps) if gaps else 0.0
        cur, out = [], []
        max_x1 = 0.0          # 本组目前见到的最右位置，用来判断「上一行是不是提前结束」
        min_x0 = None         # 本组目前最左的行首，缩进要相对它算（不能拿本组第一行）
        for l in lines:
            if cur:
                gap_break = base > 0 and (l["bbox"][1] - cur[-1]["bbox"][3]) > base * 1.35
                # 段与段之间常常没有额外行距，只有段首缩进：
                # 行首比本组最左多 5pt 以上，且上一行明显没写满 → 新段落的开头
                indent_break = ((l["bbox"][0] - min_x0) > 8
                                and (max_x1 - cur[-1]["bbox"][2]) > 8)
                if gap_break or indent_break:
                    out.append(cur)
                    cur, max_x1, min_x0 = [], 0.0, None
            cur.append(l)
            max_x1 = max(max_x1, l["bbox"][2])
            min_x0 = l["bbox"][0] if min_x0 is None else min(min_x0, l["bbox"][0])
        if cur:
            out.append(cur)

        for grp in out:
            texts = ["".join(sp["text"] for sp in l["spans"]) for l in grp]
            # v10（T01）：等宽字体占比。代码清单用的是 Mono 字体（Scaling 附录是
            # BeraSansMono 6.4pt），在此之前被「字号 < 正文 0.9 倍」那条脚注规则整块吃掉。
            mono_n = mono_all = 0
            for l in grp:
                for sp in l["spans"]:
                    n = len(sp["text"].strip())
                    if not n:
                        continue
                    mono_all += n
                    if MONO_FONT.search(sp.get("font") or ""):
                        mono_n += n
            mono = round(mono_n / mono_all, 2) if mono_all else 0.0
            # 代码保留原始行结构：join_lines 会把换行拼成一句，源代码就没法读了
            text = clean_text("\n".join(texts) if mono >= CODE_MONO_MIN else join_lines(texts))
            if not text.strip():
                continue
            fs = max((sp["size"] for l in grp for sp in l["spans"]), default=0.0)
            gx0 = min(l["bbox"][0] for l in grp)
            gx1 = max(l["bbox"][2] for l in grp)
            gy0 = grp[0]["bbox"][1]
            gy1 = grp[-1]["bbox"][3]
            # v12：同一块里的行如果左右边缘变化超过 24pt（正文绕图走），
            # 就分成多个「栏内 band」；rects 按 band 生成，前端才不会横跨图区。
            bands = []
            for l in grp:
                bx0, by0, bx1, by1 = l["bbox"]
                if bands and abs(bx0 - bands[-1][0]) <= 24 and abs(bx1 - bands[-1][2]) <= 24:
                    b = bands[-1]
                    bands[-1] = (min(b[0], bx0), min(b[1], by0), max(b[2], bx1), max(b[3], by1))
                else:
                    bands.append((bx0, by0, bx1, by1))
            blocks.append({
                "bbox": (gx0, gy0, gx1, gy1),
                "bands": [tuple(round(v, 1) for v in b) for b in bands],
                "text": text.strip(),
                "nlines": len(grp),
                "h": (gy1 - gy0) / max(len(grp), 1),
                "fs": fs,
                "mono": mono,
                # 首字下沉：整个块只有一个字母，字号却远大于正文
                "dropcap": bool(re.fullmatch(r"[A-Za-z]", text.strip())),
            })
    return blocks


def _dominant_width(blocks, content_w):
    """量「一条正文行有多宽」：取文本量最大的宽度档，而不是中位数。

    通栏的表格/图表块又宽又多，中位数会被拉偏：中文双栏页曾因此被判成 1 栏或 3 栏
    （实测 c8_crad_202440123 第 5 页判成 3 栏，整页段落按 y 交错排，2.3 跑到 2.2 前面、
    3.7 排到「4 结论」后面）。按「字符数」而不是「块数」加权，表格式短块压不过正文行。
    """
    cands = []
    for b in blocks:
        w = b["bbox"][2] - b["bbox"][0]
        if w >= content_w * 0.30:
            cands.append((w, max(len(b.get("text") or ""), 1)))
    if not cands:
        return None
    weight = {}
    for w, n in cands:
        k = round(w / 5.0) * 5
        weight[k] = weight.get(k, 0) + n
    best = sorted(weight.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    near = [w for w, _ in cands if abs(w - best) <= max(best * 0.15, 8)]
    return sum(near) / len(near) if near else float(best)


def _col_xs_of(blocks, page_x0, content_w, n):
    bw = content_w / n
    col_xs = []
    for i in range(n):
        lo, hi = page_x0 + i * bw - 1, page_x0 + (i + 1) * bw
        inside = [b["bbox"][0] for b in blocks if lo <= b["bbox"][0] < hi]
        col_xs.append(min(inside) if inside else page_x0 + i * bw)
    return col_xs


def detect_columns(blocks):
    """估这一页分几栏。返回 (栏数, 每栏左边界列表)。

    两条判据按顺序试：
    1) 版面上有≥2 个明显的「左边缘簇」→ 这页就是分栏版式，栏数取整页宽 / 典型行宽
       （v8 新增的 _dominant_width，按字符加权，不会被通栏图表块把中位数拉偏）。
    2) 只有一个左边缘簇（居中排列的作者单位表、整页大图/大表）→ 退回「长块宽度中位数」。
       这类页面上「文本量最大的行宽」只是半页，会把单栏判成 2 栏，整页被切碎
       （实测 APS LIGO 第 14/15 页：脚注并进正文 0→10 处）。
    """
    if not blocks:
        return 1, []
    # v10（T07）：代码清单的每行左边缘随缩进乱跳、行宽又常撑到整页，
    # 会伪造出「左边缘簇」并把典型行宽算小，把单栏的代码附录页判成 2–3 栏。
    # 判栏数时先把等宽字体块摘出去。
    probe = [b for b in blocks if not _is_code_block(b)]
    if len(probe) < 4:
        probe = blocks
    page_x0 = min(b["bbox"][0] for b in blocks)
    page_x1 = max(b["bbox"][2] for b in blocks)
    content_w = page_x1 - page_x0
    if content_w <= 0:
        return 1, []

    n_le, xs_le = _columns_by_left_edges(probe, page_x0, content_w)
    if n_le >= 2:
        typ = _dominant_width(probe, content_w)
        if typ:
            n = max(1, min(4, int(round(content_w / typ))))
            if n < 2:
                return 1, []       # 行宽≈整页宽：单栏页（attention 第 9 页就属这种）
            return n, _col_xs_of(blocks, page_x0, content_w, n)
        return n_le, xs_le

    # 没有成形的左边缘簇：长块宽度中位数更稳
    longs = [b for b in probe if b["nlines"] >= 4]
    if not longs:
        return 1, []
    # v10（T07）：连「长块」自己都没有两个左边缘簇，就说明这页文字其实只有一个起点
    # （gpt4 的代码附录页：每行缩进不同但都从同一个左边距开始，行宽被代码撑到整页，
    # 旧逻辑会把它判成 2–3 栏，整页按栏交错重排而乱序）。
    lx = sorted(b["bbox"][0] for b in longs)
    starts = 1
    for i in range(1, len(lx)):
        if lx[i] - lx[i - 1] >= content_w * 0.15:
            starts += 1
    if starts < 2:
        return 1, []
    widths = [b["bbox"][2] - b["bbox"][0] for b in longs
              if (b["bbox"][2] - b["bbox"][0]) >= content_w * 0.25]
    if not widths:
        return 1, []
    typ = median(widths)
    if typ <= 0:
        return 1, []
    n = max(1, min(4, int(round(content_w / typ))))
    if n < 2:
        return 1, []
    return n, _col_xs_of(blocks, page_x0, content_w, n)


def _columns_by_left_edges(blocks, page_x0, content_w):
    """兜底的分栏判据：按块左边缘做 10pt 分桶，取「人口多的簇」当栏边界。

    只在「长块宽度」判据失效时用（中文期刊一行一块的页面）。
    要求每个簇至少有 3 个块、簇间距至少占页宽 1/5，避免把缩进当成新栏。
    """
    if content_w <= 0 or len(blocks) < 6:
        return 1, []
    buckets = {}
    for b in blocks:
        key = int((b["bbox"][0] - page_x0) // 10)
        slot = buckets.setdefault(key, [])
        slot.append(b["bbox"][0])
    clusters = sorted(((sum(v) / len(v), len(v)) for k, v in buckets.items() if len(v) >= 3))
    if len(clusters) < 2:
        return 1, []
    # 合并靠得很近的簇（同一栏的缩进/非缩进两种行首）
    merged = [clusters[0]]
    for x, n in clusters[1:]:
        if x - merged[-1][0] < content_w * 0.2:
            px, pn = merged[-1]
            merged[-1] = ((px * pn + x * n) / (pn + n), pn + n)
        else:
            merged.append((x, n))
    if len(merged) < 2 or len(merged) > 4:
        return 1, []
    return len(merged), [x for x, _ in merged]


def classify(block, col_xs, col_w):
    """返回 (栏号, 是否通栏)。宽度明显超过一栏的块当作通栏（分隔条）。"""
    if not col_xs:
        return 0, True
    x0, _, x1, _ = block["bbox"]
    if (x1 - x0) > col_w * 1.35:
        return -1, True
    idx = min(range(len(col_xs)), key=lambda i: abs(col_xs[i] - x0))
    return idx, False


def order_blocks(blocks, width, layout_hint=None):
    """按栏排序：通栏块当分隔条，两条通栏之间的内容按「第 1 栏读完读第 2 栏…」排。

    layout_hint = (栏数, 每栏左边界)，首页裁掉上一篇残留后块太少，得用整页的版面信息。
    """
    if not blocks:
        return []
    ncols, col_xs = layout_hint or detect_columns(blocks)
    page_x0 = min(b["bbox"][0] for b in blocks)
    page_x1 = max(b["bbox"][2] for b in blocks)
    col_w = (page_x1 - page_x0) / max(ncols, 1)
    blocks = sorted(blocks, key=lambda b: b["bbox"][1])
    ordered, band = [], []
    for b in blocks:
        idx, is_full = classify(b, col_xs, col_w)
        b["col"] = "full" if is_full else idx
        if is_full:
            ordered.extend(sort_band(band))
            band = []
            ordered.append(b)
        else:
            band.append(b)
    ordered.extend(sort_band(band))
    return ordered


def sort_band(band):
    if not band:
        return []
    return sorted(band, key=lambda b: (b["col"], b["bbox"][1]))


def attach_dropcaps(blocks):
    """首字下沉：单独的「R」块接到下一段的开头（"obotic systems" → "Robotic systems"）。"""
    out, pending = [], None
    for b in blocks:
        if b.get("dropcap"):
            pending = b
            continue
        if pending is not None:
            if b["text"][:1].islower() and b.get("col") == pending.get("col"):
                b = dict(b)
                b["text"] = pending["text"] + b["text"]
                pending = None
            else:
                out.append(pending)
                pending = None
        out.append(b)
    if pending is not None:
        out.append(pending)
    return out


def _spaced_caps(t):
    """「T E C H N I CA L R E P O R T」这种字间加空格的页眉/横幅，不是标题。

    判据：去掉空格后全大写，且单字母「词」至少 3 个（正常大写标题不会把字母拆开）。
    """
    words = (t or "").split()
    if len(words) < 4:
        return False
    return "".join(words).isupper() and sum(1 for w in words if len(w) == 1) >= 3


def drop_above_title(blocks):
    """PDF 第 1 页上方常粘着上一篇文章的尾巴：找到本文大标题，把标题之上的块全丢掉。"""
    if not blocks:
        return blocks
    sizes = [b["fs"] for b in blocks if b["nlines"] >= 1]
    body_fs = median(sizes) if sizes else 10.0
    # 标题比正文大多少因排版而异：ResNet 是 2.2 倍，BERT 只有 1.3 倍（14.3 vs 11），
    # 所以用「比中位数至少大 1.5pt 且不小于 1.15 倍」这种松一点的判据，再取最大的那个。
    cands = [b for b in blocks
             if b["fs"] >= max(body_fs + 1.5, body_fs * 1.15)
             and not b.get("dropcap")
             and not _spaced_caps(b["text"])
             and 8 <= len(b["text"]) <= 220
             and len(b["text"].split()) >= 2]
    if not cands:
        return blocks
    title = max(cands, key=lambda b: (b["fs"], -b["bbox"][1]))
    cut = title["bbox"][1]
    kept = [b for b in blocks if b["bbox"][3] > cut + 1]
    for b in kept:
        if b is title:
            b["title"] = True
    return kept


def move_pre_title_tail(ordered):
    """标题之前出现的正文块（多栏页里某栏从更高处起排）属于续文，挪到页末。"""
    for i, b in enumerate(ordered):
        if b.get("title"):
            return ordered[i:] + ordered[:i]
    return ordered


# ---------- 段落合并 ----------

def _overlaps(a, b, tol=1.0):
    """两个 bbox 是不是叠在一起（上下有交叠就算，用来挡住「并排的表格单元格」）。"""
    x = min(a[2], b[2]) - max(a[0], b[0])
    y = min(a[3], b[3]) - max(a[1], b[1])
    return x > tol and y > tol


def _same_band(a, b, tol=24.0):
    """两个矩形是不是「同一栏内、左右边缘基本对齐」的上下两块。

    有些论文的正文绕着图走（图占住一栏上半部分），同一段上半截短、下半截长；
    直接并成一个大矩形会让前端把色条和热区画到图上。左右边缘差得多的不能并。
    """
    return abs(a[0] - b[0]) <= tol and abs(a[2] - b[2]) <= tol


def merge_overlapping_rects(rects):
    """把同一段里互相叠住、且左右对齐的矩形并成一个大矩形（否则前端会画出两层边框）。"""
    out = []
    for r in rects:
        cur = dict(r)
        merged = True
        while merged:
            merged = False
            rest = []
            for o in out:
                if (o["page"] == cur["page"] and _overlaps(o["bbox"], cur["bbox"])
                        and _same_band(o["bbox"], cur["bbox"])):
                    a, b = o["bbox"], cur["bbox"]
                    cur["bbox"] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    merged = True
                else:
                    rest.append(o)
            out = rest
        out.append(cur)
    return out


def coalesce_rects(rects):
    """把同一段里上下紧挨的「逐行矩形」并成一个「栏内块」矩形。

    有些 PDF（NBER 工作论文这类）的文本层一行就是一个 block：段落文字虽然并对了，
    rects 却是一行一个，前端按 rect 画热区就变成一串单行黄框。
    这里按「同页 + 左边缘相近 + 纵向间距不到一行」把连续的行并起来（首行缩进的
    左边缘差有十几 pt，所以 x 容差取 25 而不是 0）；跨栏时左右差得远，不会并。
    效果和 PyMuPDF 直接给出整段 block 的 PDF 一致。
    """
    out = []
    for r in rects:
        x0, y0, x1, y1 = r["bbox"]
        h = max(y1 - y0, 1.0)
        tgt = None
        for o in out:
            if o["page"] != r["page"]:
                continue
            ox0, oy0, _ox1, oy1 = o["bbox"]
            oh = max(oy1 - oy0, 1.0)
            # 只认同一条左边缘：v11 之前这里还允许「右边缘相近」也算同栏，结果
            # 一篇正文绕着图走的论文（上半截窄、下半截宽）被并成一个大矩形，
            # 色条和热区就盖到图上去了。
            same_col = abs(x0 - ox0) <= 25
            gap = y0 - oy1
            if same_col and gap <= max(2.0, min(h, oh) * 0.9) and gap >= -min(h, oh) * 0.6:
                tgt = o
                break
        if tgt is None:
            out.append({"page": r["page"], "bbox": [x0, y0, x1, y1]})
        else:
            b = tgt["bbox"]
            tgt["bbox"] = [min(b[0], x0), min(b[1], y0), max(b[2], x1), max(b[3], y1)]
    return out


SENT_END = (".", "?", "!", ":", "\u3002", "\uff1f", "\uff01", "\uff1a", "\uff1b", "\u201d", "\u2019")
NOTE_MARK_TAIL = re.compile(r"[\d\u00b9\u00b2\u00b3\u2070-\u2079]{1,3}$")
# v9 的两个开关：只为「同一把尺子量 v8」留的（tools/as_v8.py 把它俩置 False）
ENDS_SENTENCE_NOTE_AWARE = True
SHORT_PROSE_JOIN = True


def _ends_sentence(text):
    """这一行读起来是不是「说完了」。

    行尾经常挂着一个上标脚注号：NBER 的 "...(Polanyi, 1966; Autor, 2014).⁴" 在文本层里是
    "...2014).4"，只看最后一个字符会判成「没说完」，于是下一段开头的第一行被并了进来，
    一整段就横跨两个自然段（v9 修的就是这个）。所以先摘掉行尾 1–3 位数字再判。
    """
    s = (text or "").rstrip()
    if ENDS_SENTENCE_NOTE_AWARE:
        s = NOTE_MARK_TAIL.sub("", s).rstrip()
    if not s:
        return False
    return s.endswith(SENT_END)


def _is_code_block(b):
    """等宽字体占比够高 → 代码行。"""
    return (b.get("mono") or 0.0) >= CODE_MONO_MIN


def group_code_blocks(blocks):
    """v10（T01）：把等宽字体的连续行并成「一段代码清单」。

    代码在 PDF 里是一行一个块，而且行号偶尔会用别的字体渲染（Scaling 第 49 页的
    「20」「21」是 DejaVuSans 5.6pt），所以先按「左边缘 + 纵向间距」聚成清单，
    再交给正常排版流程——这样一段代码就是一个段落，不会碎成几十个 20 字符的碎片。
    返回 (非代码块列表, 代码块列表)。
    """
    def _num_only(b):
        t = (b.get("text") or "").strip()
        return len(t) <= 3 and t.isdigit()

    mono = [b for b in blocks if _is_code_block(b)]
    rest = [b for b in blocks if not _is_code_block(b)]
    if not mono:
        return blocks, []
    # 行号列偶尔用别的字体渲染（Scaling 第 49 页的「20」「21」是 DejaVuSans 5.6pt）：
    # 只有紧贴某个等宽块的数字才算行号，散落在页边的页码/坐标轴数字不能当代码。
    extra = []
    for b in list(rest):
        if not _num_only(b):
            continue
        for m in mono:
            if (abs(b["bbox"][1] - m["bbox"][1]) < 12
                    and m["bbox"][0] - 60 < b["bbox"][0] < m["bbox"][2] + 60):
                extra.append(b)
                rest.remove(b)
                break
    # 行号不能单独占一行：找同一行左边最近的那个代码块，拼成「20　TEXT」
    prefix = {}
    used_num = set()
    for b in extra:
        best, bestd = None, None
        for m in mono:
            dy = abs(b["bbox"][1] - m["bbox"][1])
            dx = m["bbox"][0] - b["bbox"][2]
            if dy < 6 and dx > -2 and (bestd is None or (dy, dx) < bestd):
                best, bestd = m, (dy, dx)
        if best is not None:
            prefix[id(best)] = (b["text"] or "").strip()
            used_num.add(id(b))
    code = mono + extra
    # 先按左边缘分列（容差 40pt：同一清单的缩进不会跨这么大的台阶），再按纵向顺序聚
    code.sort(key=lambda b: (b["bbox"][0] // 40, b["bbox"][1]))
    runs = []
    for b in code:
        if runs:
            prev = runs[-1][-1]
            lh = max(prev.get("h") or 0.0, b.get("h") or 0.0, 1.0)
            same_col = abs(b["bbox"][0] - prev["bbox"][0]) < 40
            gap = b["bbox"][1] - prev["bbox"][3]
            if same_col and gap < lh * 3.0:
                runs[-1].append(b)
                continue
        runs.append([b])
    out = []
    for run in runs:
        lines = []
        for b in run:
            if id(b) in used_num:
                continue
            t = (b["text"] or "").strip()
            if not t:
                continue
            ln = prefix.get(id(b))
            if ln:
                lines.append(ln + "  " + t)
            else:
                lines.extend(t.split("\n"))
        # 单行行号（「10」「11」…）并到下一行的行首：多行等宽块整体成一个块时，
        # 行号块与它不同高，上面那套 bbox 对齐找不到它，这里按顺序兜住。
        merged, i = [], 0
        while i < len(lines):
            if re.fullmatch(r"\d{1,3}", lines[i].strip()) and i + 1 < len(lines):
                merged.append(lines[i].strip() + "  " + lines[i + 1].strip())
                i += 2
            else:
                merged.append(lines[i])
                i += 1
        text = "\n".join(merged)
        if not text.strip():
            continue
        out.append({
            "bbox": (min(b["bbox"][0] for b in run), run[0]["bbox"][1],
                     max(b["bbox"][2] for b in run), run[-1]["bbox"][3]),
            "text": text,
            "nlines": sum(b.get("nlines") or 1 for b in run),
            "h": run[0].get("h") or 0.0,
            "fs": run[0].get("fs") or 0.0,
            "mono": 1.0,
            "dropcap": False,
            "code": True,
        })
    return rest, out


def merge_paragraphs(blocks):
    """上下紧挨着、且上一块没说完的，并成一段。"""
    lh = median_line_height(blocks)
    paras = []
    for b in blocks:
        if paras:
            prev = paras[-1]
            gap = b["bbox"][1] - prev["bbox"][3]
            # v10（T01）：代码行单独成段，行与行之间用换行拼（代码的空格缩进有意义，
            # 不能走 join_lines 的「单词间补空格」逻辑），也不参与后面的句末判断。
            if prev.get("code") and _is_code_block(b) and prev["col"] == b["col"]:
                lh_c = max(prev.get("h") or 0.0, b.get("h") or 0.0, 1.0)
                if gap < lh_c * 1.9:
                    prev["text"] = prev["text"].rstrip("\n") + "\n" + (b["text"] or "").strip()
                    prev["bbox"] = (prev["bbox"][0], prev["bbox"][1], b["bbox"][2], b["bbox"][3])
                    prev["nlines"] += b["nlines"]
                    prev["rects"].extend(_rects_of(b))
                    continue
            # 中文期刊的一行常常就是一个 block（PyMuPDF 不给整段），一行只有 20 来个字，
            # 过不了「> 80 字符」这道门槛，整段就被切成十几个碎块。
            # 所以 CJK 块改用「CJK 字符数 ≥ 8」判，并按中文句末标点判断「说完没有」。
            is_cjk = cjk_ratio(prev["text"]) >= 0.3
            if is_cjk:
                long_enough = len(CJK_RE.findall(prev["text"])) >= 8
            else:
                long_enough = len(prev["text"]) > 80
                # 短半句过不了 80 字符门槛，会被切出去变成一个「句首小写」的碎段
                # （BERT：「In this work, we denote the number of layers」44 字符 +
                #  「(i.e., Transformer blocks) as L, …」）。明显是半句话就放行：
                # 末尾是小写字母/逗号、下一块从小写或括号开头、且不像作者名单行。
                if SHORT_PROSE_JOIN and not long_enough and len(prev["text"]) >= 25:
                    tail = prev["text"].rstrip()
                    nxt = (b["text"] or "").lstrip()
                    long_enough = (len(tail.split()) >= 4
                                   and (tail[-1].islower() or tail[-1] in ",;-\uff0c\uff1b(")
                                   and (nxt[:1].islower() or nxt[:1] in "([")
                                   and not looks_like_author_roster(tail)
                                   and prose_score(tail) > 0.6)
            # 行尾的上标脚注号不算标点，否则下一段的第一行会被并进来
            unfinished = not _ends_sentence(prev["text"])
            joined = (gap < lh * 0.8 and prev["col"] == b["col"]
                      and long_enough and unfinished
                      # v8：标题不能并进正文。中文页面标题和正文同字号，早先的
                      # 「字号相同就允许合并」会把「1.1　半监督多标记学习」焊成正文段首。
                      and not _heading_block(prev) and not _heading_block(b)
                      # 字号不同的两块不许并：正文 9pt 后面跟一行 7pt 的脚注/参考文献，
                      # 版面上是紧挨着的，但语义上不是同一段（脚注被并进正文就再也分不开）。
                      and abs((prev.get("fs") or 0) - (b.get("fs") or 0)) <= 0.5)
            if joined:
                prev["text"] = join_cjk_aware(prev["text"], b["text"])
                prev["bbox"] = (prev["bbox"][0], prev["bbox"][1], b["bbox"][2], b["bbox"][3])
                prev["nlines"] += b["nlines"]
                prev["rects"].extend(_rects_of(b))
                continue
        p = dict(b)
        p["rects"] = _rects_of(b)
        p["code"] = _is_code_block(b)       # v10（T01）：代码段标记，供 kind/保字规则使用
        paras.append(p)
    return paras


def join_cjk_aware(a, b):
    """拼两段文字：中文之间不插空格，其余走 join_lines 的连字符逻辑。"""
    a_t, b_t = a.rstrip(), b.lstrip()
    if not a_t:
        return b_t
    if not b_t:
        return a_t
    # 接缝两侧都是 CJK → 直接拼，不要空格（中文不分词）
    if CJK_RE.match(a_t[-1]) and CJK_RE.match(b_t[:1]):
        return a_t + b_t
    return join_lines([a_t, b_t])


STRUCT_HEADING = ("abstract", "introduction", "related work", "related works",
                  "background", "method", "methods", "methodology", "approach",
                  "experiments", "experimental setup", "results", "limitations",
                  "conclusion", "conclusions", "discussion", "acknowledgment",
                  "acknowledgments", "acknowledgement", "acknowledgements",
                  "appendix", "references")


# T1：顶层/多级编号小标题。「1. Introduction」「3.1 Residual Learning」「2 相关工作」
# 编号最多 2 位（挡掉「41.8 Transformer」这类表格里的分数），后面必须跟标题内容。
HEADING_NUM = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+(\S.*)$", re.S)
# 标题里的虚词，算「首字母大写词占比」时不计入
HEAD_FUNCTION_WORDS = {"of", "the", "and", "in", "for", "with", "a", "an", "to", "on",
                       "or", "as", "by", "from", "via", "at", "is", "are", "vs", "vs.",
                       "its", "their", "our", "into", "over", "under", "between"}
CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")

# v10（T01）：等宽字体 = 代码清单。字体名比字号可靠得多，Scaling 的附录代码是
# BeraSansMono 6.4pt，正文是 URWPalladioL 10pt；只看字号会把它当脚注整块丢掉。
MONO_FONT = re.compile(r"(?i)(mono|courier|consol|menlo|inconsolata|sourcecode|"
                       r"source\s*code|code\s*pro|fira\s*code|jetbrains|lucid[ae]?console)")
CODE_MONO_MIN = 0.6        # 一个块里 ≥60% 字符是等宽字体，就算代码行

# v8：表格里的分数行（「23.75 Deep-Att + PosUnk [39]」「36.29 Tuned BART」）会被当成编号标题。
# 章节号不会「父级 ≥ 20 还带两位小数」，所以这条能精确挡掉分数、放行「5.10」这种真实小节。
SCORE_NUM = re.compile(r"^\s*(\d{1,2})\.(\d{2})(?!\.\d)\s")

# v8：PyMuPDF 抽不出数学字体时留下的替换字符（PLOS ONE 的公式碎片「1 XNðviÞ ¼」）
MATH_DEBRIS = re.compile(r"[ðÞ¼½¾×÷±∑∏∫√≤≥≈�]")


# 「Figure 3. …」「Fig. 2: …」「TABLE II — …」「Table 1 | …」：编号后面必须跟标签分隔符
CAPTION_LABEL = re.compile(r"^\s*(?:Figure|Fig\.|FIG\.|Table|TABLE)\s*(?:\d+|[IVX]+)\s*(?:[.:|—–]|-(?=\s))", re.A)

# 有的期刊图注编号后面不跟标点：「Figure 4 Simulated and natural synaptic transmission…」。
# 判据见 _is_caption_loose()：小字号一律认；正文字号时，只要标签后第一个词不是
# shows/illustrates/is… 这类谓语（正文里引用图的句子），也认。
CAPTION_LABEL_LOOSE = re.compile(r"^\s*(?:Figure|Fig\.|FIG\.|Table|TABLE)\s*(?:\d+|[IVX]+)\s+([^\s,.;:){}\[\]]+)", re.A)

# 标签后跟这些词，说明是在正文里引用图（"Figure 4 shows that …"），不是图注本身
CAPTION_VERB = frozenset((
    "shows", "show", "shown", "illustrates", "illustrate", "depicts", "depict",
    "indicates", "indicate", "demonstrates", "demonstrate", "presents", "present",
    "gives", "give", "compares", "compare", "reveals", "reveal", "reports", "report",
    "summarizes", "summarize", "and", "or", "also", "is", "are", "was", "were",
))


def _is_caption_loose(text, fs, body_fs):
    """「Figure 4 Simulated and natural…」这种不带标点的图注。"""
    if len(text) < 30:
        return False
    m = CAPTION_LABEL_LOOSE.match(text)
    if not m:
        return False
    raw = m.group(1)
    # 正文里引用图：括号说明跟在编号后（「Fig. 6 (middle)…」），或者标签后跟谓语
    # （「Table 23 shows the occupations…」）。这两种无论字号大小都不是图注。
    if raw[:1] in ("(", "[", "“", '"'):
        return False
    if raw.strip(".,:;()[]").lower() in CAPTION_VERB:
        return False
    if fs and body_fs and fs <= body_fs * 0.96:      # 图注普遍比正文小半号
        return True
    return raw[:1].isupper() or raw[:1].isdigit()


def _looks_like_score_row(t):
    """这一行是不是表格里的分数行（编号长得像节号，其实是 BLEU/AP 数值）。"""
    m = SCORE_NUM.match(t)
    if not m:
        return False
    if int(m.group(1)) >= 20:
        return True
    return bool(re.search(r"[+±%]|\[\d+\]", t))


def cjk_ratio(t):
    """CJK 字符占全部非空白字符的比例。用来判定「这是中文排版」。"""
    s = "".join(t.split())
    if not s:
        return 0.0
    return len(CJK_RE.findall(s)) / len(s)


def _heading_body_ok(tail):
    """编号后面那截是不是「标题腔」。

    必须挡掉这三类长得像标题、其实是正文的东西：
      - 正文里的交叉引用句：「3.2 shows that the residual …」（后面接小写动词）
      - 编号列表项：「3. See Section 2.2 for a technical description.」（以句号收尾）
      - 表格首行：「50 APbox Method」（没有标题腔）
    判据是「行短 + 不以句号收尾 + 实词基本首字母大写」，再叠加调用方的字号判据，
    就构成任务书 T1 要求的「行短 + 字号 + 后面不接小写词」三重条件。
    """
    tail = tail.strip()
    if not tail or len(tail) > 70:
        return False
    if MATH_DEBRIS.search(tail):        # 公式碎片（ð Þ ¼ 之类）不是标题
        return False
    if cjk_ratio(tail) >= 0.3:          # 中文小标题（「相关工作」）没有大小写概念
        # 中文标题不会这么长：更长的多半是「标题 + 正文」被抽成了一行
        # （实测「1.2　基于知识库和大语言模型的自动化获取和建模基于知识库的方法是通过…」）
        if len(CJK_RE.findall(tail)) > 30:
            return False
        if tail.endswith(("。", "．", ".", "，", "、", "；", "：", "？", "！")):
            return False
        # 句中标点：中文标题里不会出现「，；。」（实测「2.1 节）。在计算损失环节，对于有监督
        # 数据使用其原」「4 部分组成，分别是团队说明（Team）…」都是正文句首被当成了标题）
        if any(ch in tail for ch in "。，；"):
            return False
        # 图注式重复（「32 线激光雷达 激光雷达激光雷达视觉相机」）：同一 4 字词组出现两次以上
        grams = {tail[i:i + 4] for i in range(len(tail) - 3)}
        if any(len(set(g)) > 1 and CJK_RE.match(g) and tail.count(g) >= 2 for g in grams):
            return False
        return True
    if not tail[:1].isupper():          # 「3.2 shows that …」：编号后接小写 → 不是标题
        return False
    if tail.endswith("."):              # 标题不以句号收尾（列表项才会）
        return False
    if "," in tail or ";" in tail:      # 标题里一般不带逗号分号
        return False
    words = [w for w in tail.split() if w]
    sig = [w for w in words if w.lower().strip(".") not in HEAD_FUNCTION_WORDS]
    if not sig:
        return False
    caps = 0
    for w in sig:
        core = w.strip("\"'“”()[]")
        if not core:
            continue
        if core[:1].isupper() or core[:1].isdigit() or not core[:1].isascii():
            caps += 1
    return caps / len(sig) >= 0.7


# 中文期刊的页眉：「12 期 张兴龙等: 基于…侧向控制」「第 3 卷 李某等：…」
# 这类行以「卷/期/页码 + 作者等：」开头，`^\d+\s+汉字` 的形态和章节标题撞车，
# 所以要单独挡掉——否则每页页眉都会变成一个假 heading。
RUNNING_HEAD = re.compile(
    r"^\s*\d{1,4}\s*(?:期|卷|年)|^\s*第\s*\d+\s*(?:期|卷)"
    r"|^\s*\d{1,4}[\s\u3000\u00a0]+\S{1,12}等\s*[:：]")


def _looks_like_running_head(t):
    """这一行是不是期刊页眉（而不是章节标题）。"""
    t = (t or "").strip()
    if RUNNING_HEAD.search(t):
        return True
    # 「… 作者等: 标题」里带冒号 + 「等」，正文小标题不会这么写
    return "等" in t[:12] and ("：" in t or ":" in t)


def heading_level(text):
    """T2：按编号点号个数估层级。「3.」=1、「3.1」=2、「3.1.2」=3；无编号默认 1。"""
    m = HEADING_NUM.match(text.strip())
    if m and _heading_body_ok(m.group(2)):
        return min(len(m.group(1).split(".")), 3)
    return 1


def kind_of(text, fs=0.0, body_fs=0.0):
    """判段落类型。fs/body_fs 可选：给了就按任务书 T1 加「字号 ≥ 正文」这一重条件。"""
    # 图注/表注的判据是「Figure 3. …」「Table 2: …」这种编号标签，
    # 不是「以 Figure/Table 开头」——正文里大量句子以 "Table 3 shows that …"、
    # "Fig. 6 (middle) shows …" 开头，按前缀判会把整段正文当成图注丢掉。
    if CAPTION_LABEL.match(text):
        return "caption"
    # v11：无标点的图注标签（「Figure 4 Simulated and natural…」）
    if _is_caption_loose(text, fs, body_fs):
        return "caption"
    t = text.strip()
    if len(t) < 40 and t.rstrip(":：").lower() in STRUCT_HEADING:
        return "heading"
    # 中文结构标题（「摘要」「引言」「相关工作」「结论」）
    if len(t) <= 12 and cjk_ratio(t) >= 0.8 and t.rstrip("：:") in CJK_STRUCT_HEADING:
        return "heading"
    # T1：编号小标题。行短（< 80 字符）+ 标题腔 + 字号不小于正文
    if len(t) < 80:
        m = HEADING_NUM.match(t)
        if (m and _heading_body_ok(m.group(2)) and not _looks_like_running_head(t)
                and not _looks_like_score_row(t)):
            if not (fs and body_fs) or fs >= body_fs - 0.3:
                return "heading"
        if re.match(r"^[A-Z]\.\s+\S", t) and _heading_body_ok(t[2:]):
            return "heading"
    if len(text) < 40:
        return "short"
    return "body"


CJK_STRUCT_HEADING = ("摘要", "引言", "绪论", "前言", "相关工作", "相关研究", "研究背景",
                      "方法", "本文方法", "实验", "实验结果", "结果", "结果与分析",
                      "讨论", "结论", "总结", "致谢", "参考文献", "附录")


def digit_ratio(t):
    toks = t.split()
    if not toks:
        return 1.0
    return sum(1 for w in toks if re.search(r"\d", w)) / len(toks)


def numeric_ratio(t):
    """「不像词」的 token 占比。中文不用空格分词，所以 CJK 段落按字符口径算。"""
    if cjk_ratio(t) >= 0.15:
        s = "".join(t.split())
        if not s:
            return 1.0
        # 中文段里「有信息的字」= CJK 字 + 拉丁字母；剩下的是数字和符号
        good = sum(1 for c in s if CJK_RE.match(c) or c.isalpha())
        return 1.0 - good / len(s)
    toks = t.split()
    if not toks:
        return 1.0
    bad = sum(1 for w in toks if not re.search(r"[A-Za-z]{2}", w))
    return bad / len(toks)


def is_table_debris(t):
    """表格被拆成一行一格时的残渣：短句、数字 token 多、英文词少。"""
    if len(t) > 250:
        return False
    if cjk_ratio(t) >= 0.15:
        # 中文段落：有句读标点的就是正文，不是表格行
        return not re.search(r"[。，．；,;]", t)
    toks = t.split()
    if not toks:
        return False
    nums = sum(1 for w in toks if re.search(r"\d", w))
    alpha = sum(1 for w in toks if len(re.findall(r"[A-Za-z]{2,}", w)) >= 1)
    if nums < 2 or alpha > 8:
        return False
    return nums / len(toks) >= 0.35 or (nums >= 3 and len(t) < 150)


def keep(text, kind):
    """丢掉公式碎片、页码、单字符这类没有阅读价值的段落。"""
    if kind in ("caption", "title"):
        return True
    # heading 不走表格残渣判据：kind_of() 已经用「行短 + 标题腔 + 字号」三重条件判过了，
    # 而 is_table_debris() 的中文分支（「没有句读标点 = 表格行」）会把
    # 「1　相关工作」这种中文小标题整类误杀。
    if kind != "heading" and is_table_debris(text):
        return False
    # 中文正文：拉丁词数量这把尺子完全不适用（一段中文 0 个拉丁词），改按 CJK 字符数判
    if cjk_ratio(text) >= 0.15:
        n_cjk = len(CJK_RE.findall(text))
        if kind == "heading":
            return n_cjk >= 2 or len(text) >= 6
        return n_cjk >= 20
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]+", text)]
    if kind == "heading":
        # 编号不算词：「3.2 Attention」只剩 1 个英文词，早先的 >=2 会把它当垃圾丢掉
        return len(words) >= 1 and len(text) >= 6
    if len(text) < 700 and numeric_ratio(text) > 0.42:   # 表格单元格碎片（只对正文生效）
        return False
    return len(words) >= 6


# ---------- v8：目录页残渣 ----------
# 目录行 =「编号 标题 页码」；PaLM 那种双栏目录还会带上「页码 子节号」。
TOC_ENTRY = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2})?)\.?\s+(.+?)\s+(\d{1,3})\s+(\d{1,2}\.\d{1,2})\s*$", re.S)
TOC_ENTRY2 = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2})?)\.?\s+(.+?)\s+(\d{1,3})\s*$", re.S)


def toc_entry_text(t):
    """目录行返回「编号 + 标题」（去掉尾部页码），不是目录行返回 None。"""
    t = (t or "").strip()
    m = TOC_ENTRY.match(t)
    if m:
        return (m.group(1) + " " + m.group(2)).strip()
    m = TOC_ENTRY2.match(t)
    if m and len(m.group(2)) >= 3:
        return (m.group(1) + " " + m.group(2)).strip()
    return None


def drop_toc_headings(paras):
    """去掉目录页被误判成 heading 的行。

    判据只有一条：去掉尾部页码后，正文里存在一模一样的真标题 —— 说明这行是目录重复。
    只看「末尾有个数字」会误杀「4.2 Convergence of Algorithm 1」这种真标题，
    所以必须以「正文里有同一个标题」为前提。
    """
    def norm(s):
        return re.sub(r"\s+", " ", s or "").strip()

    heads = {norm(p["text"]) for p in paras if p["kind"] == "heading"}
    drop = set()
    for p in paras:
        if p["kind"] != "heading":
            continue
        base = toc_entry_text(p["text"])
        if base and norm(base) in heads:
            drop.add(id(p))
    if not drop:
        return paras
    return [p for p in paras if id(p) not in drop]


def _heading_block(b):
    """这一块像不像章节标题（中文页面标题与正文同字号，只能靠「编号 + 短 + 无句读」认）。"""
    t = (b.get("text") or "").strip()
    if not t or len(t) > 60:
        return False
    m = HEADING_NUM.match(t)
    return bool(m and _heading_body_ok(m.group(2)))


AFFIL = re.compile(
    r"(universit|institute|research|department|dept\.|college|laborator|school of"
    r"|google|microsoft|facebook|meta ai|openai|deepmind|tencent|alibaba|baidu|huawei"
    r"|amazon|nvidia|apple|inc\.|ltd\.)", re.I)


def looks_like_author_line(t):
    """首页作者+单位行：几乎全是首字母大写的词，且含单位关键词。"""
    toks = t.split()
    if not 4 <= len(toks) <= 24:
        return False
    caps = sum(1 for w in toks if w[:1].isupper() or w[:1] in "*†‡§")
    if caps / len(toks) < 0.75:
        return False
    if t.rstrip().endswith((".", ";")):
        return False
    return bool(AFFIL.search(t))


AUTHOR_LINE = re.compile(r"^[A-Z][\w.'-]+\s+(?:[A-Z]\.\s*)?[A-Z][\w.'-]+\s+[*†\d]")

# 作者名单行：连续的「名 姓」人名，可能带 * † ‡ 和数字角标，整行没有句号。
# PaLM / GPT-4 这类大团队论文首页有十几行这样的名单，`looks_like_author_line()`
# 要求行里含机构关键词，名单行不含，所以全都漏成了正文（实测 PaLM 漏 13 行）。
AUTHOR_ROSTER = re.compile(
    r"^(?:[A-Z][A-Za-z'\u00c0-\u024f\-]+(?:\s+[A-Z]\.)?\s+"
    r"[A-Z][A-Za-z'\u00c0-\u024f\-]+[*\u2020\u2021\u00a7\u2217\d,]*\s*){2,}$")


def looks_like_author_roster(t):
    """首页的纯作者名单行（不含机构关键词的那种）。"""
    s = (t or "").strip()
    if not 12 <= len(s) <= 220:
        return False
    if "." in s or "," in s.rstrip(","):     # 名单行不带句号；逗号只可能在行尾
        return False
    toks = s.split()
    if len(toks) < 4:
        return False
    caps = sum(1 for w in toks if w[:1].isupper())
    if caps / len(toks) < 0.85:
        return False
    return bool(AUTHOR_ROSTER.match(s))


NOTICE = re.compile(
    r"(attribution|copyright|all rights reserved|permission to reproduce|hereby grants"
    r"|equal contribution|listing order is random|conference on neural information"
    r"|proceedings of|published as|under review|preprint)", re.I)


FOOTNOTE_MARK = re.compile(r"^[*†‡∗§]")
FOOTNOTE_START = re.compile(r"^Equal contribution|^\d?https?://")


FRONT_MATTER_START = re.compile(r"^\*?Present address|^Science,|^[A-Z][a-z]+,? and ")


def is_front_matter(t):
    """首页的投稿信息：作者行、单位、通讯地址、致谢/版权声明。返回 True 就该整块丢掉。"""
    t = t.strip()
    if not t or len(t) > 320:
        return False
    # T1：章节标题要先放行。「1. Introduction」的 digit_ratio 是 0.5（两个 token 里
    # 「1.」带数字），会命中下面的「姓名 + 数字角标」规则而被整块丢掉——这正是
    # resnet/BERT/attention 里顶层标题全部缺失的根因（任务书 T1 的现象）。
    if kind_of(t) == "heading":
        return False
    if "@" in t:
        return True
    if FOOTNOTE_MARK.match(t) or FRONT_MATTER_START.match(t):
        return True
    if len(t) < 160 and digit_ratio(t) >= 0.25:      # 姓名后面挂数字角标
        return True
    if AFFIL.search(t) and (re.match(r"^[*\u2020\u2021\u00a7]?\d", t)
                           or FOOTNOTE_START.match(t)
                           or numeric_ratio(t) >= 0.1
                           or len(t) < 120):
        return True
    return False


def drop_metadata(paras):
    """删掉首页的作者名单/单位/版权声明——它们是版面元数据，不是要读的内容。"""
    out = []
    for p in paras:
        if p["page"] == 1:
            t = p["text"].strip()
            if "@" in t:                                  # 作者行几乎都带邮箱
                continue
            if len(t) < 300 and NOTICE.search(t):         # 版权 / 授权声明
                continue
            if len(t) < 160 and p["kind"] == "body" and (
                    AUTHOR_LINE.match(t) or looks_like_author_line(t)):
                continue
            # 纯作者名单（「Aakanksha Chowdhery∗ Sharan Narang∗ Jacob Devlin∗」）
            if p["kind"] == "body" and looks_like_author_roster(t):
                continue
            # 作者单位 / 通讯地址（"1Mechanical and Aerospace Engineering, Cornell Univer-"）
            if len(t) < 260 and AFFIL.search(t) and (
                    re.match(r"^[*\u2020\u2021\u00a7]?\d", t)
                    or FOOTNOTE_START.match(t)
                    or "E-mail" in t or "@" in t
                    or numeric_ratio(t) >= 0.1):
                continue
            # 作者行：姓名后面挂数字角标（"Josh Bongard,1*† Victor Zykov,1 Hod Lipson1,2"）
            if (len(t) < 160 and p["kind"] == "body" and digit_ratio(t) >= 0.25
                    and kind_of(t) != "heading"):
                continue
            if p["kind"] == "body" and FOOTNOTE_MARK.match(t):  # 首页脚注（∗/† 开头）
                continue
            if (p["kind"] == "body" and len(t) < 400
                    and FOOTNOTE_START.match(t)):             # 项目主页链接之类
                continue
        out.append(p)
    return out


REFS_HEAD = re.compile(
    r"^\s*(?:\d+\.?\s*)?(references|bibliography|references and notes"
    r"|literature cited|works cited)\b", re.I)


def is_refs_heading(text):
    t = text.strip()
    return bool(REFS_HEAD.match(t[:60]))


# ---- 参考文献状态机（A 部分 F1 的修复） -------------------------------------
#
# 旧行为：任何「字号小于正文」且前 200 字符里带年份括号的块，都会把 in_refs 置真，
# 而 in_refs 只有遇到附录标题才复位。结果首页的一条脚注
# （「1Following Brown et al. (2020), we use…」）就能让后面 29 页正文全部被丢弃。
# 实测 9/46 篇中招，最严重的 OPT 30 页只剩 5 段。
#
# 新行为分三层：
#   1) 真正的 References 标题 —— 永远可信，照旧置真；
#   2) 「小字 + 年份」这条启发式 —— 只在文档靠后（REFS_HINT_AFTER 之后）才允许置真，
#      首页/前半篇的脚注不再有杀伤力；
#   3) in_refs 状态下遇到「正文字号 + 足够长 + 像散文」的块 —— 自动复位，
#      这样即使 2) 误触发，也只会丢掉几个块而不是半篇论文。
#
# 置 False 可退回「只认 References 标题」的最保守行为（见 待定问题.md Q1）。
REFS_BY_FONT_HINT = True
# 「小字 + 年份」启发式最早可以在文档的哪个位置生效（0.55 = 全文 55% 之后）
REFS_HINT_AFTER = 0.55


def refs_should_exit(text, fs, body_fs):
    """in_refs 状态下，这一块是不是「正文回来了」。

    **只用于撤销「小字 + 年份」启发式的误触发**（见 parse_pdf 里的 refs_by_hint）。
    真正的 References 标题之后，仍然只有附录标题能复位——否则 PMLR/PaLM 那种
    正文字号、长达 200+ 字符的参考文献条目会被当成正文收进来（实测 69 条 / 63 条）。

    判据：字号不小于正文 + 长度 ≥ 200 + 散文度高 + 不像引用条目。
    """
    t = (text or "").strip()
    if len(t) < 200:
        return False
    if body_fs and fs and fs < body_fs - 0.3:
        return False
    if REF_ENTRY.match(t) or REF_AUTHOR_LIST.match(t):
        return False
    if cjk_ratio(t) >= 0.15:
        return True
    if prose_score(t) < 0.75:
        return False
    # 引用条目里「年份」密度很高；正文段落一般不会每 80 字符就出现一个年份
    years = len(re.findall(r"\((?:19|20)\d{2}[a-z]?\)", t))
    return years <= max(1, len(t) // 400)


# 参考文献条目的另一种常见开头：「Assiri, Y. Stochastic optimization…」
# 「Cho, K., van Merrienboer, B., and Bengio, Y. (2014a). …」
# 特征是开头就是「姓, 首字母.」，而且往往连着好几个作者。
REF_AUTHOR_LIST = re.compile(
    r"^\s*[A-Z][A-Za-z'\u00c0-\u024f\-]+,\s*(?:[A-Z]\.\s*){1,3}"
    r"(?:(?:,|and|&)\s*(?:[a-z]+\s+)?[A-Z][A-Za-z'\u00c0-\u024f\-]+,\s*(?:[A-Z]\.\s*){1,3})*")


STOP_END = (".", "?", "!", ":", "”", "’", "—", "。", "？", "！")


def rejoin_fragments(paras):
    """把误切出来的小尾巴接回去：小写开头、很短、前面那段句子还没说完。

    图注经常插在段落中间（版面里图注块夹在两条线之间），所以允许跨过一个 caption。
    """
    out = []
    for p in paras:
        t = p["text"].strip()
        merged = False
        # 小写开头 = 上一段还没说完。短碎片一律接；整块大截只在「跨栏/跨页」时接
        if p["kind"] == "body" and t[:1].islower() and len(t) < 1200:
            cross = True
        else:
            cross = False
        if cross:
            for j in range(len(out) - 1, max(len(out) - 4, -1), -1):
                q = out[j]
                if q["kind"] == "caption":
                    continue                     # 跳过图注，继续往前找
                if (q["kind"] == "body"
                        and not is_table_debris(q["text"])
                        and not q["text"].rstrip().endswith(STOP_END)):
                    q["text"] = q["text"].rstrip() + " " + t
                    q["page_end"] = max(q.get("page_end") or q["page"], p["page"])
                    q["rects"] = q.get("rects", []) + p.get("rects", [])
                    merged = True
                break
        if not merged:
            out.append(p)
    return out


# T3/T4：被图表劈开 / 跨栏 / 跨页的同一自然段，重新拼回去。
#
# `rejoin_fragments()` 只接「小写开头」的后半截，但实测大量续写块是大写开头的
# （"…3.57% top-5 error on the" → "ImageNet test set, and won…"），接不上。
# 这里补一道，判据按任务书 T3/T4 的提示组合，并刻意保守（见 待定问题.md Q5）：
#
#   前块：body、≥ MIN_HEAD_CHARS 字符、不以句末标点收尾、不是表格残渣；
#   后块：body、不是表格残渣，且满足下面任一条
#         a) 小写字母开头                       —— 一定是续写
#         b) 前块最后一个词是虚词/连接词         —— "…on the" + "ImageNet test set"
#         c) 前块以逗号/分号/连字符收尾          —— 句子明确没写完
#   中间：最多跨过 MAX_SKIP 个 caption 块（图表插在段落中间，T3 的典型形态）。
#
# 不满足就不合并：宁可少合并，也不要把两段真正独立的段落粘在一起。
JOIN_MIN_HEAD_CHARS = 60
JOIN_MAX_SKIP_CAPTIONS = 2
# 出现在段尾就说明「话没说完」的词（冠词、介词、连词、助动词、关系词）
TRAILING_FUNCTION_WORDS = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "with", "by", "from",
    "into", "over", "under", "between", "among", "through", "during", "about",
    "and", "or", "but", "nor", "as", "than", "that", "which", "who", "whom", "whose",
    "is", "are", "was", "were", "be", "been", "being", "has", "have", "had",
    "can", "could", "may", "might", "will", "would", "shall", "should", "must",
    "we", "it", "its", "their", "our", "this", "these", "those", "such", "both",
    "each", "every", "all", "any", "some", "no", "not", "more", "most", "less",
    "same", "other", "another", "where", "when", "while", "if", "whether", "because",
    "using", "based", "e.g.", "i.e.", "via", "per", "up", "out", "also",
}


def _unfinished_tail(text):
    """前块是不是「话没说完」。返回 True 时允许后面的块接上来。"""
    s = (text or "").rstrip()
    if len(s) < JOIN_MIN_HEAD_CHARS:
        return False
    if ENDS_SENTENCE_NOTE_AWARE:
        s = NOTE_MARK_TAIL.sub("", s).rstrip()      # 行尾脚注号不算标点
    if s.endswith(STOP_END):
        return False
    if s.endswith((")", "]", "%", "。", "”")):
        return False
    return True


def _continues_previous(prev_text, text):
    """后块是不是前块的续写。"""
    s = (prev_text or "").rstrip()
    t = (text or "").lstrip()
    if not t:
        return False
    # a) 小写开头 —— 句子明显没断开
    if t[:1].isalpha() and t[:1].islower():
        return True
    # c) 前块以逗号/分号/连字符收尾
    if s.endswith((",", ";", "-", "\u2013", "\u2014", "\uff0c", "\uff1b")):
        return True
    # b) 前块最后一个词是虚词
    last = s.split()[-1] if s.split() else ""
    if last.strip("\u201c\u201d\"'()[]").lower() in TRAILING_FUNCTION_WORDS:
        return True
    # 中文正文：前块不以句号收尾就是没写完（中文没有大小写线索）
    if cjk_ratio(s) >= 0.3 and cjk_ratio(t) >= 0.3:
        return True
    return False


def rejoin_unfinished(paras):
    """T3/T4 主体：把「前块没说完 + 后块是续写」的相邻 body 段合并回一段。

    rects 全部保留并按顺序累加（前端要靠 rects 画页边标记，跨栏/跨页都要有）。
    """
    out = []
    for p in paras:
        if p["kind"] == "body" and out and not is_table_debris(p["text"]):
            skipped = []                  # 夹在中间的 caption，合并成功后要放回去
            target = None
            for j in range(len(out) - 1, -1, -1):
                q = out[j]
                if q["kind"] == "caption" and len(skipped) < JOIN_MAX_SKIP_CAPTIONS:
                    skipped.append(j)
                    continue
                if (q["kind"] == "body"
                        and not is_table_debris(q["text"])
                        and _unfinished_tail(q["text"])
                        and _continues_previous(q["text"], p["text"])):
                    target = q
                break
            if target is not None:
                target["text"] = join_cjk_aware(target["text"], p["text"])
                target["page_end"] = max(target.get("page_end") or target["page"], p["page"])
                target["rects"] = (target.get("rects") or []) + (p.get("rects") or [])
                continue
        out.append(p)
    return out


LAST_PAGE_SIZES = {}
LAST_PAGE_COLS = {}      # pno -> 估出来的栏数（1/2/3/4）

# T6：parse_pdf 返回空列表时，这里说明为什么空。服务层据此区分
#   "no_text_layer" 扫描件 / 纯图片 PDF（本来就没有文本可切）
#   "all_filtered"  有文本层，但所有块都被过滤规则丢掉了（这是 bug 信号，该上报）
#   "empty_pdf"     PDF 本身 0 页
#   None            解析正常（非空，或这篇真的没内容）
# 注意：和 LAST_PAGE_SIZES 一样是模块级状态，并发解析两篇会串台（见 待定问题.md Q6）。
LAST_EMPTY_REASON = None

# 解析规则的版本号：改了分段/分类规则就 +1，服务端据此把旧书库里的解析结果判为过期、
# 重新解析并重新批注（否则修好的分类逻辑对已经解析过的论文不生效）。
PARSE_VERSION = 12


def _rects_of(b):
    """一个文本块的 rects：按栏内 band 分开（绕图的段落会有两条）。"""
    bands = b.get("bands") or [b["bbox"]]
    return [{"page": b["page"], "bbox": [round(v, 1) for v in band]} for band in bands]


# ---------------------------------------------------------------- 表格

# 表格图注：「Table 3: …」「TABLE II …」；只在页面上出现这种块时才去找表格
TABLE_CAP = re.compile(r"^\s*(?:Table|TABLE)\s*(?:\d+|[IVX]+)\s*[:.]", re.A)


def page_tables(blocks, page):
    """用 PyMuPDF 自带的表格检测定位本页表格区域（返回 bbox 列表）。

    只在页面上出现「Table N:」图注时才调用——检测本身约 100ms/页，不能每页都跑。
    检测失败就返回空列表，退回原来的行为，不让解析挂掉。
    """
    if not any(TABLE_CAP.match(b["text"]) for b in blocks):
        return []
    try:
        found = page.find_tables()
    except Exception:
        return []
    return [tuple(t.bbox) for t in getattr(found, "tables", [])]


def drop_table_blocks(blocks, tables):
    """丢掉落在表格区域里的小块（单元格/行），图注在表格上方、不在区域内，会保留。

    只删「几乎整个块都在表格里」且「文字很短」的块，避免把紧挨表格的正文段落误删。
    """
    if not tables:
        return blocks
    out = []
    for b in blocks:
        x0, y0, x1, y1 = b["bbox"]
        area = max(1.0, (x1 - x0) * (y1 - y0))
        cover = 0.0
        for tx0, ty0, tx1, ty1 in tables:
            ix = max(0.0, min(x1, tx1) - max(x0, tx0))
            iy = max(0.0, min(y1, ty1) - max(y0, ty0))
            cover = max(cover, ix * iy / area)
        if cover > 0.8 and len(b["text"]) < 240 and not TABLE_CAP.match(b["text"]):
            continue
        out.append(b)
    if not out:            # 整页都被判成表格，说明检测不可信，退回原样
        return blocks
    return out


# 章节编号开头（「3.2 Attention」）——但「41.8 Transformer (big)」这种表格首列分数不算
HEAD_NUM = re.compile(r"^\d{1,2}(?:\.\d{1,2})?\s+[A-Z]")


def looks_like_heading_num(t):
    if re.match(r"^\d{2,}\.\d", t):          # 41.8 / 1018 这种不是章节号
        return False
    return bool(HEAD_NUM.match(t))


def drop_table_rows(blocks):
    """表格区域里的散块：图注下方、第一条长正文之前，短且不像章节标题的块都当表格行丢掉。

    PyMuPDF 的表格检测对没有框线的表格（Attention 的 Table 2）不灵，这里按「图注 + 版面」
    补一刀：表格总是夹在图注和下一段正文之间。
    """
    caps = [b for b in blocks if TABLE_CAP.match(b["text"])]
    if not caps:
        return blocks
    out = []
    for b in blocks:
        if TABLE_CAP.match(b["text"]):
            out.append(b)
            continue
        y0, y1 = b["bbox"][1], b["bbox"][3]
        in_band = False
        for c in caps:
            cy1 = c["bbox"][3]
            if y0 < cy1 - 2:
                continue
            below = [q["bbox"][1] for q in blocks
                     if q["bbox"][1] > cy1 + 2 and q is not b and len(q["text"]) >= 200]
            limit = min(below, default=10 ** 9)
            if y1 <= limit:
                in_band = True
                break
        if in_band and len(b["text"]) < 120 and not looks_like_heading_num(b["text"]):
            # T5：章节标题不能当表格行删。实测 CVPR MAE 第 8 页的
            # 「6. Discussion and Conclusion」就落在「Table 图注 → 下一段长正文」的
            # 夹缝里被删掉了。这里用 kind_of() 的标题判据（行短 + 标题腔）兜一道，
            # 比 looks_like_heading_num() 的纯正则严格：表格首列「3.2 41.8 39.1」
            # 后面不跟字母词，过不了标题腔这一关。
            if kind_of(b["text"]) == "heading":
                out.append(b)
                continue
            continue
        out.append(b)
    if not out:
        return blocks
    return out


# 附录/补充材料级标题——参考文献区结束的信号
APPENDIX_HEAD = re.compile(
    r"^\s*(?:Appendix|Appendices|Supplementary|Supporting Information|"
    r"Additional (?:Results|Experiments|Details|Analysis)|Detailed (?:Results|Experiments|Setup))",
    re.I)


# 出版方/平台样板文案：Science 这类 PDF 每篇末尾都会印，不是论文内容
BOILERPLATE = re.compile(
    r"(?:^|\b)(?:downloaded from|view the article online|use of this article is subject to"
    r"|terms of service|all rights reserved|published by the american association"
    r"|american association for the advancement of science|reprints? and permissions"
    r"|this article is subject to|copyright\s*©)",
    re.I)

# 参考文献条目的样子：「1. J. Smith, Nature 433, 461 (2004).」这种带年份的编号条目
REF_ENTRY = re.compile(r"^\s*(?:\d+\.|[A-Z][a-z]+,\s+[A-Z]\.)\s*.{0,200}?\((?:19|20)\d{2}\)")


def is_boilerplate(text):
    return bool(BOILERPLATE.search((text or "")[:300]))


def is_appendix_start(text, fs, body_fs):
    """参考文献之后的附录标题：显式的 Appendix 字样，或者字号明显大于正文的短标题。"""
    t = (text or "").strip()
    if APPENDIX_HEAD.match(t[:80]):
        return True
    if fs and body_fs and fs >= max(12.5, body_fs * 1.15) and 2 <= len(t) <= 100:
        return True
    return False


def detect_body_fs(doc):
    """全文字号按「字符数」加权，出现最多的那个就是正文字号。

    不能拿「第一段正文」的字号当基准：论文开头常常先出现字号更大的作者行/机构行，
    那样会把真正的正文判成「小字」整篇丢掉（BERT 那篇就是这样只剩标题）。
    """
    weight = {}
    for page in doc:
        for b in page.get_text("dict").get("blocks", []):
            if b.get("type") != 0:
                continue
            for l in b.get("lines", []):
                for s in l.get("spans", []):
                    n = len((s.get("text") or "").strip())
                    if n < 2:
                        continue
                    sz = round((s.get("size") or 0) * 2) / 2
                    if sz < 5 or sz > 40:
                        continue
                    weight[sz] = weight.get(sz, 0) + n
    if not weight:
        return 0.0
    return max(weight.items(), key=lambda kv: kv[1])[0]


def parse_pdf(path, only_page=None):
    global HYPHEN_VOCAB, LAST_EMPTY_REASON
    LAST_EMPTY_REASON = None
    doc = pymupdf.open(path)
    HYPHEN_VOCAB = build_hyphen_vocab(doc)
    LAST_PAGE_SIZES.clear()
    LAST_PAGE_COLS.clear()
    result = []
    in_refs = False
    refs_by_hint = False           # True = in_refs 是「小字 + 年份」启发式置的，可被撤销
    seen_refs_heading = False      # 见过真正的 References 标题后，小字启发式才完全放开
    body_fs = detect_body_fs(doc)
    npages = doc.page_count
    raw_chars = 0                  # 文本层总字符，用来区分「扫描件」和「全被过滤掉」
    for pno, page in enumerate(doc, start=1):
        if only_page and pno != only_page:
            continue
        raw_chars += len(page.get_text("text"))
        regions = _figure_regions(page)          # v12：图/表区域，用来切开绕图的段落
        grid_regions = _figure_regions_grid(page)  # 栅格版：散点/波形图连得更全，给图注并框用
        blocks = page_blocks(page, regions)
        tables = page_tables(blocks, page)                 # 只有出现「Table N:」图注时才检测
        if tables:
            blocks = drop_table_blocks(blocks, tables)     # 表格单元格不当正文段落
        blocks = drop_table_rows(blocks)                   # 没有框线的表格也按版面夹缝丢掉
        # v10（T01）：等宽字体行先聚成「一段代码清单」，再进排版流程
        _rest, _code = group_code_blocks(blocks)
        blocks = _rest
        LAST_PAGE_SIZES[pno] = [round(page.rect.width, 1), round(page.rect.height, 1)]
        if pno == 1:
            hint = detect_columns(blocks)           # 先用整页版面判分栏
            blocks = [b for b in drop_above_title(blocks) if not is_front_matter(b["text"])]       # 再丢掉上一篇论文的残留
            blocks = blocks + _code                 # 代码清单不参与「上一篇论文残留」过滤
            LAST_PAGE_COLS[pno] = hint[0]
            ordered = move_pre_title_tail(
                attach_dropcaps(order_blocks(blocks, page.rect.width, hint)))
        else:
            LAST_PAGE_COLS[pno] = detect_columns(blocks)[0]
            blocks = blocks + _code
            ordered = attach_dropcaps(order_blocks(blocks, page.rect.width))
        for b in ordered:
            b["page"] = pno
        # 文档位置（0=首页，1=末页），用来约束「小字 + 年份」这条启发式
        where = (pno - 1) / max(npages - 1, 1)
        for para in merge_paragraphs(ordered):
            pfs = para.get("fs") or 0.0
            k = "title" if para.get("title") else kind_of(para["text"], pfs, body_fs)
            # v10（T01）：等宽字体块 = 代码清单。它既不是正文也不是脚注，
            # 直接定成 code，绕过下面两条「像脚注/像表格」的丢弃规则。
            if para.get("code"):
                k = "code"
            t = para["text"]
            # 出版社/平台样板文案（Downloaded from …、ISSN …）：整段丢
            if is_boilerplate(t):
                continue
            if is_refs_heading(t):
                in_refs = True           # 进入参考文献区：条目不要，但后面的附录要
                refs_by_hint = False     # 这是可信来源，不许被 refs_should_exit 撤销
                seen_refs_heading = True
                continue
            if in_refs:
                if is_appendix_start(t, pfs, body_fs):
                    in_refs = False      # 附录开始，恢复收录
                elif refs_by_hint and refs_should_exit(t, pfs, body_fs):
                    in_refs = False      # 启发式误触发的兜底（F1）：正文回来了
                    refs_by_hint = False
                else:
                    continue             # 引用条目：跳过
            # 字号明显小于正文的块 = 脚注 / 参考文献条目 / 版权小字，不是正文。
            # 留 0.05 的余量：0.9*10.0 在浮点里是 9.000000000000002，
            # 会让 9.0 号的图注被误判成「小于正文 0.9 倍」而整批丢掉。
            if k == "code":
                pass                 # v10（T01）：代码块不看字号、不看句读，原样保留
            elif k == "caption":
                pass                 # v11：小字号图注是正文之外的独立一类，不该按脚注丢掉
            elif body_fs and pfs and pfs < body_fs * 0.9 - 0.05:
                # 「小字 + 像引用」只在文档靠后、或已经见过 References 标题时才进 in_refs。
                # 否则首页脚注会把整篇论文判成参考文献区（A 部分 F1）。
                if REFS_BY_FONT_HINT and (seen_refs_heading or where >= REFS_HINT_AFTER):
                    if REF_ENTRY.match(t) or re.search(r"\((?:19|20)\d{2}\)", t[:200]):
                        in_refs = True
                        refs_by_hint = not seen_refs_heading
                continue
            if k != "code" and not keep(t, k):
                continue
            if k == "body" and not body_fs:
                body_fs = para.get("fs") or 0.0
            rects = para["rects"]
            if k == "caption" and regions:
                # v12：图注挨着图/表时，把两者并进同一个矩形（用户读图注时能一眼看到对应的图）。
                # 并完之后，被大矩形包住的小矩形要去掉，否则前端会叠着画两条色条。
                # v12c：不再并成一个大 bbox（那会把图注与图之间的其它正文也圈进来，
                # 视觉上「框过大、压到旁边文字」）。改成**多个紧贴的矩形**：
                # 图注自己一个框 + 相邻图区各自一个框，框与框之间不留空、也不互相包含。
                cb = [round(v, 1) for v in tuple(rects[0]["bbox"])]
                for r in rects[1:]:           # 图注自己可能是多段 band，取整个图注的包围盒作锚
                    b = [round(v, 1) for v in tuple(r["bbox"])]
                    cb = [min(cb[0], b[0]), min(cb[1], b[1]), max(cb[2], b[2]), max(cb[3], b[3])]
                near, seen_box = [cb], {tuple(cb)}
                pool = [[round(v, 1) for v in rr] for rr in regions + grid_regions]

                def _related(a, b, gap=CAP_UNION_GAP + 4):
                    y_ov = min(a[3], b[3]) - max(a[1], b[1])
                    x_ov = min(a[2], b[2]) - max(a[0], b[0])
                    same_row = y_ov >= 0.6 * min(a[3] - a[1], b[3] - b[1])
                    same_col = x_ov >= 0.6 * min(a[2] - a[0], b[2] - b[0]) and -gap <= y_ov
                    return same_row or same_col

                # 先从图注出发收一圈，再做传递闭包（多面板图可能有好几层，靠相邻块连起来）
                added = True
                while added:
                    added = False
                    for g in pool:
                        key = tuple(g)
                        if key in seen_box:
                            continue
                        if any(_related(g, h) for h in near):
                            seen_box.add(key)
                            near.append(g)
                            added = True
                # 图区内部再合并（同一张图的多块面板），但**绝不和图注 bbox 合并**
                figs = [g for g in near[1:]]
                merged = True
                while merged:
                    merged = False
                    for i in range(len(figs)):
                        for j in range(i + 1, len(figs)):
                            a, b = figs[i], figs[j]
                            if (a[0] - 40 <= b[2] and a[2] + 40 >= b[0]
                                    and a[1] - 34 <= b[3] and a[3] + 34 >= b[1]):
                                figs[i] = [min(a[0], b[0]), min(a[1], b[1]),
                                           max(a[2], b[2]), max(a[3], b[3])]
                                figs.pop(j)
                                merged = True
                                break
                        if merged:
                            break
                near = [cb] + figs
                kept = [g for g in near
                        if not any(h != g and h[0] <= g[0] + 1 and h[1] <= g[1] + 1
                                   and h[2] >= g[2] - 1 and h[3] >= g[3] - 1 for h in near)]
                rects = [{"page": rects[0]["page"], "bbox": b} for b in kept] or rects
            item = {
                "page": pno,
                "col": para["col"],
                "kind": k,
                "fs": round(para.get("fs", 0.0), 1),
                "rects": rects,
                "text": para["text"],
            }
            if k == "heading":
                item["level"] = heading_level(para["text"])    # T2
            result.append(item)
    doc.close()
    # v8：目录页的「编号 标题 页码」行先摘掉（必须在合并/去元数据之前，
    # 否则它会被当成正文参与合并，形态就毁了）
    final = rejoin_unfinished(rejoin_fragments(drop_metadata(
        merge_across_pages(drop_toc_headings(result)))))
    for para in final:
        para["rects"] = merge_overlapping_rects(coalesce_rects(para.get("rects", [])))
        para["chars"] = len(para.get("text") or "")    # 任务书契约字段
    # T6：让服务端能区分「本来就是空的」和「解不出来」
    if not final:
        if npages == 0:
            LAST_EMPTY_REASON = "empty_pdf"
        elif raw_chars < max(npages * 40, 80):
            LAST_EMPTY_REASON = "no_text_layer"
        else:
            LAST_EMPTY_REASON = "all_filtered"
    return final


def merge_across_pages(paras):
    """上一页最后一段没说完、下一页开头是小写，就接成一段。"""
    out = []
    for p in paras:
        if out:
            a = out[-1]
            same_flow = (a["kind"] == p["kind"] == "body"
                         and not a.get("page_end")
                         and p["page"] == (a.get("page_end") or a["page"]) + 1)
            unfinished = not _ends_sentence(a["text"])
            prose = p["text"][:1].isalpha() and p["text"][:1].islower() and prose_score(p["text"]) > 0.55
            if same_flow and unfinished and prose:
                a["text"] = a["text"].rstrip() + " " + p["text"]
                a["page_end"] = p["page"]
                a["rects"] = a.get("rects", []) + p.get("rects", [])
                continue
        out.append(dict(p))
    return out


# ---------- 命令行 ----------

def main():
    try:
        sys.stdout.reconfigure(errors="replace")   # 控制台编码兜底，别因为生僻符号崩掉
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--full", action="store_true", help="打印每段全文")
    ap.add_argument("--page", type=int, default=None, help="只看第 N 页")
    ap.add_argument("--json", default=None, help="把结果写到 json 文件")
    args = ap.parse_args()

    paras = parse_pdf(args.pdf, args.page)

    lengths = [len(p["text"]) for p in paras]
    print(f"=== {Path(args.pdf).name} ===")
    print(f"段落数 {len(paras)}  平均长度 {sum(lengths)//max(len(lengths),1)} 字符  "
          f"最短 {min(lengths) if lengths else 0}  最长 {max(lengths) if lengths else 0}")
    kinds = {}
    for p in paras:
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
    print("类型分布", kinds)
    print()

    for i, p in enumerate(paras, start=1):
        text = p["text"] if args.full else p["text"][:80].replace("\n", " ")
        tail = "" if args.full else ("…" if len(p["text"]) > 80 else "")
        print(f"[p{p['page']}] #{i} ({p['col']},{p['kind']}) {len(p['text'])}字  {text}{tail}")

    if args.json:
        Path(args.json).write_text(json.dumps(paras, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写入 {args.json}")


if __name__ == "__main__":
    main()
