# -*- coding: utf-8 -*-
"""把 m1_parse 的规则临时退回 v6 行为，用来做「同一把尺子量改前改后」的对比。

B 部分改了 m1_parse，A 部分的 v6 数字是用旧审计口径算的；口径后来又细化过
（作者名单、无标点版面行单独归类）。直接拿两份旧数字对比是不成立的。
这个模块通过 monkey-patch 把 v6 的关键规则装回去，让 audit_full 用**同一把尺子**
重新量一遍 v6，对比才有意义。

用法：
    python tools/audit_full.py --as-v6 papers/*.pdf --json out/audit_v6_same_ruler.json
"""

import re

import m1_parse as M

_ORIG = {}


def apply_v6():
    """把 v6 的行为装回去（只改本次 B 部分动过的那几条规则）。"""
    if _ORIG:
        return
    _ORIG["kind_of"] = M.kind_of
    _ORIG["keep"] = M.keep
    _ORIG["numeric_ratio"] = M.numeric_ratio
    _ORIG["is_table_debris"] = M.is_table_debris
    _ORIG["merge_paragraphs"] = M.merge_paragraphs
    _ORIG["detect_columns"] = M.detect_columns
    _ORIG["rejoin_unfinished"] = M.rejoin_unfinished
    _ORIG["refs_should_exit"] = M.refs_should_exit
    _ORIG["looks_like_author_roster"] = M.looks_like_author_roster
    _ORIG["is_front_matter"] = M.is_front_matter
    _ORIG["drop_metadata"] = M.drop_metadata
    _ORIG["drop_table_rows"] = M.drop_table_rows
    _ORIG["REFS_BY_FONT_HINT"] = M.REFS_BY_FONT_HINT
    _ORIG["REFS_HINT_AFTER"] = M.REFS_HINT_AFTER

    v6_caption = re.compile(r"^\s*(?:Figure|Fig\.|Table|TABLE)\s*(?:\d+|[IVX]+)\s*[.:|—–-]", re.A)
    v6_struct = ("abstract", "introduction", "related work", "conclusion",
                 "conclusions", "discussion", "acknowledgment", "acknowledgments",
                 "acknowledgement", "acknowledgements", "appendix", "references")

    def kind_of_v6(text, fs=0.0, body_fs=0.0):
        if v6_caption.match(text):
            return "caption"
        if len(text) < 40 and text.strip().rstrip(":").lower() in v6_struct:
            return "heading"
        if re.match(r"^(\d+(\.\d+)*\.?|[A-Z]\.)\s+\S", text) and len(text) < 90:
            return "heading"
        if len(text) < 40:
            return "short"
        return "body"

    def numeric_ratio_v6(t):
        toks = t.split()
        if not toks:
            return 1.0
        bad = sum(1 for w in toks if not re.search(r"[A-Za-z]{2}", w))
        return bad / len(toks)

    def is_table_debris_v6(t):
        if len(t) > 250:
            return False
        toks = t.split()
        if not toks:
            return False
        nums = sum(1 for w in toks if re.search(r"\d", w))
        alpha = sum(1 for w in toks if len(re.findall(r"[A-Za-z]{2,}", w)) >= 1)
        if nums < 2 or alpha > 8:
            return False
        return nums / len(toks) >= 0.35 or (nums >= 3 and len(t) < 150)

    def keep_v6(text, kind):
        if kind in ("caption", "title"):
            return True
        if is_table_debris_v6(text):
            return False
        words = re.findall(r"[A-Za-z][A-Za-z'-]+", text)
        if kind == "heading":
            return len(words) >= 1 and len(text) >= 6
        if len(text) < 700 and numeric_ratio_v6(text) > 0.42:
            return False
        return len(words) >= 6

    def merge_paragraphs_v6(blocks):
        lh = M.median_line_height(blocks)
        paras = []
        for b in blocks:
            if paras:
                prev = paras[-1]
                gap = b["bbox"][1] - prev["bbox"][3]
                joined = (gap < lh * 0.8 and prev["col"] == b["col"]
                          and len(prev["text"]) > 80
                          and not prev["text"].endswith((".", "?", "!", ":"))
                          and abs((prev.get("fs") or 0) - (b.get("fs") or 0)) <= 0.5)
                if joined:
                    prev["text"] = M.join_lines([prev["text"], b["text"]])
                    prev["bbox"] = (prev["bbox"][0], prev["bbox"][1], b["bbox"][2], b["bbox"][3])
                    prev["nlines"] += b["nlines"]
                    prev["rects"].append(M._rect_of(b))
                    continue
            p = dict(b)
            p["rects"] = [M._rect_of(b)]
            paras.append(p)
        return paras

    def detect_columns_v6(blocks):
        if not blocks:
            return 1, []
        page_x0 = min(b["bbox"][0] for b in blocks)
        page_x1 = max(b["bbox"][2] for b in blocks)
        content_w = page_x1 - page_x0
        longs = [b for b in blocks if b["nlines"] >= 4]
        if not longs or content_w <= 0:
            return 1, []
        floor_w = content_w * 0.25
        widths = [b["bbox"][2] - b["bbox"][0] for b in longs
                  if (b["bbox"][2] - b["bbox"][0]) >= floor_w]
        if not widths:
            return 1, []
        from statistics import median
        typ = median(widths)
        if typ <= 0:
            return 1, []
        n = max(1, min(4, int(round(content_w / typ))))
        if n < 2:
            return 1, []
        bw = content_w / n
        col_xs = []
        for i in range(n):
            lo, hi = page_x0 + i * bw - 1, page_x0 + (i + 1) * bw
            inside = [b["bbox"][0] for b in blocks if lo <= b["bbox"][0] < hi]
            col_xs.append(min(inside) if inside else page_x0 + i * bw)
        return n, col_xs

    def is_front_matter_v6(t):
        """v6 原版：没有「heading 先放行」那一条（这正是 T1 的根因）。"""
        t = t.strip()
        if not t or len(t) > 320:
            return False
        if "@" in t:
            return True
        if M.FOOTNOTE_MARK.match(t) or M.FRONT_MATTER_START.match(t):
            return True
        if len(t) < 160 and M.digit_ratio(t) >= 0.25:
            return True
        if M.AFFIL.search(t) and (re.match(r"^[*\u2020\u2021\u00a7]?\d", t)
                                  or M.FOOTNOTE_START.match(t)
                                  or numeric_ratio_v6(t) >= 0.1
                                  or len(t) < 120):
            return True
        return False

    def drop_metadata_v6(paras):
        """v6 原版：没有 heading 保护，也没有作者名单过滤。"""
        out = []
        for p in paras:
            if p["page"] == 1:
                t = p["text"].strip()
                if "@" in t:
                    continue
                if len(t) < 300 and M.NOTICE.search(t):
                    continue
                if len(t) < 160 and p["kind"] == "body" and (
                        M.AUTHOR_LINE.match(t) or M.looks_like_author_line(t)):
                    continue
                if len(t) < 260 and M.AFFIL.search(t) and (
                        re.match(r"^[*\u2020\u2021\u00a7]?\d", t)
                        or M.FOOTNOTE_START.match(t)
                        or "E-mail" in t or "@" in t
                        or numeric_ratio_v6(t) >= 0.1):
                    continue
                if len(t) < 160 and p["kind"] == "body" and M.digit_ratio(t) >= 0.25:
                    continue
                if p["kind"] == "body" and M.FOOTNOTE_MARK.match(t):
                    continue
                if (p["kind"] == "body" and len(t) < 400
                        and M.FOOTNOTE_START.match(t)):
                    continue
            out.append(p)
        return out

    def drop_table_rows_v6(blocks):
        """v6 原版：没有「kind_of == heading 就放过」那条（T5 的误删根因）。"""
        caps = [b for b in blocks if M.TABLE_CAP.match(b["text"])]
        if not caps:
            return blocks
        out = []
        for b in blocks:
            if M.TABLE_CAP.match(b["text"]):
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
            if in_band and len(b["text"]) < 120 and not M.looks_like_heading_num(b["text"]):
                continue
            out.append(b)
        return out or blocks

    M.kind_of = kind_of_v6
    M.keep = keep_v6
    M.numeric_ratio = numeric_ratio_v6
    M.is_table_debris = is_table_debris_v6
    M.merge_paragraphs = merge_paragraphs_v6
    M.detect_columns = detect_columns_v6
    M.rejoin_unfinished = lambda paras: paras        # T3/T4 在 v6 里不存在
    M.refs_should_exit = lambda t, fs, bfs: False    # v6 没有复位兜底
    M.looks_like_author_roster = lambda t: False     # v6 不识别作者名单
    M.is_front_matter = is_front_matter_v6
    M.drop_metadata = drop_metadata_v6
    M.drop_table_rows = drop_table_rows_v6
    M.REFS_BY_FONT_HINT = True
    M.REFS_HINT_AFTER = 0.0                          # v6：首页脚注就能触发


def restore():
    for k, v in _ORIG.items():
        setattr(M, k, v)
    _ORIG.clear()
