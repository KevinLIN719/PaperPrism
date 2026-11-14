"""PaperPrism 本地后端：把 PDF 解析成段落，顺便当静态文件服务器。

启动：
    python server.py
然后浏览器打开 http://127.0.0.1:8765

接口：
    GET  /api/health          -> {"ok": true}
    GET  /api/papers          -> 项目 papers/ 目录里有哪些 PDF
    POST /api/parse           -> body {"path": "papers/xxx.pdf"}，返回解析结果
"""

import json
import os
import re
import sys
import threading
import time
import traceback
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "vendor", "pymupdf_pkg"))

import llm  # noqa: E402
import repro  # noqa: E402
import store  # noqa: E402
import zhihu  # noqa: E402
import m1_parse  # noqa: E402  （要先把 vendor 路径塞进去，所以放在 sys.path 之后）

WEB_DIR = os.path.join(ROOT, "web")
PAPERS_DIR = os.path.join(ROOT, "papers")
IMPORT_DIR = os.path.join(PAPERS_DIR, "imported")   # 用户拖进来的 PDF 存这里
PORT = int(os.environ.get("PAPERPRISM_PORT", "8765"))

# 批注是 2 个并发 worker 一批一批回写的，store.merge 是「读文件 → 改 → 写回」，
# 不加锁就会互相覆盖（丢批注）。所有书库写入都走这把锁。
_STORE_LOCK = threading.Lock()

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
}


def anchor_of(idx, text):
    """批注锚点：段序号 + 首 8 个词。首 8 词用来校验，对不上就丢弃批注。"""
    words = re.findall(r"[A-Za-z0-9''-]+", text)
    return {"idx": idx, "head": " ".join(words[:8])}


def parse_request(payload):
    rel = (payload or {}).get("path", "")
    full = os.path.abspath(os.path.join(ROOT, rel))
    if not full.startswith(os.path.abspath(PAPERS_DIR)):
        raise ValueError("只能解析 papers/ 目录里的 PDF")
    if not full.lower().endswith(".pdf") or not os.path.isfile(full):
        raise ValueError("找不到这个 PDF：%s" % rel)

    paras = m1_parse.parse_pdf(full)
    out = []
    for i, p in enumerate(paras):
        out.append({
            "i": i,
            "page": p["page"],
            "col": p.get("col", "full"),
            "kind": p["kind"],
            "chars": len(p["text"]),
            "rects": p.get("rects", []),
            "text": p["text"],
            "anchor": anchor_of(i, p["text"]),
        })
    return {
        "file": os.path.basename(full),
        "pages": max((p["page"] for p in out), default=0),
        "count": len(out),
        "parse_version": m1_parse.PARSE_VERSION,
        "page_sizes": m1_parse.LAST_PAGE_SIZES,
        "paras": out,
    }


_PARSE_CACHE = {}


_REPRO_CACHE = {}


def repro_cached(payload):
    """复现体检结果也按「文件 + 修改时间」缓存：GitHub 查询和模型调用都不便宜。"""
    rel = (payload or {}).get("path", "")
    full = os.path.abspath(os.path.join(ROOT, rel))
    stamp = None
    if os.path.isfile(full):
        stamp = (full, os.path.getmtime(full))
        hit = _REPRO_CACHE.get(stamp)
        if hit is not None:
            return hit
    parsed = parse_cached(payload)
    card, meta = repro.repro_check(parsed)
    out = {"file": parsed["file"], "card": card, "meta": meta}
    if stamp is not None:
        _REPRO_CACHE[stamp] = out
    return out


def zhihu_cached(payload):
    """知乎讨论卡：结果按论文内容哈希缓存进书库，重开这篇不再花知乎额度。

    只有 "搜到了" 和 "确实没搜到" 才落盘；没配 key / 鉴权失败 / 额度用完 都不落盘，
    这样用户补上 key 或第二天再打开时，会自动重试，而不是一直卡在旧错误上。
    """
    sha, _full, rel = paper_sha(payload)
    data = store.load(sha) or {}
    # 前端会把内存里最新的摘要/批注一起传来：刚生成完还没落盘时也能立刻挑对术语，
    # 避免和 /api/store 的写入抢时序（只用于这次挑词，不覆盖书库里的内容）。
    snap = dict(data)
    if (payload or {}).get("summary"):
        snap["summary"] = payload["summary"]
    ann = (payload or {}).get("annots")
    if ann:
        if isinstance(ann, list):
            ann = {str(a["idx"]): a for a in ann if isinstance(a, dict) and a.get("idx") is not None}
        snap["annots"] = ann
    card, cached = zhihu.build_card(snap, refresh=bool((payload or {}).get("refresh")))
    card["cached"] = cached
    if not cached and card.get("status") in ("ok", "empty"):
        stored = dict(card)
        stored.pop("cached", None)
        with _STORE_LOCK:
            store.merge(sha, {"zhihu": stored}, path=rel)
    return {"sha": sha, "card": card, "cached": cached}


def parse_cached(payload):
    """解析结果按「文件 + 修改时间」缓存：同一篇论文反复要摘要时不用重新解析。"""
    rel = (payload or {}).get("path", "")
    full = os.path.abspath(os.path.join(ROOT, rel))
    stamp = None
    if os.path.isfile(full):
        stamp = (full, os.path.getmtime(full))
        hit = _PARSE_CACHE.get(stamp)
        if hit is not None:
            return hit
    data = parse_request(payload)
    if stamp is not None:
        _PARSE_CACHE.clear()
        _PARSE_CACHE[stamp] = data
    return data


def paper_sha(payload):
    rel = (payload or {}).get("path", "")
    full = os.path.abspath(os.path.join(ROOT, rel))
    if not full.startswith(os.path.abspath(PAPERS_DIR)) or not full.lower().endswith(".pdf") or not os.path.isfile(full):
        raise ValueError("找不到这个 PDF：%s" % rel)
    return store.sha_of(full), full, rel


def open_paper(payload):
    """打开论文：本地书库命中就直接回放，一条模型调用都不发。"""
    sha, full, rel = paper_sha(payload)
    data = store.load(sha)
    if not data or not data.get("parse"):
        return {"cached": False, "sha": sha, "path": rel, "file": os.path.basename(full)}
    # 解析规则升级过（PARSE_VERSION 变了）：旧的段落编号、分段、分类都不可信，
    # 派生结果（摘要/批注/体检）也就对不上了 —— 丢掉重跑，别让老结果糊在新解析上。
    if (data["parse"] or {}).get("parse_version") != m1_parse.PARSE_VERSION:
        for k in ("parse", "summary", "summary_meta", "annots", "repro", "zhihu", "usage"):
            data.pop(k, None)
        with _STORE_LOCK:
            store.save(sha, data)
        return {"cached": False, "sha": sha, "path": rel,
                "file": os.path.basename(full), "stale": True}
    with _STORE_LOCK:
        data = store.merge(sha, {}, path=rel)      # 顺手更新"最近打开"
    return {"cached": True, "sha": sha, "path": rel, "file": data.get("file"), "bundle": data}


def save_paper(payload):
    """前端每跑完一段（解析 / 摘要 / 批注 / 体检）就把结果并进本地书库。"""
    sha, full, rel = paper_sha(payload)
    patch = {k: payload.get(k) for k in
             ("parse", "summary", "summary_meta", "repro", "annots", "note", "del_note", "ask", "usage") if k in payload}
    patch["file"] = os.path.basename(full)
    patch["size"] = os.path.getsize(full)
    with _STORE_LOCK:
        data = store.merge(sha, patch, path=rel)
    return {"ok": True, "sha": sha, "counts": {
        "notes": len(data.get("notes") or []),
        "asks": len(data.get("asks") or []),
        "annots": len(data.get("annots") or {}),
    }}


def list_papers():
    if not os.path.isdir(PAPERS_DIR):
        return []
    items = []
    for name in sorted(os.listdir(PAPERS_DIR)):
        if name.lower().endswith(".pdf"):
            items.append({
                "name": name,
                "path": "papers/" + name,
                "kb": round(os.path.getsize(os.path.join(PAPERS_DIR, name)) / 1024),
            })
    if os.path.isdir(IMPORT_DIR):
        for name in sorted(os.listdir(IMPORT_DIR)):
            if name.lower().endswith(".pdf"):
                items.append({
                    "name": name,
                    "path": "papers/imported/" + name,
                    "kb": round(os.path.getsize(os.path.join(IMPORT_DIR, name)) / 1024),
                    "imported": True,
                })
    for it in items:
        try:
            sha = store.sha_of(os.path.join(ROOT, it["path"]))
            d = store.load(sha)
            if d and d.get("parse"):
                it["cached"] = {"sha": sha,
                                "summary": bool(d.get("summary")),
                                "annots": len(d.get("annots") or {}),
                                "notes": len(d.get("notes") or []),
                                "asks": len(d.get("asks") or [])}
        except Exception:
            pass
    return items


class Handler(SimpleHTTPRequestHandler):
    server_version = "PaperPrism/0.2"

    def log_message(self, fmt, *args):  # 安静一点，只留错误
        if args and str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---------- 工具 ----------
    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path):
        if not os.path.isfile(path):
            self.send_json({"error": "not found"}, 404)
            return
        ext = os.path.splitext(path)[1].lower()
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        # 页面和脚本每次都取最新的：改了 reader.html 之后，浏览器若拿缓存，
        # 会继续用旧 JS 渲染——明明是新的解析结果，看起来却像「老版」。
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    # ---------- 路由 ----------
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/health":
            return self.send_json({
                "ok": True,
                "llm": {
                    "model": llm.config()["model"],
                    "base": llm.config()["base"],
                    "key_set": llm.has_key(),
                },
                "zhihu": zhihu.quota_hint(),
            })
        if path == "/api/papers":
            return self.send_json({"papers": list_papers()})
        if path == "/api/settings":           # 设置面板：当前模型/地址/密钥（打码）+ 来源
            return self.send_json(llm.settings_info())
        if path == "/api/library":            # 本地书库索引：哪些论文已经有批注/笔记
            return self.send_json({"library": store.library()})
        if path.startswith("/api/"):
            return self.send_json({"error": "unknown api"}, 404)

        if path.startswith("/pdf/"):            # 原来的 PDF 本身，给阅读器渲染原版式用
            from urllib.parse import unquote
            rel = unquote(path[5:].lstrip("/"))
            target = os.path.abspath(os.path.join(PAPERS_DIR, rel))
            if not target.startswith(os.path.abspath(PAPERS_DIR)):
                return self.send_json({"error": "forbidden"}, 403)
            return self.send_file(target)

        if path in ("/", ""):
            path = "/reader.html"          # 主界面 = 原版式阅读器；重排视图留在 /index.html
        target = os.path.abspath(os.path.join(WEB_DIR, path.lstrip("/")))
        if not target.startswith(WEB_DIR):
            return self.send_json({"error": "forbidden"}, 403)
        self.send_file(target)

    def handle_upload(self):
        """body 是 PDF 原始字节，文件名放在 X-Filename 头里（前端 encodeURIComponent 过）。"""
        try:
            from urllib.parse import unquote
            name = unquote(self.headers.get("X-Filename") or "upload.pdf")
            name = os.path.basename(name).replace("\\", "_").strip() or "upload.pdf"
            if not name.lower().endswith(".pdf"):
                name += ".pdf"
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                return self.send_json({"error": "空文件"}, 400)
            if n > 80 * 1024 * 1024:
                return self.send_json({"error": "文件太大（>80MB）"}, 400)
            os.makedirs(IMPORT_DIR, exist_ok=True)
            stem, ext = os.path.splitext(name)
            target = os.path.join(IMPORT_DIR, name)
            k = 1
            while os.path.exists(target):           # 同名就加后缀，不覆盖
                target = os.path.join(IMPORT_DIR, "%s-%d%s" % (stem, k, ext))
                k += 1
            data = self.rfile.read(n)
            with open(target, "wb") as f:
                f.write(data)
            base = os.path.basename(target)
            return self.send_json({
                "path": "papers/imported/" + base,
                "name": base,
                "kb": round(len(data) / 1024),
            })
        except Exception as exc:
            return self.send_json({"error": "上传失败：%s" % exc}, 500)

    def do_POST(self):
        route = self.path.split("?")[0]
        if route == "/api/upload":            # 拖进来的 PDF：原始字节直传，存 papers/imported/
            return self.handle_upload()
        if route not in ("/api/parse", "/api/jump1", "/api/annotate", "/api/ask", "/api/repro",
                         "/api/open", "/api/store", "/api/forget", "/api/zhihu",
                         "/api/settings", "/api/settings/test"):
            return self.send_json({"error": "unknown api"}, 404)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            if route == "/api/settings":       # 保存模型配置（写 settings.json，不重启即生效）
                llm.save_settings(payload)
                return self.send_json(llm.settings_info())
            if route == "/api/settings/test":  # 测试连接：发一个几 token 的请求
                return self.send_json(llm.test_connection())
            if route == "/api/parse":
                return self.send_json(parse_cached(payload))
            if route == "/api/zhihu":           # 知乎讨论卡（站内搜索 API，结果进书库缓存）
                return self.send_json(zhihu_cached(payload))
            if route == "/api/forget":          # 丢掉这篇的本地记录，强制重跑
                sha, _full, rel = paper_sha(payload)
                with _STORE_LOCK:
                    return self.send_json({"ok": store.delete(sha)})
            if route == "/api/open":
                return self.send_json(open_paper(payload))
            if route == "/api/store":
                return self.send_json(save_paper(payload))
            if route == "/api/repro":
                return self.send_json(repro_cached(payload))
            if route == "/api/ask":
                # 追问：选中段 + 检索命中的段落 + 摘要要点
                parsed = parse_cached(payload)
                q = (payload.get("question") or "").strip()
                if not q:
                    return self.send_json({"error": "问题为空"}, 400)
                idx = payload.get("idx")
                idx = int(idx) if isinstance(idx, (int, float)) else None
                res = llm.ask(parsed, q, idx=idx, summary=payload.get("summary"))
                try:                                   # 追问记录也进索引，方便复查
                    sha, _full, rel = paper_sha(payload)
                    rec = {"id": "q%d" % int(time.time() * 1000), "q": q, "idx": idx,
                           "a": res.get("answer"), "used": res.get("used"), "ts": int(time.time())}
                    with _STORE_LOCK:
                        store.merge(sha, {"ask": rec}, path=rel)
                except Exception:
                    traceback.print_exc()
                return self.send_json({"file": parsed["file"], **res})
            if route == "/api/annotate":
                # 第二跳：给一批段落（3–4 段）写批注
                parsed = parse_cached(payload)
                batch = [int(x) for x in (payload.get("batch") or [])][:6]
                if not batch:
                    return self.send_json({"error": "batch 为空"}, 400)
                items, meta = llm.annotate_batch(parsed, batch)
                return self.send_json({"file": parsed["file"], "items": items, "meta": meta})
            # 第一跳：解析（带缓存）+ 结构化摘要
            parsed = parse_cached(payload)
            summary, meta = llm.jump1(parsed)
            return self.send_json({
                "file": parsed["file"],
                "count": parsed["count"],
                "summary": summary,
                "meta": meta,
            })
        except Exception as exc:  # 把错误原样回给前端，方便我调试
            traceback.print_exc()
            self.send_json({"error": str(exc)}, 400)


def main():
    addr = ("127.0.0.1", PORT)
    srv = ThreadingHTTPServer(addr, Handler)
    print("PaperPrism backend  ->  http://%s:%d" % addr)
    print("papers/ 里有 %d 篇 PDF" % len(list_papers()))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
