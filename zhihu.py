# -*- coding: utf-8 -*-
"""知乎讨论卡：把这篇论文里的概念，拿到知乎上搜一遍。

为什么要有这一块：
- 论文是写给同行看的，术语一出，新手就卡住；知乎上往往已经有人用「人话」讨论过同一个概念。
- 所以这里不生成任何新内容，只做「把已有讨论找出来 + 说清楚它跟本文哪一段有关」。

三条硬规则（比赛手册明确要求）：
1. 失败 / 额度耗尽 / 搜不到 都必须在界面上说出来，不许静默失败；
2. 每次搜索都花额度（知乎搜索 5000 次/天），所以结果按论文缓存进本地书库，重开不再调；
3. 搜索词只从本文自己的术语里挑（优先「本文自创概念」），不猜、不扩写。

契约见 zhihu/references/http-api.md：
    GET https://developer.zhihu.com/api/v1/content/zhihu_search?Query=..&Count=..
    Authorization: Bearer <Access Secret> / X-Request-Timestamp: 秒级时间戳
    响应 {Code, Message, Data:{HasMore, Items:[{Title, ContentType, ContentText, Url, VoteUpCount, ...}]}}
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import llm  # 借用它的 _load_dotenv()，这样 .env 只在一个地方读

ENDPOINT = "https://developer.zhihu.com/api/v1/content/zhihu_search"
SEARCH_PAGE = "https://www.zhihu.com/search?type=content&q="

MAX_QUERIES = 3          # 一篇最多搜 3 个词（1 词 = 1 次额度）
PER_QUERY = 3            # 每个词最多展示 3 条
COUNT = 5                # 每次向知乎要 5 条，再自己筛

# 知乎错误码 -> 我们能给人看的话
CODE_MSG = {
    10001: ("error", "知乎说请求参数不对（10001）"),
    20001: ("auth", "知乎鉴权失败（20001）：Access Secret 不对或已过期"),
    30001: ("quota", "知乎额度/频率受限（30001）：今天的搜索额度用完了"),
    90001: ("error", "知乎内部错误（90001），过一会儿再试"),
}

EMPTY_MSG = {
    "nokey": "没配置知乎能力：.env 里没有 ZHIHU_ACCESS_SECRET",
    "auth": "知乎鉴权失败：Access Secret 不对或已过期（去 developer.zhihu.com 个人中心看一眼）",
    "quota": "知乎今天的搜索额度用完了（5000 次/天），明天再来",
    "net": "连不上知乎（网络或代理问题）",
    "error": "知乎接口报错",
    "empty": "知乎上没有搜到和这些概念相关的讨论",
    "nocontent": "还没有摘要和批注，挑不出要搜的概念",
}


# ------------------------------------------------------------------ 环境

def has_secret():
    llm._load_dotenv()
    return bool(os.environ.get("ZHIHU_ACCESS_SECRET", "").strip())


def manual_url(q):
    return SEARCH_PAGE + urllib.parse.quote(q or "")


# ------------------------------------------------------------------ HTTP

def search(query, count=COUNT, timeout=20):
    """调一次知乎搜索。返回 (items, err)。

    err 是 None 或 (kind, message, http_code)，kind 取值 nokey/auth/quota/net/error。
    绝不抛异常：网络这类失败必须变成卡片上的一行字，而不是把整个请求打挂。
    """
    if not has_secret():
        return [], ("nokey", EMPTY_MSG["nokey"], None)
    secret = os.environ["ZHIHU_ACCESS_SECRET"].strip()
    qs = urllib.parse.urlencode({"Query": query, "Count": str(count)})
    req = urllib.request.Request(
        ENDPOINT + "?" + qs,
        headers={
            "Authorization": "Bearer " + secret,
            "X-Request-Timestamp": str(int(time.time())),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            pass
        msg = None
        try:
            msg = json.loads(body).get("Message")
        except Exception:
            pass
        if exc.code in (401, 403):
            return [], ("auth", EMPTY_MSG["auth"], exc.code)
        if exc.code == 429:
            return [], ("quota", EMPTY_MSG["quota"], exc.code)
        return [], ("net", "知乎返回 HTTP %s%s" % (exc.code, ("：" + msg) if msg else ""), exc.code)
    except Exception as exc:                      # URLError / timeout / 连接被重置
        return [], ("net", "%s（%s）" % (EMPTY_MSG["net"], exc), None)

    try:
        data = json.loads(body)
    except Exception:
        return [], ("error", "知乎返回的不是 JSON：%s" % body[:120], None)

    code = data.get("Code")
    if code != 0:
        kind, text = CODE_MSG.get(code, ("error", "知乎报错 %s：%s" % (code, data.get("Message"))))
        return [], (kind, text, code)

    items = ((data.get("Data") or {}).get("Items")) or []
    return [_slim(it) for it in items if isinstance(it, dict)], None


_TAG = re.compile(r"<[^>]+>")


def _slim(it):
    """把知乎的 17 个字段压成界面要用的 6 个：多余字段不往书库里存。"""
    text = _TAG.sub("", it.get("ContentText") or "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 110:
        text = text[:110] + "…"
    return {
        "title": (it.get("Title") or "").strip(),
        "type": it.get("ContentType") or "",
        "url": it.get("Url") or "",
        "vote": it.get("VoteUpCount"),
        "comment": it.get("CommentCount"),
        "author": it.get("AuthorName") or "",
        "snippet": text,
        "auth": it.get("AuthorityLevel") or "",
    }


# ------------------------------------------------------------------ 相关度

def _vocab(bundle):
    """这篇论文自己的词表（中英都收）：用来判断一条知乎结果到底跟本文有没有关系。

    为什么必须做这一步：知乎搜索是关键词匹配，搜「补偿行为」会把心理学回答全带回来，
    搜「自建模」会带回来 Maya 建模教程 —— 直接展示给评委看就是事故。
    """
    toks = set()
    summary = bundle.get("summary") or {}
    for g in (summary.get("glossary") or []):
        if isinstance(g, dict):
            for k in ("term", "zh"):
                t = (g.get(k) or "").strip()
                if len(t) >= 2:
                    toks.add(t)
    for a in (bundle.get("annots") or {}).values():
        if not isinstance(a, dict):
            continue
        for t in (a.get("terms") or []):
            if isinstance(t, dict):
                for k in ("t", "zh"):
                    v = (t.get(k) or "").strip()
                    if len(v) >= 2:
                        toks.add(v)
    return [t for t in toks if len(t) >= 2]


def _score(item, vocab, q):
    """一条结果命中几个「本文术语」（重叠的搜索词本身不算）。命中越多越可能是同一件事。"""
    text = ((item.get("title") or "") + " " + (item.get("snippet") or "")).lower()
    ql = (q or "").lower()
    hits = 0
    for t in vocab:
        tl = t.lower()
        if tl and tl not in ql and tl in text:
            hits += 1
    return hits


# ------------------------------------------------------------------ 选词

GENERIC = {"集成", "冗余", "正则化", "损失函数", "随机梯度下降", "反向传播", "过拟合",
           "归一化", "梯度下降", "神经网络", "深度学习", "机器学习"}


def pick_queries(bundle):
    """从这篇的术语表 + 批注里挑最多 3 个词去知乎搜。

    先信 jump1 的术语表（那是专门挑的「读者最容易卡住的词」，而且干净），
    再补批注里的「本文自创概念」（这类词最能体现这篇的独特性）。
    用中文译名搜（知乎是中文社区，英文术语搜回来全是论文推销），没有中文才退回英文。
    「集成」「冗余」这种三字以内的通用词先让位给更具体的词，它们搜出去全是别的话题。
    """
    picks, seen = [], set()

    def add(term, zh, why):
        zh = (zh or "").strip()
        term = (term or "").strip()
        q = zh if len(zh) >= 2 else term
        if not q or q.lower() in seen or q in GENERIC:
            return
        seen.add(q.lower())
        picks.append({"q": q, "term": term or q, "zh": zh, "why": why})

    summary = bundle.get("summary") or {}
    for g in (summary.get("glossary") or []):
        if isinstance(g, dict):
            add(g.get("term"), g.get("zh"), "术语")

    for a in (bundle.get("annots") or {}).values():
        if not isinstance(a, dict) or not a.get("selfmade"):
            continue
        for t in (a.get("terms") or [])[:2]:
            if isinstance(t, dict):
                add(t.get("t"), t.get("zh"), "本文自创概念")

    # 术语表内部的先后顺序沿用模型给的（越靠前越关键），这里只把三字以上的词提前
    picks.sort(key=lambda p: 0 if len(p["zh"] or p["q"]) >= 3 else 1)
    return picks[:MAX_QUERIES]


# ------------------------------------------------------------------ 组装卡片

def build_card(bundle, refresh=False):
    """返回 (card, is_cached)。card 直接给前端渲染，也原样存进书库。"""
    cached = bundle.get("zhihu")
    if cached and cached.get("status") in ("ok", "empty") and not refresh:
        card = dict(cached)
        card["cached"] = True
        return card, True

    queries = pick_queries(bundle)
    if not queries:
        return {
            "status": "nocontent",
            "error": EMPTY_MSG["nocontent"],
            "ts": int(time.time()),
            "queries": [],
            "total": 0,
            "asked": 0,
        }, False

    if not has_secret():
        return {
            "status": "nokey",
            "error": EMPTY_MSG["nokey"],
            "ts": int(time.time()),
            "queries": [{"q": q["q"], "term": q["term"], "why": q["why"], "url": manual_url(q["q"]),
                         "items": [], "error": None} for q in queries],
            "total": 0,
            "asked": 0,
        }, False

    vocab = _vocab(bundle)
    out, seen_ids, kinds, weak = [], set(), [], []
    for q in queries:
        items, err = search(q["q"])
        scored = []
        for it in items:
            key = it.get("url") or it.get("title")
            if not it.get("title") or not it.get("url") or key in seen_ids:
                continue
            it["score"] = _score(it, vocab, q["q"])
            scored.append(it)
        strong = sorted([it for it in scored if it["score"] > 0], key=lambda x: -x["score"])
        kept = strong[:PER_QUERY]
        for it in kept:
            seen_ids.add(it.get("url") or it.get("title"))
        if not kept:
            weak.append(q["q"])
        e = None
        if err:
            kinds.append(err[0])
            e = err[1]
        out.append({"q": q["q"], "term": q["term"], "why": q["why"], "url": manual_url(q["q"]),
                    "items": kept, "error": e})

    total = sum(len(x["items"]) for x in out)
    if total:
        status, error = "ok", None
    else:
        # 全空：按「最需要人动手」的顺序报一个原因
        for k in ("auth", "quota", "net", "error", "nokey"):
            if k in kinds:
                status, error = k, EMPTY_MSG[k]
                break
        else:
            status, error = "empty", EMPTY_MSG["empty"]

    return {
        "status": status,
        "error": error,
        "ts": int(time.time()),
        "queries": out,
        "total": total,
        "asked": len(queries),
        "weak": weak,          # 搜到了东西但跟本文不是一个话题的词
    }, False


def quota_hint():
    """给 /api/health 用：一句话说清知乎这块现在能不能用。"""
    if not has_secret():
        return {"key_set": False, "note": ".env 里没有 ZHIHU_ACCESS_SECRET"}
    return {"key_set": True, "endpoint": ENDPOINT, "daily_quota": 5000}


if __name__ == "__main__":
    # 自测：python zhihu.py store/<sha12>.json
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        b = json.load(f)
    print("选词：", [q["q"] + "（" + q["why"] + "）" for q in pick_queries(b)])
    card, cached = build_card(b)
    print("状态：", card["status"], "| 条数:", card["total"], "| 缓存:", cached)
    for q in card["queries"]:
        print("\n[%s] %s" % (q["q"], q["why"]))
        if q.get("error"):
            print("   ! ", q["error"])
        for it in q["items"]:
            print("   -", it["type"], "|", it["title"][:50], "| 赞", it["vote"], "| 权威", it["auth"])
            print("     ", it["snippet"][:70])
