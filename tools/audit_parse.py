"""批量体检解析结果：给一批 PDF，看 m1_parse 切出来的段落有哪些典型毛病。

用法：
    python tools/audit_parse.py papers/*.pdf
    python tools/audit_parse.py papers/*.pdf --json out/audit.json
    python tools/audit_parse.py papers/*.pdf --csv out/report.csv

每篇输出一节，字段含义见 audit_one()。退出码永远是 0（这是体检工具，不是测试）。

T8 新增两项：
  - usable_ratio：段落切分可用率，口径见 USABLE_DOC（也写在 识别报告.md 第 2 节）
  - --csv：一行一篇的汇总表，列 file / pages / paras / body / caption / heading /
    usable_ratio / issues
"""

import argparse
import csv
import glob
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vendor", "pymupdf_pkg"))

import m1_parse  # noqa: E402

# 「1. J. Smith, Nature 433, 461 (2004).」这种参考文献条目
REF_LIKE = re.compile(r"^\s*(?:\d+\.|[A-Z][a-z]+,\s+[A-Z]\.).{0,300}?\((?:19|20)\d{2}\)")
# 出版社/平台样板
BOILER_LIKE = re.compile(
    r"(?:downloaded from|view the article online|permissions|all rights reserved"
    r"|published by the american|issn\s|reprints? and permissions)", re.I)
# 明显被两栏交错的迹象：一行结尾是连字符的半个词，紧接着另一个大写开头的半句
INTERLEAVE = re.compile(r"[a-z]- [A-Z][a-z]+ .{0,60}? [a-z]+er?e?d? ")
# 没说完就断掉的段尾（正文段不该以这些结尾）
BAD_TAIL = re.compile(r"[,;:]\s*$")

# ---- T8：可用率 -------------------------------------------------------------

USABLE_DOC = """usable_ratio（段落切分可用率）

评分对象：kind in (body, caption) 的段落。title/heading/short 不参与——它们不是阅读单位。
一段判为「不可用」，当且仅当命中下列任一条：
  1. 段尾真截断：以 , ; ，； 结尾，或完全没有句末标点
     （以冒号或运算符结尾不算错：「… defined as:」后面接公式是正常排版）
  2. 段首小写：首字符是小写字母 → 上一段的后半截没接上
  3. 参考文献漏成正文：匹配「[12] Smith, J., … 2019.」这类条目样式
  4. 脚注并入正文：以 * / 匕首号 / 上标数字起手且 < 400 字符
  5. 超长粘连：单段 > 3500 字符
  6. 图注边界错：caption 段没有「Figure N.」「Table N:」标签
usable_ratio = 可用段数 / 评分对象段数。

已知局限：只检查「段落自身形态」，查不出「两个独立段落被错误合并」（除非超长），
所以这是可用率的**上界**。
它也不反映「内容整段被丢掉」——那种情况段数少、剩下的反而都对，可用率会虚高，
所以必须同时看 keep_rate 列（解析字符 / PDF 文本层字符，健康区间约 50%-95%）。"""

CAPTION_TAG = re.compile(r"^\s*(?:Figure|Fig\.|FIG\.|Table|TABLE)\s*(?:\d+|[IVX]+)\s*[.:|—–-]", re.A)
USABLE_REF = re.compile(
    r"^\s*(?:\[\d{1,3}\]|\(\d{1,3}\)|\d{1,3}\.)\s*(?:[A-Z]\.\s*)?[A-Z][A-Za-z'\-]+"
    r"[^.]{0,200}?(?:\((?:19|20)\d{2}\)|(?:19|20)\d{2}[a-z]?\.)")
USABLE_FOOTNOTE = re.compile(
    r"^\s*(?:[*\u2020\u2021\u00a7\u2217]|\d{1,2})\s*"
    r"(?:[A-Z\u4e00-\u9fff]|https?://|See |We |The |For )")
SENTENCE_END = (".", "?", "!", ":", "\u201d", "\u2019", "\u2014",
                "\u3002", "\uff1f", "\uff01", "\uff1a")


def tail_state(t):
    """段尾状态：None 正常 / 'benign' 后面接公式 / 'bad' 真断了。"""
    s = (t or "").rstrip()
    if not s:
        return None
    if s.endswith((",", ";", "\uff0c", "\uff1b")):
        return "bad"
    if s[-1:] in SENTENCE_END:
        return None
    if s[-1:] in "=+-\u2212(\u2208\u2192\u00b7/":
        return "benign"
    return "bad"


def para_unusable(p):
    """这一段为什么不可用；可用则返回 None。"""
    t = p["text"]
    if p["kind"] == "caption":
        return None if CAPTION_TAG.match(t) else "caption无标签"
    if tail_state(t) == "bad":
        return "段尾截断"
    if t[:1].isalpha() and t[:1].islower():
        return "段首小写"
    if USABLE_REF.match(t):
        return "参考文献漏成正文"
    if USABLE_FOOTNOTE.match(t) and len(t) < 400:
        return "脚注并入正文"
    if len(t) > 3500:
        return "超长粘连"
    return None


def audit_one(path):
    import time
    t0 = time.time()
    paras = m1_parse.parse_pdf(path)
    secs = round(time.time() - t0, 2)
    kinds = {}
    for p in paras:
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1

    body = [p for p in paras if p["kind"] == "body"]
    refs_leak = [p for p in body if REF_LIKE.match(p["text"])]
    boiler = [p for p in paras if BOILER_LIKE.search(p["text"][:200])]
    short_body = [p for p in body if len(p["text"]) < 40]
    bad_tail = [p for p in body if BAD_TAIL.search(p["text"].rstrip())]
    interleave = [p for p in body if INTERLEAVE.search(p["text"][:300])]
    titles = [p for p in paras if p["kind"] == "title"]
    # 段落里出现两次「. 」却被当成一段：可能是跨栏/跨页合并过头
    merged_hard = [p for p in body if len(p["text"]) > 3000]

    # T8：可用率 + 留存率
    scored = [p for p in paras if p["kind"] in ("body", "caption")]
    reasons = {}
    bad = 0
    for p in scored:
        why = para_unusable(p)
        if why:
            bad += 1
            reasons[why] = reasons.get(why, 0) + 1
    usable_ratio = round((len(scored) - bad) / len(scored), 4) if scored else 0.0
    raw_chars = _raw_text_chars(path)
    keep_rate = round(sum(len(p["text"]) for p in paras) / raw_chars, 4) if raw_chars else 0.0

    issues = []
    if len(titles) != 1:
        issues.append("title=%d（应为 1）" % len(titles))
    if refs_leak:
        issues.append("参考文献漏成正文 %d 段" % len(refs_leak))
    if boiler:
        issues.append("出版社样板 %d 段" % len(boiler))
    if interleave:
        issues.append("疑似两栏交错 %d 段" % len(interleave))
    if short_body:
        issues.append("超短正文段 %d 段" % len(short_body))
    if len(body) > 2500:
        issues.append("正文段数异常多 %d" % len(body))
    # 内容大面积丢失：整篇被规则吞掉（A 部分 F1/F7）
    if raw_chars and keep_rate < 0.35 and paras:
        issues.append("内容大面积丢失（只保留文本层的 %.0f%%）" % (keep_rate * 100))
    if not paras:
        issues.append("0 段（LAST_EMPTY_REASON=%s）" % m1_parse.LAST_EMPTY_REASON)
    if secs > 10:
        issues.append("解析耗时 %.1f 秒" % secs)

    return {
        "file": os.path.basename(path),
        "parse_version": m1_parse.PARSE_VERSION,
        "pages": len(m1_parse.LAST_PAGE_SIZES),
        "secs": secs,
        "paras": len(paras),
        "headings": [p["text"][:70] for p in paras if p["kind"] == "heading"],
        "heading_levels": [p.get("level") for p in paras if p["kind"] == "heading"],
        "kinds": kinds,
        "body_chars": sum(len(p["text"]) for p in body),
        "raw_chars": raw_chars,
        "keep_rate": keep_rate,
        "usable_ratio": usable_ratio,
        "scored_paras": len(scored),
        "unusable_reasons": reasons,
        "empty_reason": m1_parse.LAST_EMPTY_REASON,
        "short_body": [{"page": p["page"], "text": p["text"][:60]} for p in short_body[:5]],
        "refs_leak": [{"page": p["page"], "text": p["text"][:60]} for p in refs_leak[:5]],
        "boiler": [{"page": p["page"], "text": p["text"][:60]} for p in boiler[:5]],
        "interleave": [{"page": p["page"], "text": p["text"][:120]} for p in interleave[:3]],
        "bad_tail": [{"page": p["page"], "text": p["text"][-60:]} for p in bad_tail[:5]],
        "huge": [{"page": p["page"], "chars": len(p["text"])} for p in merged_hard[:5]],
        "first": paras[0]["text"][:80] if paras else "",
        "last": paras[-1]["text"][-80:] if paras else "",
        "issues": issues,
    }


def _raw_text_chars(path):
    """PDF 文本层总字符数，用来算 keep_rate。解析失败就返回 0（不影响其它指标）。"""
    try:
        import pymupdf
        doc = pymupdf.open(path)
        n = sum(len(doc[i].get_text("text")) for i in range(doc.page_count))
        doc.close()
        return n
    except Exception:
        return 0


CSV_COLUMNS = ["file", "pages", "paras", "body", "caption", "heading",
               "usable_ratio", "keep_rate", "body_chars", "secs", "issues"]


def write_csv(rows, path):
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)
        for r in rows:
            k = r.get("kinds") or {}
            w.writerow([
                r.get("file", ""), r.get("pages", ""), r.get("paras", ""),
                k.get("body", 0), k.get("caption", 0), k.get("heading", 0),
                r.get("usable_ratio", ""), r.get("keep_rate", ""),
                r.get("body_chars", ""), r.get("secs", ""),
                "；".join(r.get("issues") or []) or "无",
            ])


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        epilog=USABLE_DOC, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--json", default=None, help="写出完整结果（含证据片段）")
    ap.add_argument("--csv", default=None, help="写出汇总表（一行一篇）")
    args = ap.parse_args()

    # Windows 的 cmd 不展开通配符，这里自己展开，方便 papers/*.pdf 这种写法
    paths = []
    for pat in args.pdfs:
        paths.extend(sorted(glob.glob(pat)) if any(c in pat for c in "*?[") else [pat])

    out = []
    for path in paths:
        try:
            r = audit_one(path)
        except Exception as e:                                    # 单篇崩了不影响其它篇
            r = {"file": os.path.basename(path), "error": "%s: %s" % (type(e).__name__, e), "issues": ["解析崩溃"]}
        out.append(r)
        print("=" * 70)
        print(r["file"], " 页数", r.get("pages"), " 段落", r.get("paras"), " 类型", r.get("kinds"))
        if r.get("error"):
            print("  !! ", r["error"])
            continue
        print("  正文", r["kinds"].get("body", 0), "段 /", r["body_chars"], "字符")
        print("  可用率 %s   留存率 %s   耗时 %ss" % (
            r["usable_ratio"], r["keep_rate"], r["secs"]))
        if r["unusable_reasons"]:
            print("  不可用原因:", "、".join("%s×%d" % kv for kv in
                                         sorted(r["unusable_reasons"].items(), key=lambda kv: -kv[1])))
        print("  首段:", r["first"])
        print("  末段:", r["last"])
        print("  问题:", "；".join(r["issues"]) if r["issues"] else "无")
        for key, label in (("refs_leak", "参考文献漏标"), ("boiler", "出版社样板"),
                           ("interleave", "交错"), ("short_body", "超短段"),
                           ("bad_tail", "段尾截断"), ("huge", "超长段")):
            for item in r.get(key) or []:
                print("    -", label, item)

    if args.json:
        d = os.path.dirname(os.path.abspath(args.json))
        if d:
            os.makedirs(d, exist_ok=True)
        with io.open(args.json, "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print("\n已写入", args.json)

    if args.csv:
        write_csv(out, args.csv)
        print("已写入", args.csv)


if __name__ == "__main__":
    main()
