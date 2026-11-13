# -*- coding: utf-8 -*-
"""把 v9 的两条新判据关掉，用「同一把尺子」重新量 v8。

v9 只动了两处规则（都在 m1_parse.py）：
  ENDS_SENTENCE_NOTE_AWARE —— 行尾上标脚注号不再算「没说完」
  SHORT_PROSE_JOIN         —— 短半句也允许并段（原来死守 >80 字符门槛）
把这两个模块级开关置 False，其余行为（含 v8 的所有规则）原样保留，就能量出 v8。

用法：
    python tools/audit_full.py --as-v8 papers_audit/c*.pdf papers/*.pdf \
        --json out/audit_v8_newruler.json
"""

import m1_parse as M


def apply_v8():
    M.ENDS_SENTENCE_NOTE_AWARE = False
    M.SHORT_PROSE_JOIN = False
