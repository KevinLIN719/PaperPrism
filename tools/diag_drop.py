# -*- coding: utf-8 -*-
"""诊断：统计 parse_pdf 里每条丢弃规则各丢了多少块/多少字符。

不改 m1_parse 的行为，只是把它的主循环抄一份出来打点，用来定位
「30 页论文只剩 5 段」这种内容大面积丢失到底是哪条规则干的。

用法：
    python tools/diag_drop.py papers_audit/c5_opt.pdf
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vendor", "pymupdf_pkg"))

import re          # noqa: E402
import pymupdf     # noqa: E402
import m1_parse as M  # noqa: E402


def diag(path, show=6):
    doc = pymupdf.open(path)
    M.HYPHEN_VOCAB = M.build_hyphen_vocab(doc)
    M.LAST_PAGE_SIZES.clear()
    M.LAST_PAGE_COLS.clear()
    body_fs = M.detect_body_fs(doc)
    print("body_fs =", body_fs)
    stats = {}
    samples = {}

    def hit(reason, text, fs, page):
        stats[reason] = stats.get(reason, 0) + 1
        stats[reason + ":chars"] = stats.get(reason + ":chars", 0) + len(text)
        samples.setdefault(reason, []).append((page, round(fs or 0, 1), text[:90]))

    in_refs = False
    kept = 0
    for pno, page in enumerate(doc, start=1):
        blocks = M.page_blocks(page)
        n0 = len(blocks)
        tables = M.page_tables(blocks, page)
        if tables:
            blocks = M.drop_table_blocks(blocks, tables)
        n1 = len(blocks)
        blocks = M.drop_table_rows(blocks)
        n2 = len(blocks)
        if n0 - n1:
            stats["drop_table_blocks"] = stats.get("drop_table_blocks", 0) + (n0 - n1)
        if n1 - n2:
            stats["drop_table_rows"] = stats.get("drop_table_rows", 0) + (n1 - n2)
        M.LAST_PAGE_SIZES[pno] = [page.rect.width, page.rect.height]
        if pno == 1:
            hint = M.detect_columns(blocks)
            before = len(blocks)
            blocks = [b for b in M.drop_above_title(blocks) if not M.is_front_matter(b["text"])]
            stats["p1_front_matter"] = stats.get("p1_front_matter", 0) + (before - len(blocks))
            M.LAST_PAGE_COLS[pno] = hint[0]
            ordered = M.move_pre_title_tail(M.attach_dropcaps(M.order_blocks(blocks, page.rect.width, hint)))
        else:
            M.LAST_PAGE_COLS[pno] = M.detect_columns(blocks)[0]
            ordered = M.attach_dropcaps(M.order_blocks(blocks, page.rect.width))
        for b in ordered:
            b["page"] = pno
        for para in M.merge_paragraphs(ordered):
            k = "title" if para.get("title") else M.kind_of(para["text"])
            t = para["text"]
            pfs = para.get("fs") or 0.0
            if M.is_boilerplate(t):
                hit("boilerplate", t, pfs, pno)
                continue
            if M.is_refs_heading(t):
                in_refs = True
                hit("refs_heading", t, pfs, pno)
                continue
            if in_refs:
                if M.is_appendix_start(t, para.get("fs"), body_fs):
                    in_refs = False
                else:
                    hit("in_refs", t, pfs, pno)
                    continue
            if body_fs and pfs and pfs < body_fs * 0.9 - 0.05:
                if M.REF_ENTRY.match(t) or re.search(r"\((?:19|20)\d{2}\)", t[:200]):
                    in_refs = True
                    hit("small_fs->refs_on", t, pfs, pno)
                else:
                    hit("small_fs", t, pfs, pno)
                continue
            if not M.keep(t, k):
                if M.is_table_debris(t):
                    hit("keep:table_debris", t, pfs, pno)
                elif len(t) < 700 and M.numeric_ratio(t) > 0.42:
                    hit("keep:numeric", t, pfs, pno)
                else:
                    hit("keep:too_short", t, pfs, pno)
                continue
            kept += 1
    doc.close()

    print("\n保留段落 %d" % kept)
    print("%-22s %6s %9s" % ("丢弃原因", "块数", "字符"))
    for r in sorted(stats):
        if r.endswith(":chars"):
            continue
        print("%-22s %6d %9d" % (r, stats[r], stats.get(r + ":chars", 0)))
    print()
    for r, items in samples.items():
        print("---", r)
        for pg, fs, t in items[:show]:
            print("   p%-3d fs=%-5s %s" % (pg, fs, t))


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print("=" * 80)
        print(p)
        diag(p)
