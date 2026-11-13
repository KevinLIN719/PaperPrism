# -*- coding: utf-8 -*-
"""PaperPrism 一条命令验收：改完代码跑这个。

    python tools/check.py          退出码 0 = 全过，非 0 = 有东西坏了

第 1 关  代码门禁：ruff（规则定义在根目录 ruff.toml，只收"一定是 bug"的，不管风格）
第 2 关  解析冒烟：4 篇固定论文重新解析，段数 / 正文字数必须与 tools/check_baseline.json 完全一致
第 3 关  精确对拍：store/ 里存有当前 PARSE_VERSION 缓存的论文，重解析的每一段文字必须与缓存逐段相同
         （这一关最严：能抓到"指标没变但段落被切碎了"这类问题）
"""

import glob
import io
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def step_ruff():
    print("\n[1/3] 代码门禁   python -m ruff check .")
    try:
        rc = subprocess.run([sys.executable, "-m", "ruff", "check", "."], cwd=ROOT).returncode
    except OSError as e:
        print("  [FAIL] ruff 跑不起来（%s）\n         先执行: python -m pip install ruff" % e)
        return False
    if rc == 0:
        print("  [ ok ] 门禁通过（0 条）")
        return True
    print("  [FAIL] 上面 ruff 报的都是真问题，不是口味问题")
    return False


def body_chars(paras):
    return sum(len(p.get("text") or "") for p in paras if p.get("kind") == "body")


_CACHE = {}                     # 同一篇 PDF 只解析一次（第 2、3 关会用到同一批文件）


def parse_cached(M, full):
    if full not in _CACHE:
        _CACHE[full] = M.parse_pdf(full)
    return _CACHE[full]


def step_smoke(M):
    print("\n[2/3] 解析冒烟  4 篇固定样本")
    path = os.path.join(HERE, "check_baseline.json")
    want_all = json.load(io.open(path, encoding="utf-8"))["papers"]
    good = True
    for rel, want in want_all.items():
        full = os.path.join(ROOT, rel)
        name = os.path.basename(rel)
        if not os.path.isfile(full):
            print("  [FAIL] %-34s 文件不存在" % name)
            good = False
            continue
        try:
            paras = parse_cached(M, full)
        except Exception as e:                      # 一篇炸了不许影响其它篇
            print("  [FAIL] %-34s 解析抛异常: %s: %s" % (name, type(e).__name__, e))
            good = False
            continue
        n, c = len(paras), body_chars(paras)
        if n == want["paras"] and c == want["body_chars"]:
            print("  [ ok ] %-34s 段=%-4d 正文=%d" % (name, n, c))
        else:
            print("  [FAIL] %-34s 变了: 段 %d->%d，正文 %d->%d"
                  % (name, want["paras"], n, want["body_chars"], c))
            print("         先判断是改好还是改坏；确认后更新 tools/check_baseline.json")
            good = False
        if not any(p.get("kind") == "title" for p in paras):
            print("  [FAIL] %-34s 没识别到标题" % name)
            good = False
    return good


def step_store(M):
    print("\n[3/3] 与 store 缓存逐段对拍")
    good = True
    checked = 0
    for f in sorted(glob.glob(os.path.join(ROOT, "store", "*.json"))):
        try:
            d = json.load(io.open(f, encoding="utf-8"))
        except Exception:
            continue
        rel = d.get("path") or ""
        cached = d.get("parse") or {}
        pv = cached.get("parse_version")
        if not rel:
            continue
        full = os.path.join(ROOT, rel)
        name = os.path.basename(rel)
        if not os.path.isfile(full):
            continue
        if pv != M.PARSE_VERSION:
            print("  [skip] %-34s 缓存是 v%s，当前 v%s（改版本号前忘了跑 migrate_parse_version.py？）"
                  % (name, pv, M.PARSE_VERSION))
            continue
        old = [p.get("text") for p in cached.get("paras") or []]
        try:
            new = [p.get("text") for p in parse_cached(M, full)]
        except Exception as e:
            print("  [FAIL] %-34s 解析抛异常: %s: %s" % (name, type(e).__name__, e))
            good = False
            continue
        checked += 1
        if old == new and len(old) == len(new):
            print("  [ ok ] %-34s %d 段逐段一致" % (name, len(new)))
        else:
            i = next((k for k in range(min(len(old), len(new))) if old[k] != new[k]), None)
            print("  [FAIL] %-34s 不一致: 缓存 %d 段 / 现在 %d 段，首个差异下标=%s"
                  % (name, len(old), len(new), i))
            good = False
    if checked == 0:
        print("  [warn] 没有可对拍的缓存（不影响通过）")
    return good


def main():
    sys.path.insert(0, ROOT)
    sys.path.insert(0, os.path.join(ROOT, "vendor", "pymupdf_pkg"))
    os.chdir(ROOT)
    t0 = time.time()
    print("PaperPrism 验收   root=%s" % ROOT)

    if not step_ruff():                 # 门禁都没过就不必跑解析
        print("\n[FAIL] 有东西坏了  （用时 %.1fs）" % (time.time() - t0))
        sys.exit(1)

    import m1_parse as M
    a = step_smoke(M)
    b = step_store(M)
    all_ok = a and b
    print("\n%s  （用时 %.1fs）"
          % ("[PASS] 全部通过" if all_ok else "[FAIL] 有东西坏了", time.time() - t0))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
