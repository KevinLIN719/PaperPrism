# -*- coding: utf-8 -*-
"""把 diag_drop 的打点跑成一张汇总表：哪条丢弃规则在多少篇论文上吃掉了多少正文。

输出 out/drop_stats.json + 控制台表格。用来给「失败模式频次表」提供数字依据。
"""

import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vendor", "pymupdf_pkg"))

import pymupdf        # noqa: E402
import m1_parse as M  # noqa: E402


def stats_one(path):
    doc = pymupdf.open(path)
    M.HYPHEN_VOCAB = M.build_hyphen_vocab(doc)
    M.LAST_PAGE_SIZES.clear()
    M.LAST_PAGE_COLS.clear()
    body_fs = M.detect_body_fs(doc)
    raw = sum(len(doc[i].get_text("text")) for i in range(doc.page_count))
    st = {}
    first_refs_page = None

    def hit(reason, text):
        st[reason] = st.get(reason, 0) + 1
        st[reason + ":chars"] = st.get(reason + ":chars", 0) + len(text)

    in_refs = False
    kept, kept_chars = 0, 0
    for pno, page in enumerate(doc, start=1):
        blocks = M.page_blocks(page)
        tables = M.page_tables(blocks, page)
        if tables:
            blocks = M.drop_table_blocks(blocks, tables)
        blocks = M.drop_table_rows(blocks)
        M.LAST_PAGE_SIZES[pno] = [page.rect.width, page.rect.height]
        if pno == 1:
            hint = M.detect_columns(blocks)
            blocks = [b for b in M.drop_above_title(blocks) if not M.is_front_matter(b["text"])]
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
                hit("boilerplate", t)
                continue
            if M.is_refs_heading(t):
                if first_refs_page is None:
                    first_refs_page = pno
                in_refs = True
                continue
            if in_refs:
                if M.is_appendix_start(t, para.get("fs"), body_fs):
                    in_refs = False
                else:
                    hit("in_refs", t)
                    continue
            if body_fs and pfs and pfs < body_fs * 0.9 - 0.05:
                if M.REF_ENTRY.match(t) or re.search(r"\((?:19|20)\d{2}\)", t[:200]):
                    in_refs = True
                    if first_refs_page is None:
                        first_refs_page = pno
                    hit("small_fs->refs_on", t)
                else:
                    hit("small_fs", t)
                continue
            if not M.keep(t, k):
                if M.is_table_debris(t):
                    hit("keep:table_debris", t)
                elif len(t) < 700 and M.numeric_ratio(t) > 0.42:
                    hit("keep:numeric", t)
                else:
                    hit("keep:too_short", t)
                continue
            kept += 1
            kept_chars += len(t)
    npages = doc.page_count
    doc.close()
    return {
        "file": os.path.basename(path), "pages": npages, "raw_chars": raw,
        "kept": kept, "kept_chars": kept_chars,
        "keep_rate": round(kept_chars / max(raw, 1), 3),
        "refs_on_page": first_refs_page,
        "refs_on_frac": round((first_refs_page or npages) / max(npages, 1), 2),
        "drops": {k: v for k, v in sorted(st.items())},
    }


def main():
    import glob
    paths = []
    for pat in sys.argv[1:]:
        paths.extend(sorted(glob.glob(pat)) if any(c in pat for c in "*?") else [pat])
    out = []
    print("%-40s %5s %6s %6s %8s %s" % ("file", "pages", "keep%", "refs@", "in_refs丢", "最大丢弃项"))
    for p in paths:
        try:
            r = stats_one(p)
        except Exception as exc:
            print("%-40s FAIL %s" % (os.path.basename(p), exc))
            continue
        out.append(r)
        ch = {k[:-6]: v for k, v in r["drops"].items() if k.endswith(":chars")}
        top = max(ch.items(), key=lambda kv: kv[1]) if ch else ("-", 0)
        print("%-40s %5d %5.0f%% %5s %8d %s(%d)" % (
            r["file"], r["pages"], r["keep_rate"] * 100, r["refs_on_page"],
            ch.get("in_refs", 0), top[0], top[1]))
    io.open(os.path.join(ROOT, "out", "drop_stats.json"), "w", encoding="utf-8", newline="\n").write(
        json.dumps(out, ensure_ascii=False, indent=2))
    print("\n已写入 out/drop_stats.json")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    main()
