"""PaperPrism 的模型调用层：只做一件事——把「段落列表」变成第一跳的结构化摘要。

设计原则（对应 _relay/brief.md 的「设计修订 v1.1」）：
  1. 不绑死厂商：走 OpenAI 兼容的 /chat/completions，地址、模型、key 全部用环境变量配。
     - LLM_BASE_URL   默认 https://api.deepseek.com/v1
     - LLM_MODEL      默认 deepseek-chat
     - LLM_API_KEY    优先读它；没有就读 DEEPSEEK_API_KEY（再没有就报错）
  2. 强约束输出：response_format=json_object + 提示词里贴 schema + 回来后自己校验一遍。
     校验不通过就重试一次（第 2 次温度调低），还不行就抛错，让前端降级。
  3. 批注锚点由我们自己定：模型只需要指认「第几段」，锚点里的「首 8 词」我们从解析结果里取。
     这样模型编不出锚点，对不上就丢批注。

只依赖标准库（本机 pip 装不了东西，见 memory 里的环境事实）。
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"

# 用户在界面上改的配置落在项目根目录的 settings.json（不进 git，见 .gitignore）。
# 优先级：settings.json > .env / 环境变量 > 默认值。
SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
_SETTINGS = None

WORTH = ("值得精读", "扫结论即可", "与你不相关")
STRENGTH = ("强", "中", "弱")

# ---------------------------------------------------------------- 成本估算
# 牌价来源：https://api-docs.deepseek.com/quick_start/pricing（2026-11-14 抓取）。
# 单位：美元 / 1M tokens。本项目的 LLM_MODEL 是旧模型名 deepseek-chat，现由 Flash 承接，
# 所以按 Flash 牌价估算；以后换模型只改这张表，别在别处硬编码价格。
PRICES = {
    "flash": {"peak": {"hit": 0.006, "miss": 0.30, "out": 1.20},
              "offpeak": {"hit": 0.003, "miss": 0.15, "out": 0.60}},
}

# 模型名 → PRICES 里的档位。没有牌价的模型（换厂商、自带模型）返回 None，
# 前端显示「未估算」，绝不拿别人的价格瞎算。
PRICE_BY_MODEL = {
    "deepseek-chat": "flash",
    "deepseek-flash": "flash",
}


def price_key(model):
    return PRICE_BY_MODEL.get((model or "").strip().lower())


def is_peak(ts=None):
    """官网口径：UTC 周一至周五 01:00-04:00、06:00-10:00 为峰时，其余（含周末）低谷。"""
    t = time.gmtime(time.time() if ts is None else ts)
    if t.tm_wday >= 5:
        return False
    return 1 <= t.tm_hour < 4 or 6 <= t.tm_hour < 10


def merge_usage(total, usage):
    """把多次调用的 usage 累加成一个（成本要按总量算，不能每次各自四舍五入）。"""
    out = dict(total or {})
    for k in ("prompt_tokens", "completion_tokens", "total_tokens",
              "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
        out[k] = int(out.get(k) or 0) + int((usage or {}).get(k) or 0)
    return out


def cost_usd(usage, model=None, ts=None):
    """按牌价算一次（或累计）调用的美元成本。缓存命中与未命中分开计价。
    没有牌价的模型返回 None（前端显示「未估算」），不要拿别的模型的价格硬算。"""
    pk = price_key(model or config()["model"])
    if not pk:
        return None
    u = usage or {}
    hit = int(u.get("prompt_cache_hit_tokens") or 0)
    miss = int(u.get("prompt_cache_miss_tokens") or 0)
    if not (hit or miss):
        miss = int(u.get("prompt_tokens") or 0)
    out = int(u.get("completion_tokens") or 0)
    p = PRICES[pk]["peak" if is_peak(ts) else "offpeak"]
    return round((hit * p["hit"] + miss * p["miss"] + out * p["out"]) / 1000000.0, 6)


def usage_info(usage, model=None, ts=None):
    """给前端用的「用量 + 成本」摘要（页脚要显示 tokens / 成本每篇）。"""
    u = usage or {}
    return {
        "model": model or config()["model"],
        "prompt_tokens": int(u.get("prompt_tokens") or 0),
        "completion_tokens": int(u.get("completion_tokens") or 0),
        "cache_hit_tokens": int(u.get("prompt_cache_hit_tokens") or 0),
        "cache_miss_tokens": int(u.get("prompt_cache_miss_tokens") or 0),
        "tokens": int(u.get("total_tokens") or 0),
        "cost_usd": cost_usd(u, model, ts),
        "peak": is_peak(ts),
    }


def _load_dotenv():
    """读项目根目录的 .env（KEY=VALUE 一行一个），环境变量优先。
    本机沙箱里 pip 装不了 python-dotenv，这里自己写 20 行。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(path):
        return
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and v and k not in os.environ:
                os.environ[k] = v
    except OSError:
        pass


def _settings():
    """读 settings.json（界面里存的那份）。坏文件就当没有，不能让配置坏了开不了机。"""
    global _SETTINGS
    if _SETTINGS is None:
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                _SETTINGS = json.load(f) or {}
        except (OSError, ValueError):
            _SETTINGS = {}
    return _SETTINGS


def save_settings(patch):
    """合并保存（只认 base/model/key 三个键，且空字符串=删掉这项、回退到 .env）。"""
    global _SETTINGS
    cur = dict(_settings())
    for k in ("base", "model", "key"):
        if k in patch:
            v = str(patch.get(k) or "").strip()
            if k == "base" and v:            # 有人会把整条 URL 粘进来，这里顺手清掉尾巴
                v = v.rstrip("/")
                for tail in ("/chat/completions", "/completions"):
                    if v.endswith(tail):
                        v = v[: -len(tail)].rstrip("/")
            if v:
                cur[k] = v
            else:
                cur.pop(k, None)
    _SETTINGS = cur
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SETTINGS_PATH)
    return cur


def mask_key(k):
    k = k or ""
    if len(k) <= 10:
        return "***" if k else ""
    return k[:6] + "…" + k[-4:]


def settings_info():
    """给设置面板用的现状：当前生效值 + 来源（settings / env / default）+ 打码的 key。"""
    s = _settings()
    cfg = config()
    _load_dotenv()
    env_key = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""

    def src(field, envname):
        if s.get(field):
            return "settings"
        return "env" if os.environ.get(envname) else "default"

    return {
        "base": cfg["base"],
        "model": cfg["model"],
        "key_set": bool(cfg["key"]),
        "key_masked": mask_key(cfg["key"]),
        "base_source": src("base", "LLM_BASE_URL"),
        "model_source": src("model", "LLM_MODEL"),
        "key_source": "settings" if s.get("key") else ("env" if env_key else "default"),
        "priced": bool(price_key(cfg["model"])),
        "settings_path": SETTINGS_PATH,
    }


def config():
    _load_dotenv()
    s = _settings()
    key = s.get("key") or os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""
    return {
        "base": (s.get("base") or os.environ.get("LLM_BASE_URL") or DEFAULT_BASE).rstrip("/"),
        "key": key,
        "model": s.get("model") or os.environ.get("LLM_MODEL") or DEFAULT_MODEL,
    }


def has_key():
    return bool(config()["key"])


def test_connection():
    """设置面板的「测试连接」：发一个 1 token 的小请求，确认 base/model/key 能用。
    不花正经额度（几十个 token），失败把可读原因回给前端。"""
    t0 = time.time()
    try:
        text, usage = chat([{"role": "user", "content": "ping，只回一个字：pong"}],
                           temperature=0, max_tokens=8, timeout=30, json_mode=False)
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc), "ms": int((time.time() - t0) * 1000)}
    cfg = config()
    return {
        "ok": True,
        "ms": int((time.time() - t0) * 1000),
        "model": cfg["model"],
        "base": cfg["base"],
        "reply": (text or "").strip()[:40],
        "usage": usage_info(usage, cfg["model"]),
    }


# ---------------------------------------------------------------- HTTP


def chat(messages, temperature=0.3, max_tokens=2400, timeout=120, json_mode=True):
    """调一次 /chat/completions，返回 (文本, 用量 dict)。失败抛 RuntimeError（带可读原因）。"""
    cfg = config()
    if not cfg["key"]:
        raise RuntimeError(
            r"没有配置 API key：点右上角「设置」填进去（或写 .env 的一行 "
            "DEEPSEEK_API_KEY=sk-...）"
        )
    body = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    req = urllib.request.Request(
        cfg["base"] + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + cfg["key"],
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise RuntimeError("模型接口返回 HTTP %s：%s" % (exc.code, detail))
    except urllib.error.URLError as exc:
        raise RuntimeError("连不上模型接口（%s）：%s" % (cfg["base"], exc.reason))

    try:
        data = json.loads(raw)
        text = data["choices"][0]["message"]["content"]
    except Exception:
        raise RuntimeError("模型返回的结构不认识：%s" % raw[:400])
    usage = data.get("usage") or {}
    return text, usage


def chat_json(messages, temperature=0.3, max_tokens=2400, timeout=120):
    """要 JSON：剥掉 ```json 围栏再解析；解析不了抛 ValueError（好让上层重试）。"""
    text, usage = chat(messages, temperature=temperature, max_tokens=max_tokens, timeout=timeout)
    return parse_json_loose(text), usage


def _salvage_json(s):
    """输出被截断时救回来：砍掉最后不完整的元素，再补上没闭合的括号。"""
    try:
        tail = s[s.find("{"):]
    except Exception:
        return None
    if not tail:
        return None
    for cut in range(len(tail) - 1, max(0, len(tail) // 2), -1):
        if tail[cut] not in "}]":
            continue
        frag = tail[: cut + 1]
        opens, in_str, esc = [], False, False
        for ch in frag:
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch in "{[":
                opens.append(ch)
            elif ch in "}]":
                if opens:
                    opens.pop()
        if in_str:
            continue
        closers = "".join("}" if o == "{" else "]" for o in reversed(opens))
        try:
            return json.loads(frag + closers)
        except Exception:
            continue
    return None


def parse_json_loose(text):
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except Exception:
        i, j = s.find("{"), s.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(s[i : j + 1])
            except Exception:
                pass
        fixed = _salvage_json(s)
        if fixed is not None:
            return fixed
        raise ValueError("模型没返回合法 JSON：%s" % s[:300])


# ---------------------------------------------------------------- 提示词


SYSTEM = (
    "你是一位帮中文读者快速判断英文论文价值的研究助理。"
    "读者是计算机专业学生，英文能读但慢，需要你替他做第一轮筛选与导航。"
    "你只输出 JSON，不要任何解释文字、不要 Markdown 代码围栏。"
)

SCHEMA_HINT = """请严格输出下面这个 JSON 结构（字段一个都不能少，也不要多）：

{
  "worth_reading": "值得精读 | 扫结论即可 | 与你不相关（三选一，原样输出）",
  "why": "一句话说明理由，中文，不超过 40 字",
  "tl_dr": ["第一句", "第二句", "第三句"],
  "claims": [
    {"idx": 12, "claim": "这篇论文的主张，中文，不超过 30 字",
     "evidence": "它的证据是什么，中文，不超过 30 字",
     "strength": "强 | 中 | 弱"}
  ],
  "glossary": [
    {"term": "masked language model", "zh": "掩码语言模型", "def": "中文解释，不超过 25 字"}
  ]
}

硬性要求：
- "idx" 必须是我给你的段落编号（方括号里的数字），指认「这句话出现在哪一段」，不许编造。
- claims 给 6 到 8 条，且必须覆盖全文不同部分：至少 1 条来自引言/动机，1 到 2 条来自方法，至少 2 条来自实验或结果（Results / Experiments 小节，含关键数字），至少 1 条来自结论或局限。读完整篇再选，不要只用前半篇。
- tl_dr 正好 3 句，分别回答：这篇解决什么问题、怎么做的、结果如何（有数字就写数字），不要「本文提出…」这种空话。
- glossary 给 10 到 15 个术语，是读者读这篇最容易卡住的词（领域专有名词、缩写、方法名），不要给 AI/ML 的常识词。
- 全部中文表述，但 term 保留英文原文。"""


def pidx(p):
    """段序号：解析层用的是 "i"，模型层习惯叫 "idx"，两个都认。"""
    return p["idx"] if "idx" in p else p["i"]


def build_messages(parsed, budget=48000):
    """把解析结果压成「标题 + 小节标题 + 带编号的正文」，喂给模型。

    整篇放得下就整篇送；放不下先把每段截短（700 → 400 → 240 字），而不是从中间切断整篇——
    否则实验/结论一节永远进不了模型，摘要就会「只覆盖前半篇」。
    """
    paras = parsed["paras"]
    title = next((p["text"] for p in paras if p["kind"] == "title"), "")
    headings = [p["text"] for p in paras if p["kind"] == "heading"][:30]

    def pack(limit):
        chunks, used = [], 0
        for p in paras:
            if p["kind"] == "title":
                continue
            t = p["text"]
            if limit and len(t) > limit:
                t = t[:limit].rstrip() + "…"
            line = "[%d] %s" % (pidx(p), t)
            chunks.append(line)
            used += len(line)
        return chunks, used

    if pack(0)[1] <= budget:
        chunks, used = pack(0)
    else:
        for limit in (700, 400, 240):
            chunks, used = pack(limit)
            if used <= budget:
                break
        else:                      # 极长的论文：按段截到预算，后面标注省略
            chunks, used = [], 0
            for p in paras:
                if p["kind"] == "title":
                    continue
                line = "[%d] %s" % (pidx(p), p["text"][:240])
                if used + len(line) > budget:
                    chunks.append("（后面还有 %d 段，长度超限省略）" % (len(paras) - len(chunks) - 1))
                    break
                chunks.append(line)
                used += len(line)

    head = []
    if title:
        head.append("论文标题：" + title)
    if headings:
        head.append("小节标题：" + " | ".join(headings))
    user = (
        "\n".join(head)
        + "\n\n以下是按阅读顺序切好的段落（[编号] 正文）：\n\n"
        + "\n\n".join(chunks)
        + "\n\n"
        + SCHEMA_HINT
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], used


# ---------------------------------------------------------------- 校验


def _s(v, limit):
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


def validate(summary, parsed):
    """把模型输出洗成可信的结构；不可信的条目直接丢，不猜。"""
    paras = parsed["paras"]
    by_idx = {pidx(p): p for p in paras}

    worth = _s(summary.get("worth_reading"), 20)
    if worth not in WORTH:
        worth = "扫结论即可"

    tl = summary.get("tl_dr") or []
    if isinstance(tl, str):
        tl = [tl]
    tl_dr = [_s(x, 120) for x in tl if _s(x, 120)][:3]

    claims, seen = [], set()
    for c in summary.get("claims") or []:
        if not isinstance(c, dict):
            continue
        try:
            idx = int(c.get("idx"))
        except Exception:
            continue
        para = by_idx.get(idx)
        if para is None or para["kind"] not in ("body", "heading") or idx in seen:
            continue
        seen.add(idx)
        claims.append({
            "idx": idx,
            "claim": _s(c.get("claim"), 80),
            "evidence": _s(c.get("evidence"), 80),
            "strength": _s(c.get("strength"), 2) if _s(c.get("strength"), 2) in STRENGTH else "中",
            "anchor": {"idx": idx, "head": para["anchor"]["head"]},
        })
        if len(claims) >= 8:
            break

    glossary, got = [], set()
    for g in summary.get("glossary") or []:
        if not isinstance(g, dict):
            continue
        term = _s(g.get("term"), 60)
        if not term or term.lower() in got:
            continue
        got.add(term.lower())
        glossary.append({"term": term, "zh": _s(g.get("zh"), 30), "def": _s(g.get("def"), 80)})
        if len(glossary) >= 15:
            break

    ok = bool(tl_dr) and bool(claims) and bool(glossary)
    return {
        "worth_reading": worth,
        "why": _s(summary.get("why"), 100),
        "tl_dr": tl_dr,
        "claims": claims,
        "glossary": glossary,
    }, ok


# ---------------------------------------------------------------- 第一跳


# ---------------------------------------------------------------- 输入预算（按篇幅动态）

# 不同篇幅给不同输入预算（字符数）。deepseek-chat 上下文 64k tokens，
# 12 万英文字符约 3 万 tokens，留足输出与提示的余量。
BUDGET_TIERS = ((15, 30000), (40, 70000), (80, 120000), (10 ** 9, 150000))

# 分块精读时每块最多这么多字符；一次解析最多切这么多块，再多就把每段截短
MAP_CHUNK = 26000
MAP_MAX_CHUNKS = 12


def page_count(parsed):
    pages = parsed.get("pages") or parsed.get("page_count")
    if pages:
        return int(pages)
    return max((p["page"] for p in parsed["paras"]), default=0)


def budget_for(parsed):
    """按页数给输入预算：15 页以内 3 万字符，40 页 7 万，80 页 12 万，再长 15 万。"""
    pages = page_count(parsed)
    for limit, budget in BUDGET_TIERS:
        if pages <= limit:
            return budget
    return BUDGET_TIERS[-1][1]


MAP_SYSTEM = (
    "你是一位替读者精读英文论文的研究助理。"
    "你只输出 JSON，不要任何解释文字、不要 Markdown 代码围栏。"
)

MAP_HINT = """请输出下面这个 JSON（字段一个都不能少）：
{
  "points": [{"idx": 12, "point": "这一段/这一小节说了什么，中文，不超过 40 字",
              "why": "为什么重要（结论、数字、方法关键点），不超过 30 字"}],
  "numbers": ["关键数字，如 28.4 BLEU / 提升 7.7 个点"],
  "terms": [{"term": "英文术语", "zh": "中文译名"}]
}
要求：points 给 6 到 10 条，覆盖这一段的每个小节；idx 用文中段落编号（方括号里的数字）。"""


def _chunk(paras, max_chars):
    """按段落顺序切成若干块，每块不超过 max_chars 个字符。"""
    chunks, cur, used = [], [], 0
    for p in paras:
        if p["kind"] == "title":
            continue
        line = "[%d] %s" % (pidx(p), p["text"])
        if cur and used + len(line) > max_chars:
            chunks.append(cur)
            cur, used = [], 0
        cur.append(line)
        used += len(line)
    if cur:
        chunks.append(cur)
    return chunks


def _map_notes(parsed, budget):
    """长篇文档：分块精读，每块出一份要点，最后再汇总。"""
    paras = parsed["paras"]
    chunks = _chunk(paras, MAP_CHUNK)
    if len(chunks) > MAP_MAX_CHUNKS:          # 太长就先把每段截短，保证块数可控
        short = []
        for p in paras:
            if p["kind"] == "title":
                continue
            short.append(dict(p, text=p["text"][:240]))
        chunks = _chunk(short, MAP_CHUNK)[:MAP_MAX_CHUNKS]

    notes, used_tokens, all_usage = [], 0, {}
    for i, lines in enumerate(chunks, 1):
        body = "\n".join(lines)
        user = (
            "下面是论文的第 %d/%d 部分（按原文顺序，方括号是段落编号）：\n\n%s\n\n%s"
            % (i, len(chunks), body, MAP_HINT)
        )
        msg = [{"role": "system", "content": MAP_SYSTEM}, {"role": "user", "content": user}]
        try:
            raw, usage = chat_json(msg, temperature=0.2, max_tokens=2600)
        except Exception:
            # 一块失败不能让整篇总结失败：重试一次，再不行就记成「读失败」继续下一块
            try:
                raw, usage = chat_json(msg, temperature=0.0, max_tokens=2600)
            except Exception:
                notes.append({"part": i, "of": len(chunks), "points": [],
                              "numbers": [], "terms": [], "failed": True})
                continue
        used_tokens += int((usage or {}).get("total_tokens") or 0)
        all_usage = merge_usage(all_usage, usage)
        pts = raw.get("points") if isinstance(raw, dict) else None
        notes.append({
            "part": i,
            "of": len(chunks),
            "points": pts if isinstance(pts, list) else [],
            "numbers": (raw.get("numbers") or [])[:10] if isinstance(raw, dict) else [],
            "terms": (raw.get("terms") or [])[:12] if isinstance(raw, dict) else [],
        })
    return notes, used_tokens, all_usage


def build_reduce_messages(parsed, notes):
    """把分块要点压成一次汇总用的消息。"""
    paras = parsed["paras"]
    title = next((p["text"] for p in paras if p["kind"] == "title"), "")
    headings = [p["text"] for p in paras if p["kind"] == "heading"][:40]

    lines = []
    for n in notes:
        lines.append("【第 %d/%d 部分】" % (n["part"], n["of"]))
        for pt in n["points"][:12]:
            if isinstance(pt, dict):
                lines.append("  - [%s] %s（%s）" % (pt.get("idx", "?"),
                                                   pt.get("point", ""), pt.get("why", "")))
            else:
                lines.append("  - %s" % pt)
        if n["numbers"]:
            lines.append("  数字：" + "；".join(str(x) for x in n["numbers"][:8]))
        if n["terms"]:
            lines.append("  术语：" + "、".join(
                (t.get("term", "") if isinstance(t, dict) else str(t)) for t in n["terms"][:10]))

    head = []
    if title:
        head.append("论文标题：" + title)
    if headings:
        head.append("小节标题：" + " | ".join(headings))
    user = (
        "\n".join(head)
        + "\n\n这是一篇长论文的分块精读笔记（按原文顺序）：\n"
        + "\n".join(lines)
        + "\n\n请基于整篇的笔记做总结（不要只看开头几块；claims 的 idx 用笔记里方括号中的编号）。\n\n"
        + SCHEMA_HINT
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def jump1(parsed):
    """第一跳：值不值得读 + 三句 TL;DR + claims + 术语表。返回 (summary, meta)。"""
    t0 = time.time()
    budget = budget_for(parsed)
    total = sum(len(p["text"]) + 8 for p in parsed["paras"] if p["kind"] != "title")
    mode, chunks, map_tokens, map_usage = "single", 0, 0, {}
    if total > budget:
        notes, map_tokens, map_usage = _map_notes(parsed, budget)
        messages = build_reduce_messages(parsed, notes)
        mode, chars, chunks = "map-reduce", len(messages[1]["content"]), len(notes)
    else:
        messages, chars = build_messages(parsed, budget)

    last_err = None
    for attempt, temp in enumerate((0.3, 0.1)):
        try:
            raw, usage = chat_json(messages, temperature=temp)
            summary, ok = validate(raw, parsed)
            if ok:
                return summary, {
                    "ms": int((time.time() - t0) * 1000),
                    "chars": chars,
                    "budget": budget,
                    "doc_chars": total,
                    "mode": mode,
                    "chunks": chunks,
                    "attempt": attempt + 1,
                    "usage": usage,
                    "map_usage": map_usage,
                    "map_tokens": map_tokens,
                    "model": config()["model"],
                    # 成本按「分块 + 汇总」的总量算（map-reduce 时只算 reduce 会严重低估）
                    "cost": usage_info(merge_usage(usage, map_usage), config()["model"]),
                }
            last_err = ValueError("模型输出缺少必要字段（tl_dr / claims / glossary）")
        except Exception as exc:  # 网络、JSON、校验都在这
            last_err = exc
    raise RuntimeError("第一跳失败：%s" % last_err)


# ---------------------------------------------------------------- 第二跳：逐段批注

ANNO_SYSTEM = "你是论文精读助手，给论文的每一段写一句批注。只输出 JSON，不要任何解释文字。"

ROLES = ("背景", "缺口", "方法", "证据", "局限")

ANNO_HINT = """只输出这个 JSON：
{"items":[{"idx":段落编号(整数，必须是我给的编号),
           "role":"这段在论证链条里担任什么角色，只能从这五个里选一个：背景 / 缺口 / 方法 / 证据 / 局限",
           "one_line":"这段话在说什么（≤30 字，中文，具体，不要空话）",
           "note":"读这段要抓什么，或它和全文哪部分有关（≤25 字）",
           "terms":[{"t":"英文术语原文","zh":"中文译名",
                     "selfmade":这个术语是不是本文作者自己造的/命名的（true/false，判断见下）,
                     "why":"写 true 时给一句话依据（≤20 字，引用本段的命名动作）"}],
           "selfmade":本段是否在给本文自己造的术语下定义（等价于 terms 里有 true）}]}

role 的判断标准（务必区分，不要全填一个）：
- 背景：领域现状、前人都做了什么、常识前提
- 缺口：现有方法的不足、限制、作者要解决的空位
- 方法：作者提出的做法、架构、训练/推理流程
- 证据：实验、数字、对比、消融、可视化结果
- 局限：作者承认的不足、失败情形、未来工作

要求：
- 每段都要有一条，idx 用我给的 [#编号]，不要改。
- one_line 要具体：出现数字/结论就把数字写进去，禁止“介绍了背景”这种废话。
- terms 每段 0–3 个，只挑读者可能不认识的专业词。

selfmade 的判定（重要，按四步走，不要凭“这段里有自创词”就写 true）：
1) 先在这一段里找**命名/定义动作**：we propose / introduce / present / call / term / name / define、
   “we refer to X as / X is dubbed / we coin”、专名后紧跟括号全称或缩写（如 RAX (Robot Agent eXploration)）、
   或段首「术语.」后紧跟一句定义。找不到 → false。
2) 若命名动作发生在**别的段落**（本段只是使用它、复述、或写 “as we discussed in the introduction”）→ false。
3) 若本段在给某词下定义时**带文献标号**（如 [2, 34, 49]、(26)），或出现 familiar from / adopted from /
   following prior work / has been suggested / 行业通行指标 → false（那是沿用的既有概念，不是本文自创）。
4) 以下一律 false：匿名化代称（hereafter, the “AI firm”）、变量名与分组口径（quintile、high-skill 等）、
   产品名 / 公司名、他人数据集或 benchmark、某个任务里造出来的具体实例、普通英文词被临时借用但没有本文定义。
只有「本文提出的方法 / 模块 / 指标 / 自建数据集 / 理论概念」这类**论文级命名**才算 true。

正例（应写 true）：
- “In this work we propose the Transformer, a model architecture eschewing recurrence…”（we propose + 专名）
- “We introduce RAX (Robot Agent eXploration), an open-source framework…”（专名 + 括号全称）
- “Budget and scenes. The exploration budget counts exploration episodes.”（段首术语 + 定义句）
反例（应写 false）：
- “Shortcut connections [2, 34, 49] are those skipping one or more layers.”（带引用标号 = 沿用既有概念）
- “... provides AI-based customer service support software (hereafter, the “AI firm”)”（匿名化代称）
- “In this section, we demonstrate how RAX achieves continual learning…”（只是使用，不是定义）

terms 里每个词单独给 selfmade（术语级，不要整段一个结论）：
- 同一段里可能既有既有概念又有本文命名：既有概念写 false，本文命名的写 true。
- 写 true 时必须满足上面四步里的“本段命名动作”，且那句动作指向的就是这个词；why 里摘出那句动作（如 “we propose the Transformer”）。
- 段落级 selfmade = terms 里是否有 true；terms 为空时按上面四步单独判。
"""


# selfmade 的确定性兜底：模型说 true 时，本段还得真找得到命名/定义动作。
# 2026-11-14 用 30 条人工抽查做反事实：关闭时 precision 33%，开启后 86%（标记数 30→7，召回 6/10）。
# 宁可少标（漏掉几条真自创）也不要错标——错标会让读者把作者生造的词当成领域共识。
SELF_MADE_GUARD = True

_SM_NAMING = re.compile(
    r"(?i)\b(we|this paper|our (?:work|paper|study))\s+(?:hereby\s+)?"
    r"(propose|introduce|present|call|term|name|define|establish|coined|dub)|"
    r"\bwe\s+refer\s+to\b|\breferred\s+to\s+as\b|\bdubbed\b|\bcoined\b|\buse\s+the\s+term\b|"
    r"\bwe\s+(?:modify|re-?design|design|change)\b[^.]{0,60}?\bas\b")
_SM_DEF = re.compile(
    r"(?i)\b(is|are)\s+defined\s+as\b|\bdefined\s+as\b|\bdenotes?\b|\bwe\s+define\b|"
    r"\bwe\s+call\b|\bcounts?\b|\bwe\s+measure\b")
_SM_LEAD_TERM = re.compile(r"^([A-Z][A-Za-z\-]*(?:\s+[A-Za-z\-]+){0,4})\.\s")
_SM_ACRO = re.compile(r"\b([A-Z][A-Za-z\-]+(?:\s+[A-Za-z\-]+){0,4})\s*\(([A-Z]{2,}[A-Za-z0-9\-]*)\)")
_SM_ACRO2 = re.compile(r"\b([A-Z]{2,}[A-Za-z0-9\-]*)\s*\(([A-Z][A-Za-z\-]+(?:\s+[A-Za-z\-]+){1,6})\)")
_SM_QUOTED = re.compile(r"(?i)\b(call|term|name|dub|refer to)\b[^.]{0,60}[\"“]")
_SM_ANON = re.compile(r"(?i)hereafter,?\s+the\s+[\"“]")
_SM_FAMILIAR = re.compile(r"(?i)\b(familiar from|adopted from|borrowed from|following prior work)\b")


def selfmade_ok(text):
    """这一段本段有没有“在给它命名/定义”的证据（没有就不是本文自创）。"""
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return False
    if _SM_ANON.search(t) or _SM_FAMILIAR.search(t):
        return False
    if _SM_NAMING.search(t) or _SM_ACRO.search(t) or _SM_ACRO2.search(t):
        return True
    if _SM_QUOTED.search(t):
        return True
    # 段首「术语.」+ 同段有定义动词（Budget and scenes. / Rehearsal. 这类自查表写法）
    return bool(_SM_LEAD_TERM.match(t)) and bool(_SM_DEF.search(t)) and len(t) < 700


def strong_definition(text):
    """自查表式定义段：段首「术语.」+ 同段定义动词（Budget and scenes. X counts ...）。"""
    t = re.sub(r"\s+", " ", text or "").strip()
    return bool(_SM_LEAD_TERM.match(t)) and bool(_SM_DEF.search(t)) and len(t) < 700


_CITE_TAIL = re.compile(r"^\s*(?:\[\d|\(\d)")


def term_selfmade_ok(text, term):
    """术语级兜底：这个词在本段里得真被命名，且不是“术语 + 文献标号”的沿用写法。"""
    text = text or ""
    if not selfmade_ok(text):
        return False
    words = re.findall(r"[A-Za-z]+", (term or "").lower())
    if not words:
        return False
    pat = r"\b" + r"\W+".join(re.escape(w) for w in words[:3])
    low = text.lower()
    m = re.search(pat, low)
    if not m:
        return False
    if _CITE_TAIL.match(low[m.end():m.end() + 40]):
        return False
    return True


def annotate_batch(parsed, idxs, timeout=120):
    """给一批段落写批注（每批 3–4 段，失败重试一次）。"""
    paras = parsed["paras"]
    title = parsed.get("title") or ""
    blocks = []
    for i in idxs:
        p = paras[i]
        text = p["text"]
        if len(text) > 900:
            text = text[:900] + "…"
        blocks.append("[#%d] %s\n%s" % (i, p.get("anchor", {}).get("head", ""), text))
    user = "论文标题：%s\n\n下面是这篇论文的 %d 段原文。逐段给批注：\n\n%s\n\n%s" % (
        title, len(idxs), "\n\n".join(blocks), ANNO_HINT
    )
    msg = [{"role": "system", "content": ANNO_SYSTEM}, {"role": "user", "content": user}]
    import time as _t

    t0 = _t.time()
    try:
        raw, usage = chat_json(msg, temperature=0.2, max_tokens=1600, timeout=timeout)
    except Exception:
        raw, usage = chat_json(msg, temperature=0.0, max_tokens=1600, timeout=timeout)

    want = set(int(x) for x in idxs)
    items = raw.get("items") if isinstance(raw, dict) else None
    if not items:
        items = []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            i = int(it.get("idx"))
        except Exception:
            continue
        if i not in want:
            continue
        one = _s(it.get("one_line"), 80)
        if not one:
            continue
        terms = []
        text_i = paras[i].get("text") or ""
        any_sm = False
        for t in (it.get("terms") or [])[:3]:
            if isinstance(t, dict) and t.get("t"):
                tt = _s(t.get("t"), 40)
                sm = bool(t.get("selfmade")) and (not SELF_MADE_GUARD or term_selfmade_ok(text_i, tt))
                any_sm = any_sm or sm
                terms.append({"t": tt, "zh": _s(t.get("zh"), 40),
                              "selfmade": sm,
                              "why": _s(t.get("why"), 40) if sm else ""})
        role = _s(it.get("role"), 8).strip()
        if role not in ROLES:
            role = ""
        out.append({
            "idx": i,
            "role": role,
            "one_line": one,
            "note": _s(it.get("note"), 60),
            "terms": terms,
            "selfmade": any_sm
                        or (bool(it.get("selfmade")) and (not SELF_MADE_GUARD or selfmade_ok(text_i)))
                        or (SELF_MADE_GUARD and strong_definition(text_i)),
            "anchor": paras[i].get("anchor"),
        })
    meta = {
        "ms": int((_t.time() - t0) * 1000),
        "usage": usage or {},
        "asked": len(idxs),
        "got": len(out),
        "cost": usage_info(usage, config()["model"]),
    }
    return out, meta


# ---------------------------------------------------------------- 追问

ASK_SYSTEM = (
    "你是论文精读助手，回答读者对这篇论文的具体疑问。只依据给你的材料回答；"
    "材料不足以回答时直接说「材料里没写」，并指出还需要哪部分内容。"
    "中文，先给结论再给依据，180 字以内，不要寒暄。引用材料时写成 [#段落编号]。"
)

_STOP = set(
    "the a an of to in on for with and or is are was were be been being it its this that these those as by at "
    "from we our their they them which what how why when does do did can could should would may might must not no "
    "than then there here also such more most much many use used using paper".split()
)


def _tokens(t):
    return [w for w in re.findall(r"[A-Za-z][A-Za-z\-]{2,}", (t or "").lower()) if w not in _STOP]


def retrieve(parsed, question, k=3, exclude=None):
    """最土的检索：问题里的实词在段落里出现几次，就排多前。"""
    paras = parsed["paras"]
    terms = set(_tokens(question))
    if not terms:
        return []
    scored = []
    for i, p in enumerate(paras):
        if i == exclude or p.get("kind") not in ("body", "heading"):
            continue
        toks = _tokens(p.get("text", "")[:1500])
        if not toks:
            continue
        same = set(toks) & terms
        if not same:
            continue
        hit = sum(1 for w in toks if w in terms)
        scored.append((hit + 0.5 * len(same), i))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [i for _, i in scored[:k]]


def ask(parsed, question, idx=None, summary=None, timeout=120):
    """回答一个追问：材料 = 选中段 + 检索命中的 3 段 + 摘要要点。"""
    import time as _t

    paras = parsed["paras"]
    picked = retrieve(parsed, question, 3, exclude=idx)
    if not picked and summary:
        # 中文提问检索不到英文词：退而用摘要里的主张段当材料
        picked = [c["idx"] for c in (summary.get("claims") or [])[:3]
                  if isinstance(c.get("idx"), int) and 0 <= c["idx"] < len(paras)]
    blocks = []
    if idx is not None and 0 <= idx < len(paras):
        blocks.append("[#%d 读者选中] %s" % (idx, paras[idx]["text"][:900]))
    for i in picked:
        blocks.append("[#%d] %s" % (i, paras[i]["text"][:900]))
    if not blocks:
        for i in range(min(3, len(paras))):
            blocks.append("[#%d] %s" % (i, paras[i]["text"][:900]))
    ctx = ""
    if summary:
        ctx = "摘要要点：%s\n关键主张：%s\n" % (
            "；".join(summary.get("tl_dr") or []),
            "；".join(c.get("claim", "") for c in (summary.get("claims") or [])[:5]),
        )
    user = "论文标题：%s\n%s\n材料段落：\n\n%s\n\n读者的问题：%s" % (
        parsed.get("title") or "",
        ctx,
        "\n\n".join(blocks),
        question,
    )
    t0 = _t.time()
    text, usage = chat(
        [{"role": "system", "content": ASK_SYSTEM}, {"role": "user", "content": user}],
        temperature=0.2,
        max_tokens=900,
        timeout=timeout,
        json_mode=False,
    )
    used = ([idx] if idx is not None else []) + picked
    return {
        "answer": (text or "").strip(),
        "used": used,
        "meta": {"ms": int((_t.time() - t0) * 1000), "usage": usage or {},
                 "retrieved": picked, "cost": usage_info(usage, config()["model"])},
    }
