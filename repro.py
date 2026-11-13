# -*- coding: utf-8 -*-
"""复现可行性体检（reproduction feasibility check）。

设计约束（写代码前定下的）：
- **不跑代码、不接 agent、不碰 Colab**。PaperBench 的最好成绩是人类博士的
  一半左右，而"结果对得上" 接近于 0 —— 一个高概率失败的"帮我复现"按钮会一
  次性烧掉整个产品赖以生存的可核查信用。
- 只回答四个问题：多大工作量 / 有没有官方代码 / 数据从哪来 / 哪几处会卡住。
- 每一条判断都必须钉在具体段落上（idx 由模型给，后端校验存在性，对不上就丢），
  复用第一跳的锚定纪律：宁可少贴，不可贴错。
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

import llm

REPRO_SYSTEM = (
    "你是帮学生判断「这篇论文值不值得动手复现」的研究助理。"
    "你只根据给定的论文正文做判断，不猜没写的东西；拿不准就写「论文未说明」。"
    "你只输出 JSON，不要 Markdown 代码围栏。"
)

REPRO_HINT = """请严格输出下面这个 JSON（字段一个都不能少）：

{
  "feasible": "高 | 中 | 低（三选一，指「两周内用一张消费级显卡能不能做出一个能看的小实验」）",
  "why": "一句理由，中文，不超过 40 字",
  "cost": "复现成本，中文，一句话，写清算力/数据量级/大致工期",
  "datasets": ["数据集或语料名称", "..."],
  "repo": "作者官方代码仓库 URL。正文里给了就照抄；正文没给但你知道官方实现在哪，也可以给（我们会去 GitHub 核对仓库是否存在）；完全不确定就给空字符串",
  "risks": [
    {"idx": 34, "text": "会卡住的地方，中文，不超过 30 字"}
  ],
  "start": {"idx": 56, "text": "最小可行起点：从哪一节哪个实验下手，中文，不超过 40 字"}
}

硬性要求：
- 所有 idx 必须是我给你的段落编号（方括号里的数字），不许编造；没把握的条目就不要写。
- risks 给 2 到 4 条，必须是**真的会卡住人**的东西：缺数据/数据已下架、算力要求、
  依赖或版本差异、评测口径变化、关键超参没写清、预处理没公开。不要写「实现有难度」这种废话。
- start 只给一条，必须指向**实验/训练配置类**段落（讲数据集、超参、训练时长、评测方式的那种）或某个实验小节的标题，不要指向模型结构、动机、相关工作。
- datasets 最多 5 条，正文没写清楚就给空数组。
- 全部中文，数据集名称保留英文原文。"""

REPO_RE = re.compile(r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.I)


def _s(v, limit):
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


LINK_FIX = (
    (re.compile(r"https?\s*:\s*/\s*/\s*", re.I), "https://"),
    (re.compile(r"github\s*\.\s*com\s*/\s*", re.I), "github.com/"),
)


def repair_links(text):
    """修「URL 被换行拆开」的常见损坏：`https://github. com/x` / `https:// github.com/x`。

    PDF 的文本层常把跨行处变成空格（我们拼行时也只在连字符处去空格），
    不修的话正则捞不到仓库地址，复现体检就丢掉了最关键的一条证据。
    """
    out = text
    for pat, rep in LINK_FIX:
        out = pat.sub(rep, out)
    return out


def find_repos(parsed):
    """从解析出的正文里捞 GitHub 仓库地址（按出现次数排序，去重）。"""
    seen = {}
    for p in parsed["paras"]:
        for m in REPO_RE.finditer(repair_links(p.get("text") or "")):
            owner, name = m.group(1), m.group(2)
            name = name.rstrip(".")
            if name.lower().endswith((".git",)):
                name = name[:-4]
            if not name or name.lower() in ("blob", "tree", "issues", "releases"):
                continue
            key = "%s/%s" % (owner, name)
            seen[key] = seen.get(key, 0) + 1
    return [k for k, _ in sorted(seen.items(), key=lambda kv: -kv[1])]


def github_info(full_name, timeout=8):
    """查仓库状态：星数、最近提交、是否归档、是否有 requirements。失败返回 None。"""
    url = "https://api.github.com/repos/%s" % full_name
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "PaperPrism-repro/0.1",
    })
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        req.add_header("Authorization", "Bearer %s" % token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    return {
        "full_name": d.get("full_name"),
        "url": d.get("html_url"),
        "stars": d.get("stargazers_count"),
        "pushed_at": (d.get("pushed_at") or "")[:10],
        "archived": bool(d.get("archived")),
        "open_issues": d.get("open_issues_count"),
        "license": (d.get("license") or {}).get("spdx_id"),
        "description": _s(d.get("description"), 120),
    }


def _context(parsed, budget=32000):
    """给体检用的上下文：标题 + 小节标题 + 正文（段落较长时截短）。"""
    out = []
    used = 0
    title = parsed.get("title") or ""
    if title:
        out.append("论文标题：%s" % title)
        used += len(title)
    for p in parsed["paras"]:
        i = llm.pidx(p)
        kind = p.get("kind")
        text = p.get("text") or ""
        if kind == "heading":
            line = "\n## [#%d] %s" % (i, _s(text, 120))
        elif kind == "caption":
            line = "[#%d] (图注) %s" % (i, _s(text, 160))
        else:
            line = "[#%d] %s" % (i, _s(text, 520))
        if used + len(line) > budget:
            break
        out.append(line)
        used += len(line)
    return "\n".join(out)


def _resolve(obj, by_idx, text_key):
    """把 {idx, text} 钉到真实段落上；idx 不存在就整条丢弃。"""
    if not isinstance(obj, dict):
        return None
    try:
        idx = int(obj.get("idx"))
    except Exception:
        return None
    para = by_idx.get(idx)
    if not para:
        return None
    txt = _s(obj.get(text_key), 120)
    if not txt:
        return None
    return {"idx": idx, "text": txt, "anchor": para.get("anchor")}


def validate(card, parsed):
    paras = parsed["paras"]
    by_idx = {llm.pidx(p): p for p in paras}

    feasible = _s(card.get("feasible"), 4)
    if feasible not in ("高", "中", "低"):
        feasible = "中"

    datasets = [_s(x, 60) for x in (card.get("datasets") or []) if _s(x, 60)][:5]

    risks = []
    for r in (card.get("risks") or []):
        item = _resolve(r, by_idx, "text")
        if item:
            risks.append(item)
    risks = risks[:4]

    start = _resolve(card.get("start"), by_idx, "text")

    repo_url = _s(card.get("repo"), 200)
    if repo_url and not REPO_RE.search(repo_url):
        repo_url = ""

    return {
        "feasible": feasible,
        "why": _s(card.get("why"), 60),
        "cost": _s(card.get("cost"), 120),
        "datasets": datasets,
        "risks": risks,
        "start": start,
        "repo_hint": repo_url,
    }


def _repo_evidence(parsed, repo_hint):
    """官方代码：优先用正文里的 GitHub 链接，其次用模型给的仓库地址。"""
    candidates = []
    if repo_hint:
        m = REPO_RE.search(repo_hint)
        if m:
            candidates.append("%s/%s" % (m.group(1), m.group(2)))
    for full in find_repos(parsed):
        if full not in candidates:
            candidates.append(full)
    checked = []
    for full in candidates[:3]:            # 最多查三个，别拖慢
        info = github_info(full)
        checked.append(full)
        if info:
            info["checked"] = checked
            return info
    return {"full_name": candidates[0] if candidates else "", "url": "", "stars": None,
            "pushed_at": "", "archived": False, "open_issues": None, "license": None}


def repro_check(parsed, timeout=150):
    """一次模型调用 + 一次 GitHub 查询。返回 (card, meta)。"""
    t0 = time.time()
    user = "%s\n\n请判断这篇论文的复现可行性：\n\n%s" % (_context(parsed), REPRO_HINT)
    msg = [{"role": "system", "content": REPRO_SYSTEM}, {"role": "user", "content": user}]
    try:
        raw, usage = llm.chat_json(msg, temperature=0.0, max_tokens=1400, timeout=timeout)
    except Exception:
        raw, usage = llm.chat_json(msg, temperature=0.0, max_tokens=1400, timeout=timeout)

    card = validate(raw if isinstance(raw, dict) else {}, parsed)
    card["repo"] = _repo_evidence(parsed, card.pop("repo_hint", ""))
    meta = {
        "ms": int((time.time() - t0) * 1000),
        "usage": usage or {},
    }
    return card, meta


if __name__ == "__main__":      # 手工试跑：python repro.py papers/xxx.pdf
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "pymupdf_pkg"))
    import m1_parse

    path = sys.argv[1] if len(sys.argv) > 1 else "papers/bert_1810.04805.pdf"
    paras = m1_parse.parse_pdf(path)
    parsed = {
        "file": os.path.basename(path),
        "title": next((p["text"] for p in paras if p.get("kind") == "title"), ""),
        "paras": [dict(p, i=n, anchor={"idx": n, "head": " ".join(p["text"].split()[:8])})
                  for n, p in enumerate(paras)],
    }
    card, meta = repro_check(parsed)
    print(json.dumps(card, ensure_ascii=False, indent=2))
    print("ms=%s tokens=%s" % (meta["ms"], meta.get("usage")))
