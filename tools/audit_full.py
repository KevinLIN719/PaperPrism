# -*- coding: utf-8 -*-
"""A 部分：批量识别验收（不改 m1_parse 的规则，只观察）。

对每篇 PDF 跑 parse_pdf，并按任务书 3.2 的 7 项逐项判定，输出机器可读的 audit.json。
每一项都带「证据」（原文片段 + 页码），便于人工复核；不下任何没有证据支撑的结论。

用法：
    python tools/audit_full.py papers_audit/*.pdf --json out/audit.json
"""

import argparse
import glob
import io
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vendor", "pymupdf_pkg"))

import m1_parse  # noqa: E402
import pymupdf   # noqa: E402

# ---- 判据正则 ----------------------------------------------------------

# 真·图注标签：「Figure 3.」「Table 2:」「Fig. 1 |」
CAPTION_LABEL = re.compile(r"^\s*(?:Figure|Fig\.|Table|TABLE|FIG\.)\s*(?:\d+|[IVX]+)\s*[.:|—–\-]", re.A)
# 正文里以 Figure/Table 开头但其实是句子：「Table 3 shows that …」
CAPTION_SENTENCE = re.compile(r"^\s*(?:Figure|Fig\.|Table|TABLE)\s*(?:\d+|[IVX]+)\s+(?:shows?|show|presents?|"
                              r"reports?|lists?|summari[sz]es?|compares?|illustrates?|gives?|contains?|"
                              r"demonstrates?|depicts?|indicates?|gives)", re.I)
# 参考文献条目：「[12] J. Smith, …, 2019.」「1. J. Smith, Nature 433, 461 (2004).」
REF_ENTRY = re.compile(
    r"^\s*(?:\[\d{1,3}\]|\(\d{1,3}\)|\d{1,3}\.)\s*(?:[A-Z]\.\s*)?[A-Z][A-Za-z'\-]+"
    r"[^.]{0,200}?(?:\((?:19|20)\d{2}\)|(?:19|20)\d{2}[a-z]?\.)")
REF_AUTHOR_YEAR = re.compile(r"^[A-Z][A-Za-z'\-]+,\s+[A-Z]\.(?:\s*[A-Z]\.)*,?.{0,160}?(?:19|20)\d{2}")
# 顶层编号标题：「1. Introduction」「2 Related Work」。编号限 1-2 位，排除「1050 Massachusetts Avenue」
NUM_HEAD = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2})*)\.?\s+([A-Z\u4e00-\u9fff][^\n]{0,60})$")
# 标题里不算实词的虚词，用来算「首字母大写词占比」
HEAD_STOP = {"of", "the", "and", "in", "for", "with", "a", "an", "to", "on", "or",
             "as", "by", "from", "via", "at", "is", "are", "vs", "vs."}


def _title_cased(tail):
    """标题腔：实词几乎都首字母大写。用来挡掉「3. See Section 2.2 for a technical
    description.」「34. Right: a "bottleneck" building block…」这类编号列表项/图注后半截
    ——它们长得像编号标题，但其实是正文句子。"""
    tail = tail.strip()
    if not tail:
        return False
    if any(c in tail for c in ",;:"):         # 标题里一般不带逗号分号冒号
        return False
    if tail.endswith("."):                    # 标题不以句号收尾
        return False
    words = [w for w in re.split(r"\s+", tail) if w]
    sig = [w for w in words if w.lower().strip(".") not in HEAD_STOP]
    if not sig:
        return False
    caps = 0
    for w in sig:
        core = w.strip("\"'\u201c\u201d()[[]")
        if core[:1].isupper() or core[:1].isdigit() or not core[:1].isascii():
            caps += 1
    return caps / len(sig) >= 0.7
# 常见章节名（无编号也该是 heading）
STRUCT_NAMES = ("abstract", "introduction", "related work", "background", "method", "methods",
                "methodology", "approach", "experiments", "experimental setup", "results",
                "discussion", "conclusion", "conclusions", "limitations",
                "acknowledgments", "acknowledgements", "appendix", "related works")
# 「References」是有意吞掉的（进入 in_refs 状态机），不算漏识别
# 句末标点（中英）
STOP_END = (".", "?", "!", ":", "\u201d", "\u2019", "\u2014", "\u3002", "\uff1f", "\uff01", "\uff1b")
# 行尾上标脚注号（v9 起解析器也会先摘掉再判「说完了」）
NOTE_MARK_TAIL = re.compile(r"[\d\u00b9\u00b2\u00b3\u2070-\u2079]{1,3}$")
# 脚注起手式：上标数字/星号开头的小字
FOOTNOTE_LEAD = re.compile(r"^\s*(?:[*\u2020\u2021\u00a7\u2217]|\d{1,2})\s*(?:[A-Z\u4e00-\u9fff]|https?://|See |We |The |For )")
# 中文作者名行：2-4 个汉字姓名，逗号/空格分隔，整行不含句号
CJK_NAME_LINE = re.compile(r"^(?:[\u4e00-\u9fff]{2,4}[,，\s\u00b7]+){1,}[\u4e00-\u9fff]{2,4}\s*\d*$")
CJK = re.compile(r"[\u4e00-\u9fff]")


def _is_caption_text(t):
    return bool(CAPTION_LABEL.match(t))


# 作者名单行：连续的「名 姓」人名，可能带 * † ‡ 和数字角标。
# PaLM 首页有 60+ 个作者排成十几行，每行都没有句末标点，会被当成「段尾截断」
# 刷掉 81 处——那是版面元数据没清干净，不是切段错误，要单独归类。
AUTHOR_ROSTER = re.compile(
    r"^(?:[A-Z][A-Za-z'\u00c0-\u024f\-]+(?:\s+[A-Z]\.)?\s+"
    r"[A-Z][A-Za-z'\u00c0-\u024f\-]+[*\u2020\u2021\u00a7\u2217\d,]*\s*){2,}$")


def is_author_roster(t):
    """这一段是不是首页作者名单（而不是正文）。"""
    s = (t or "").strip()
    if len(s) > 220 or "." in s.replace("\u2026", ""):
        return False
    toks = s.split()
    if len(toks) < 4:
        return False
    caps = sum(1 for w in toks if w[:1].isupper())
    return caps / len(toks) >= 0.85 and bool(AUTHOR_ROSTER.match(s))


# 目录行：「7 Memorization ... 35」或「. . . . . 33」
TOC_LINE = re.compile(r"\.\s*\.\s*\.|\u2026{2,}")
# 表头 / 列名行：一串首字母大写的短词，没有句子结构（「Layers # of Heads dmodel Batch Size」）
TABLE_HEADER = re.compile(r"^[A-Za-z0-9#%/\-\u2212+()\[\].,\s]{0,160}$")
# 项目符号列表项
BULLET_LINE = re.compile(r"^\s*[\u2022\u25cf\u25a0\u00b7\u2013\u2014*]\s+")


def truncation_kind(t):
    """「段尾没有句末标点」的进一步归因。

    任务书 Q5 的三类里，只有第一类是真的要修的切段错误：
      'split'   —— 正文被切断（跨栏/跨页/图表劈开）
      'layout'  —— 原文本身就没有句末标点：表头、目录行、列表项、公式行
      'roster'  —— 首页作者名单
    """
    s = (t or "").strip()
    if not s:
        return None
    if is_author_roster(s):
        return "roster"
    if TOC_LINE.search(s):
        return "layout"
    if BULLET_LINE.match(s):
        return "layout"
    # 表头：短、几乎全是大写开头的词、没有小写功能词连成的句子
    toks = s.split()
    if len(toks) <= 16 and len(s) <= 160:
        lowers = sum(1 for w in toks if w[:1].islower())
        if lowers <= max(1, len(toks) // 5):
            return "layout"
    return "split"


def _truncated_tail(t):
    """段尾像被截断。

    分两级（任务书 5 节说「… defined as:」后面接公式是正常的，不要修）：
      - 返回 "benign"：以冒号结尾 → 后面接公式/列表，属正常；
      - 返回 "bad"：以逗号/分号结尾，或干脆没有任何句末标点 → 真的断了。

    v9 起先摘掉行尾的上标脚注号（"...(Autor, 2014).⁴" 在文本层是 "...2014).4"）——
    那是「说完了」，不是截断。
    """
    s = t.rstrip()
    if not s:
        return None
    s = NOTE_MARK_TAIL.sub("", s).rstrip() or s
    if s.endswith((",", ";", "\uff0c", "\uff1b")):
        return "bad"
    if s[-1:] in (":", "\uff1a"):
        return "benign"
    if s[-1:] in STOP_END:
        return None
    # 以运算符/半个公式收尾，说明后面接公式，属良性
    if s[-1:] in "=+-\u2212(\u2208\u2192\u00b7/":
        return "benign"
    return "bad"


def _page_text_cache(doc):
    return [doc[i].get_text("text") for i in range(doc.page_count)]


def audit_one(path):
    t0 = time.time()
    paras = m1_parse.parse_pdf(path)
    secs = round(time.time() - t0, 2)

    doc = pymupdf.open(path)
    npages = doc.page_count
    raw_pages = _page_text_cache(doc)
    raw_chars = sum(len(t) for t in raw_pages)
    # 页面是否有文本层（扫描件判定）
    has_text_layer = raw_chars >= npages * 40
    page_sizes = dict(m1_parse.LAST_PAGE_SIZES)
    page_cols = dict(m1_parse.LAST_PAGE_COLS)
    doc.close()

    kinds = {}
    for p in paras:
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
    body = [p for p in paras if p["kind"] == "body"]
    caps = [p for p in paras if p["kind"] == "caption"]
    heads = [p for p in paras if p["kind"] == "heading"]
    titles = [p for p in paras if p["kind"] == "title"]

    findings = []        # 每条 = {check, severity, n, evidence:[...]}

    def add(check, severity, items, note=""):
        if items:
            findings.append({
                "check": check, "severity": severity, "n": len(items),
                "note": note,
                "evidence": [{"page": it[0], "text": it[1][:160]} for it in items[:4]],
            })

    # --- 检查 0：内容留存率（最严重的失败模式：整段整页被规则吞掉） ---
    # 口径：解析保留的字符数 / PDF 文本层总字符数。参考文献 + 页眉页脚 + 公式
    # 本来就该丢，所以健康值不是 100%；基线 5 篇在 53%-72%，低于 35% 判为内容大面积丢失。
    keep_rate = round(sum(len(p["text"]) for p in paras) / max(raw_chars, 1), 3)
    if has_text_layer and keep_rate < 0.35:
        findings.append({
            "check": "0-内容大面积丢失", "severity": "high", "n": 1,
            "note": "只保留了文本层的 %.0f%%（%d / %d 字符）" % (
                keep_rate * 100, sum(len(p["text"]) for p in paras), raw_chars),
            "evidence": [],
        })

    # --- 检查 1：标题 ---
    chk1 = {"titles": len(titles), "text": titles[0]["text"][:120] if titles else ""}
    if len(titles) != 1:
        add("1-标题", "high" if has_text_layer else "info",
            [(t["page"], t["text"]) for t in titles] or [(1, "(无 title 段)")],
            "title=%d，应为 1" % len(titles))

    # --- 检查 2：段落边界 ---
    # 「段尾没有句末标点」要先归因再判错，否则表头、目录行、作者名单会刷出大量假阳性
    # （PaLM 实测 81 处里只有 1/4 是真的切段错误）。
    split_bad, layout_bad, roster = [], [], []
    for p in body:
        if _truncated_tail(p["text"]) != "bad":
            continue
        kind = truncation_kind(p["text"])
        if kind == "roster":
            roster.append((p["page"], p["text"][:110]))
        elif kind == "layout":
            layout_bad.append((p["page"], p["text"][-110:]))
        else:
            split_bad.append((p["page"], p["text"][-110:]))
    benign = [(p["page"], p["text"][-110:]) for p in body if _truncated_tail(p["text"]) == "benign"]
    lower_start = [(p["page"], p["text"][:110]) for p in body
                   if p["text"][:1].isalpha() and p["text"][:1].islower()]
    # 两段粘一段：段内出现「句末标点 + 空格 + 大写」且总长很大，只做统计不判错
    huge = [(p["page"], p["text"][:110]) for p in body if len(p["text"]) > 3500]
    add("2-段尾截断", "mid", split_bad, "正文句被切断（跨栏/跨页/图表劈开）—— 真要修的")
    add("2-无标点版面行", "info", layout_bad, "表头/目录行/列表项，原文本来就没有句末标点")
    add("2-段尾接公式", "info", benign, "以冒号或运算符结尾，后面接公式，属正常")
    add("2-段首小写", "mid", lower_start, "段落以小写字母开头 = 上一段没接上")
    add("2-超长段", "low", huge, "单段 > 3500 字符，可能把多段粘在一起")
    add("1-作者名单进正文", "mid", roster, "首页作者行没被 drop_metadata 清掉")

    # --- 检查 3：图注/表注 ---
    cap_wrong = [(p["page"], p["text"][:140]) for p in caps if not _is_caption_text(p["text"])]
    body_is_cap = [(p["page"], p["text"][:140]) for p in body
                   if _is_caption_text(p["text"]) and not CAPTION_SENTENCE.match(p["text"])]
    cap_sentence = [(p["page"], p["text"][:140]) for p in caps if CAPTION_SENTENCE.match(p["text"])]
    add("3-caption误判", "mid", cap_wrong, "被判 caption 但没有图注标签")
    add("3-caption漏判", "low", body_is_cap, "带图注标签却留在 body")
    add("3-正文被判图注", "high", cap_sentence, "「Table N shows…」这类正文句被判成 caption")

    # --- 检查 4：参考文献 / 附录 ---
    refs_leak = [(p["page"], p["text"][:140]) for p in body
                 if REF_ENTRY.match(p["text"]) or REF_AUTHOR_YEAR.match(p["text"])]
    add("4-参考文献漏成正文", "high", refs_leak)
    # 附录是否保留：原文里有 Appendix 字样的页，解析结果里是否还有段落
    app_pages = [i + 1 for i, t in enumerate(raw_pages)
                 if re.search(r"^\s*(?:Appendix|APPENDIX|A\.\d|Supplementary)", t, re.M)]
    kept_pages = {p["page"] for p in paras} | {r["page"] for p in paras for r in p.get("rects", [])}
    app_lost = [(pg, "原文第 %d 页有 Appendix 字样，解析结果里该页 0 段" % pg)
                for pg in app_pages if pg not in kept_pages]
    add("4-附录丢失", "mid", app_lost)

    # --- 检查 5：脚注 ---
    # 脚注特征：段内出现「句末标点 + 上标数字 + 大写」或段落以脚注起手式开头
    foot_in_body = [(p["page"], p["text"][:150]) for p in body
                    if FOOTNOTE_LEAD.match(p["text"]) and len(p["text"]) < 400]
    # 正文段尾部粘了一段 URL/小字脚注
    foot_tail = [(p["page"], p["text"][-150:]) for p in body
                 if re.search(r"[a-z]\.\s*\d{1,2}(?:See|https?://|The code|Our code)", p["text"])]
    add("5-脚注并入正文", "mid", foot_in_body + foot_tail)

    # --- 检查 6：章节标题清单 ---
    head_texts = [h["text"].strip() for h in heads]
    head_norm = {re.sub(r"\s+", " ", h).lower().rstrip(":") for h in head_texts}
    # 还要排掉「已经出现在某个 body/caption 段开头」的行：那说明它没丢，只是没单独成段
    inline_heads = set()
    for p in paras:
        first = re.sub(r"\s+", " ", p["text"][:90]).lower()
        inline_heads.add(first)
    # 从原文里找「独占一行的编号/结构标题」，看解析有没有漏
    missed = []
    seen = set()
    for pno, t in enumerate(raw_pages, start=1):
        for line in t.splitlines():
            s = line.strip()
            if not s or len(s) > 70:
                continue
            m = NUM_HEAD.match(s)
            # 结构标题必须首字母大写（"Method" / "METHOD"）：resnet 第 6 页表格里的
            # 列名 "method" 是小写的，不是章节标题
            ok_struct = (s.lower().rstrip(":.") in STRUCT_NAMES
                         and (s[:1].isupper() or not s[:1].isascii()))
            if m and not _title_cased(m.group(2)):
                m = None
            if not (m or ok_struct):
                continue
            key = re.sub(r"\s+", " ", s).lower().rstrip(":")
            if key in seen:
                continue
            seen.add(key)
            if key in head_norm:
                continue
            # 它可能作为某段的开头被吸进了正文段（粗体引导词排版），这不算「丢」，算「没拆开」
            if any(h.startswith(key) for h in inline_heads):
                missed.append((pno, s + "   [被吸进正文段开头]"))
                continue
            missed.append((pno, s))
    add("6-heading漏识别", "high", missed, "原文有这些独立标题行，解析结果里不是 heading")

    # --- 检查 7：耗时 ---
    if secs > 10:
        add("7-耗时", "mid", [(0, "单篇 %.2f 秒" % secs)])

    # --- 扫描件 ---
    if not has_text_layer:
        findings.append({
            "check": "0-无文本层", "severity": "high" if paras else "info", "n": 1,
            "note": "原文 %d 页仅 %d 个字符，判为扫描件；解析得到 %d 段" % (npages, raw_chars, len(paras)),
            "evidence": [],
        })

    # --- 中文排版 ---
    cjk_chars = sum(len(CJK.findall(p["text"])) for p in paras)
    cjk_name_leak = [(p["page"], p["text"][:80]) for p in paras
                     if p["page"] == 1 and p["kind"] == "body" and CJK_NAME_LINE.match(p["text"].strip())]
    add("8-中文姓名行进正文", "mid", cjk_name_leak)

    # --- usable_ratio：可用率 ---
    # 口径见 识别报告.md「可用率怎么算」：一段「可用」= 不触发任何 high/mid 级段落级问题
    bad_ids = set()
    for p in body:
        t = p["text"]
        if _truncated_tail(t) == "bad" and truncation_kind(t) in ("split", "roster"):
            bad_ids.add(id(p))
        if t[:1].isalpha() and t[:1].islower():
            bad_ids.add(id(p))
        if REF_ENTRY.match(t) or REF_AUTHOR_YEAR.match(t):
            bad_ids.add(id(p))
        if FOOTNOTE_LEAD.match(t) and len(t) < 400:
            bad_ids.add(id(p))
        if len(t) > 3500:
            bad_ids.add(id(p))
    for p in caps:
        if CAPTION_SENTENCE.match(p["text"]) or not _is_caption_text(p["text"]):
            bad_ids.add(id(p))
    scored = body + caps
    usable = len(scored) - len(bad_ids)
    usable_ratio = round(usable / len(scored), 4) if scored else 0.0

    issues = ["%s×%d" % (f["check"], f["n"]) for f in findings if f["severity"] in ("high", "mid")]

    return {
        "file": os.path.basename(path),
        "parse_version": m1_parse.PARSE_VERSION,
        "pages": npages,
        "cols_mode": max(set(page_cols.values()), key=list(page_cols.values()).count) if page_cols else 1,
        "secs": secs,
        "paras": len(paras),
        "kinds": kinds,
        "body_chars": sum(len(p["text"]) for p in body),
        "raw_chars": raw_chars,
        "keep_rate": keep_rate,
        "has_text_layer": has_text_layer,
        "cjk_chars": cjk_chars,
        "title_check": chk1,
        "headings": head_texts,
        "usable_ratio": usable_ratio,
        "scored_paras": len(scored),
        "usable_paras": usable,
        "findings": findings,
        "issues": issues,
        "page_sizes_n": len(page_sizes),
    }


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--json", default=None)
    ap.add_argument("--as-v6", action="store_true",
                    help="把 m1_parse 临时退回 v6 规则，用同一把尺子量改前的结果")
    ap.add_argument("--as-v8", action="store_true",
                    help="关掉 v9 的两条新判据，用同一把尺子量 v8 的结果")
    args = ap.parse_args()

    if args.as_v6:
        import as_v6
        as_v6.apply_v6()
        print("[已切换到 v6 规则]")
    if args.as_v8:
        import as_v8
        as_v8.apply_v8()
        print("[已切换到 v8 规则]")

    paths = []
    for pat in args.pdfs:
        paths.extend(sorted(glob.glob(pat)) if any(c in pat for c in "*?") else [pat])

    out = []
    for path in paths:
        try:
            r = audit_one(path)
        except Exception as exc:
            r = {"file": os.path.basename(path), "error": "%s: %s" % (type(exc).__name__, exc),
                 "issues": ["解析崩溃"], "findings": [], "usable_ratio": 0.0}
        out.append(r)
        print("%-34s %3s页 %4s段 %5s秒 可用率 %-7s %s" % (
            r["file"], r.get("pages", "?"), r.get("paras", "?"), r.get("secs", "?"),
            r.get("usable_ratio", "?"), "；".join(r.get("issues") or []) or "无"))

    if args.json:
        d = os.path.dirname(os.path.abspath(args.json))
        if d:
            os.makedirs(d, exist_ok=True)
        io.open(args.json, "w", encoding="utf-8", newline="\n").write(
            json.dumps(out, ensure_ascii=False, indent=2))
        print("\n已写入", args.json)


if __name__ == "__main__":
    main()
