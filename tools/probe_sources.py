# -*- coding: utf-8 -*-
"""一次性探针：批量试下载候选 PDF，只报可用性，不落盘大文件。"""
import concurrent.futures as cf
import sys
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"}


def probe(item):
    key, url = item
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=45) as f:
            head = f.read(2048)
            ok = head[:5] == b"%PDF-"
            return "%-28s %s %s" % (key, "PDF " if ok else "not-pdf", head[:12])
    except Exception as exc:
        return "%-28s FAIL %s %s" % (key, type(exc).__name__, str(exc)[:60])


def main():
    items = []
    for line in sys.stdin.read().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        k, u = line.split("\t", 1)
        items.append((k, u))
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for r in ex.map(probe, items):
            print(r)


if __name__ == "__main__":
    main()
