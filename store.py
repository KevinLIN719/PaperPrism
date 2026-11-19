# -*- coding: utf-8 -*-
"""本地书库：把「解析 + 摘要 + 逐段批注 + 复现体检 + 用户批注 + 追问记录」落盘。

为什么按文件内容哈希做索引，而不是按路径：
- 同一篇论文可能被拷来拷去、改了名字、从 papers/ 拖进 papers/imported/；
- 按内容哈希的话，换个名字打开还是命中同一份缓存，用户不会莫名其妙重跑一遍。

一个文件 = 一篇论文，`store/<sha12>.json`：

    {
      "sha": ..., "file": 原始文件名, "path": 最近一次打开时的路径, "size": 字节数,
      "updated": 时间戳,
      "parse":   {count, pages, page_sizes, paras},      # 解析结果，命中就不用再解析
      "summary": {...}, "summary_meta": {...},           # 跳 1
      "annots":  {段序号: 批注},                          # 跳 2
      "repro":   {card, meta},                           # 复现体检
      "zhihu":   {status, queries, total, ts},            # 知乎讨论（站内搜索 API 的结果缓存）
      "notes":   [{id, idx, text, ts}],                  # 用户自己写的批注
      "asks":    [{id, q, a, used, ts}]                  # 追问记录
    }
"""
import hashlib
import json
import os
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
STORE_DIR = os.path.join(ROOT, "store")
_REMOVED_RECORDS = set()


def allow_updates(sha):
    _REMOVED_RECORDS.discard(sha)


def _ensure_dir():
    if not os.path.isdir(STORE_DIR):
        os.makedirs(STORE_DIR, exist_ok=True)


def sha_of(path, chunk=1 << 20):
    """整份文件的内容哈希（分块读，100MB 的 PDF 也不会一次读进内存）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def store_path(sha):
    return os.path.join(STORE_DIR, "%s.json" % sha[:12])


def load(sha):
    p = store_path(sha)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("sha") != sha:
        return None
    return data


def save(sha, data):
    if sha in _REMOVED_RECORDS:
        raise ValueError('论文记录已删除，本次后台结果不再保存')
    _ensure_dir()
    data = dict(data)
    data["sha"] = sha
    data["updated"] = int(time.time())
    p = store_path(sha)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, p)
    return data


def delete(sha, block_updates=False):
    """删掉一篇论文的本地记录（「重新生成」用：改了解析器/提示词之后要重跑）。"""
    p = store_path(sha)
    if block_updates:
        _REMOVED_RECORDS.add(sha)
    if os.path.isfile(p):
        os.remove(p)
        return True
    return False


def merge(sha, patch, path=None):
    """增量写入：解析 / 摘要 / 批注 / 体检 / 笔记 / 追问分批到达，每次都并进同一个文件。"""
    bookmark = patch.get('reading_bookmark')
    if isinstance(bookmark, dict) and 'bookmarks' in bookmark:
        marks = bookmark['bookmarks']
        if not isinstance(marks, list):
            raise ValueError('书签格式不正确')
        counts = {}
        for mark in marks:
            if not isinstance(mark, dict) or type(mark.get('page')) is not int or mark['page'] < 1:
                raise ValueError('书签页码不正确')
            page = mark['page']
            counts[page] = counts.get(page, 0) + 1
            if counts[page] > 3:
                raise ValueError('每页最多添加三个书签')
    data = load(sha) or {"sha": sha, "notes": [], "asks": [], "annots": {}}
    for k in ("parse", "summary", "summary_meta", "repro", "zhihu", "usage", "file", "size", "reading_goal", "reading_discipline", "reading_bookmark", "repro_resources"):
        if k in patch and patch[k] is not None:
            data[k] = patch[k]
    if path:
        data["path"] = path

    if "annots" in patch:
        cur = data.get("annots") or {}
        incoming = patch["annots"] or {}
        if isinstance(incoming, dict):
            for k, v in incoming.items():
                cur[str(k)] = v
        elif isinstance(incoming, list):
            for v in incoming:
                if isinstance(v, dict) and v.get("idx") is not None:
                    cur[str(v["idx"])] = v
        data["annots"] = cur

    if "ask_review" in patch:
        item=patch["ask_review"]
        data.setdefault("ask_reviews",{})[item["id"]]=item

    if "claim_review" in patch:
        item = patch["claim_review"]
        data.setdefault("claim_reviews", {})[item["id"]] = item
    if "paragraph_explanation" in patch:
        item = patch['paragraph_explanation']
        data.setdefault('paragraph_explanations',{})[item['id']] = item

    if "comparison_summary" in patch:
        entry = patch["comparison_summary"]
        data.setdefault("comparison_summaries", {})[entry["key"]] = entry["result"]
    if "repro_profile" in patch:
        entry = patch["repro_profile"]
        data.setdefault("repro_profiles", {})[entry["key"]] = entry["result"]

    if "figure_record" in patch:
        record = patch["figure_record"]
        # 仅由图表解读接口构造，不保存截图或 base64。
        if isinstance(record, dict) and record.get("id"):
            records = data.setdefault("figures", [])
            records[:] = [r for r in records if r.get("id") != record["id"]]
            records.append(record)

    if "note" in patch and isinstance(patch["note"], dict):
        notes = data.setdefault("notes", [])
        if patch["note"].get("text"):
            notes.append(patch["note"])

    if "del_note" in patch:
        nid = patch["del_note"]
        data["notes"] = [n for n in data.get("notes", []) if n.get("id") != nid]

    if "ask" in patch and isinstance(patch["ask"], dict):
        data.setdefault("asks", []).append(patch["ask"])

    if "del_figure" in patch:
        data["figures"] = [r for r in data.get("figures", []) if r.get("id") != patch["del_figure"]]
    if "del_ask" in patch:
        data["asks"] = [r for r in data.get("asks", []) if r.get("id") != patch["del_ask"]]
        data["ask_reviews"] = {k:r for k,r in data.get("ask_reviews",{}).items() if r.get("ask_id") != patch["del_ask"]}

    return save(sha, data)


def library():
    """书库索引：有本地记录的论文（按最近更新排序）。"""
    _ensure_dir()
    rows = []
    for name in os.listdir(STORE_DIR):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(STORE_DIR, name), "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        parse = d.get("parse") or {}
        summary = d.get("summary") or {}
        rows.append({
            "sha": d.get("sha"),
            "file": d.get("file"),
            "path": d.get("path"),
            "updated": d.get("updated"),
            "paras": parse.get("count"),
            "pages": parse.get("pages"),
            "worth": summary.get("worth_reading"),
            "claims": len(summary.get("claims") or []),
            "terms": len(summary.get("glossary") or []),
            "annots": len(d.get("annots") or {}),
            "notes": len(d.get("notes") or []),
            "asks": len(d.get("asks") or []),
            "has_repro": bool(d.get("repro")),
        })
    rows.sort(key=lambda r: r.get("updated") or 0, reverse=True)
    return rows
