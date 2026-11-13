# -*- coding: utf-8 -*-
"""把 store/ 里的旧版本缓存升到当前 PARSE_VERSION，并把批注/笔记/追问/体检按文本重新对位。

PARSE_VERSION 8 -> 9 只改了两条切段规则（行尾脚注号、短半句并段），段号会小幅漂移
（NBER 204->209、bert 143->146），直接沿用旧段号会让批注挂错段。这个脚本：
  1. 用新解析器重解析每篇 PDF；
  2. 用「旧段落文本 vs 新段落文本」的公共前缀/包含关系把旧段号映射到新段号；
  3. 重写 parse（parse_version=9）并同步 annots / notes / asks / repro 里的 idx。

用法：
    python .tmp/migrate_v9.py --dry-run     # 只看映射，不写盘
    python .tmp/migrate_v9.py               # 真写（先备份 store/ 到 .tmp/store_backup_v8/）
"""
import io
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vendor", "pymupdf_pkg"))

import m1_parse  # noqa: E402
import store  # noqa: E402

DRY = "--dry-run" in sys.argv
STORE_DIR = os.path.join(ROOT, "store")
BACKUP_DIR = os.path.join(ROOT, ".tmp", "store_backup_v8")


def norm(s):
    return " ".join((s or "").split()).lower()


def build_parse(full):
    """和 server.parse_request 同一份结构。"""
    paras = m1_parse.parse_pdf(full)
    out = []
    for i, p in enumerate(paras):
        words = (p["text"] or "").split()
        out.append({
            "i": i,
            "page": p["page"],
            "col": p.get("col", "full"),
            "kind": p["kind"],
            "chars": len(p["text"]),
            "rects": p.get("rects", []),
            "text": p["text"],
            "anchor": {"idx": i, "head": " ".join(words[:8])},
        })
    return {
        "pages": max((p["page"] for p in out), default=0),
        "count": len(out),
        "parse_version": m1_parse.PARSE_VERSION,
        "page_sizes": m1_parse.LAST_PAGE_SIZES,
        "paras": out,
    }


def remap_idx(old_paras, new_paras, oi, hint=None):
    """旧段号 -> 新段号：先比文本公共前缀，再退化到包含 + 长度接近。"""
    if oi is None or not (0 <= oi < len(old_paras)):
        return oi
    old = norm(old_paras[oi]["text"])
    head = old[:70]
    if not head:
        return min(oi, len(new_paras) - 1)
    cands = []
    for ni, p in enumerate(new_paras):
        t = norm(p["text"])
        if not t:
            continue
        if t.startswith(head[:50]):
            cands.append((2, -abs(len(t) - len(old)), ni))
        elif head[:50] in t:
            cands.append((1, -abs(len(t) - len(old)), ni))
    if cands:
        cands.sort(reverse=True)
        return cands[0][2]
    # 兜底：公共前缀最长的那个
    best, bestn = -1, 0
    for ni, p in enumerate(new_paras):
        t = norm(p["text"])
        n = 0
        for a, b in zip(head, t):
            if a != b:
                break
            n += 1
        if n > bestn:
            best, bestn = ni, n
    return best if bestn >= 10 else min(oi, len(new_paras) - 1)


def migrate_file(path):
    with io.open(path, encoding="utf-8") as f:
        data = json.load(f)
    parse = data.get("parse") or {}
    ver = parse.get("parse_version")
    rel = data.get("path") or ""
    full = os.path.join(ROOT, rel)
    print("== %s  版本 %s -> %s  文件 %s" % (
        os.path.basename(path), ver, m1_parse.PARSE_VERSION, rel))
    if ver == m1_parse.PARSE_VERSION:
        print("   已是当前版本，跳过")
        return False
    if not os.path.exists(full):
        print("   !! PDF 不存在：%s，跳过" % full)
        return False

    new_parse = build_parse(full)
    old_paras = parse.get("paras") or []
    new_paras = new_parse["paras"]
    print("   段数 %d -> %d" % (len(old_paras), len(new_paras)))

    mapping = {}
    used = set()

    def remap(oi):
        if oi in mapping:
            return mapping[oi]
        ni = remap_idx(old_paras, new_paras, oi)
        mapping[oi] = ni
        if ni != oi:
            print("   idx %3d -> %3d  %s" % (oi, ni, norm(old_paras[oi]["text"])[:50]))
        used.add(ni)
        return ni

    annots = data.get("annots") or {}
    new_annots = {}
    for k, a in annots.items():
        a = dict(a)
        oi = a.get("idx", int(k) if str(k).isdigit() else None)
        ni = remap(oi)
        a["idx"] = ni
        if isinstance(a.get("anchor"), dict):
            a["anchor"] = dict(a["anchor"])
            a["anchor"]["idx"] = ni
        new_annots[str(ni)] = a
    data["annots"] = new_annots

    for key in ("notes", "asks"):
        for item in data.get(key) or []:
            if isinstance(item, dict) and item.get("idx") is not None:
                item["idx"] = remap(item["idx"])

    card = ((data.get("repro") or {}).get("card") or {})
    for risk in card.get("risks") or []:
        if risk.get("idx") is not None:
            risk["idx"] = remap(risk["idx"])
        if isinstance(risk.get("anchor"), dict):
            risk["anchor"]["idx"] = risk["idx"]

    data["parse"] = new_parse
    print("   批注 %d 条 / 笔记 %d / 追问 %d / 体检风险 %d" % (
        len(new_annots), len(data.get("notes") or []),
        len(data.get("asks") or []), len(card.get("risks") or [])))
    if DRY:
        return True
    store.save(data["sha"], data)
    return True


def repair_by_anchor(path):
    """已升级但批注段号还是旧的：用 anchor.head（旧段前 8 个词）在新段落里重新找位置。"""
    with io.open(path, encoding="utf-8") as f:
        data = json.load(f)
    paras = (data.get("parse") or {}).get("paras") or []
    if not paras:
        return 0
    heads = [(i, norm(p["text"])[:120]) for i, p in enumerate(paras)]

    def find(head):
        h = norm(head)
        if not h:
            return None
        frag = h[:50]
        for i, t in heads:
            if t.startswith(frag):
                return i
        for i, t in heads:
            if frag in t:
                return i
        return None

    fixed = 0
    new_annots = {}
    for k, a in (data.get("annots") or {}).items():
        a = dict(a)
        cur = a.get("idx")
        head = (a.get("anchor") or {}).get("head")
        hit = find(head) if head else None
        if hit is not None and hit != cur:
            a["idx"] = hit
            if isinstance(a.get("anchor"), dict):
                a["anchor"] = dict(a["anchor"])
                a["anchor"]["idx"] = hit
            fixed += 1
        new_annots[str(a.get("idx"))] = a
    data["annots"] = new_annots

    for key in ("notes", "asks"):
        for item in data.get(key) or []:
            if not isinstance(item, dict):
                continue
            # 笔记/追问没有 anchor.head，用旧段文本前缀兜底不了，保持原样
    print("== %s 按 anchor.head 重对位：%d 条批注段号变化" % (
        os.path.basename(path), fixed))
    if not DRY:
        store.save(data["sha"], data)
    return fixed


def main():
    files = sorted(f for f in os.listdir(STORE_DIR) if f.endswith(".json"))
    todo = []
    for f in files:
        p = os.path.join(STORE_DIR, f)
        with io.open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        if ((d.get("parse") or {}).get("parse_version")) != m1_parse.PARSE_VERSION:
            todo.append(p)
    print("需要升级 %d / %d 篇%s" % (len(todo), len(files), "（dry-run）" if DRY else ""))
    if not DRY and todo:
        if os.path.isdir(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)
        shutil.copytree(STORE_DIR, BACKUP_DIR)
        print("已备份 store/ -> %s" % BACKUP_DIR)
    n = 0
    for p in todo:
        if migrate_file(p):
            n += 1
    print("完成：升级 %d 篇" % n)


if __name__ == "__main__":
    if "--repair-anchors" in sys.argv:
        for f in sorted(os.listdir(STORE_DIR)):
            if f.endswith(".json"):
                repair_by_anchor(os.path.join(STORE_DIR, f))
    else:
        main()
