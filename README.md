# PaperPrism

本地运行的论文阅读工作台：把 PDF 拆成结构化段落，原版式和段落对照着读，边读边让模型做摘要、批注、答疑，最后判断这篇论文能不能复现。

整个东西跑在自己电脑上，数据落本地磁盘，只把论文正文发给模型接口。

## 它解决什么问题

读论文时的典型动作是「看一段原文 → 糊里糊涂往下滑 → 忘了前面写了啥 → 想查某个公式和实验的关系」。PDF 阅读器只有原文，笔记软件只有自己写的东西，两边对不上。

PaperPrism 把这两半接起来：

- 左边是 PDF 原版式，右边是同一篇论文解析出来的段落，点任意一边另一边会跳过去
- 每个段落都有模型写的批注，全文还有分段汇总的摘要
- 读不懂就在段落上追问，回答只基于这篇论文的正文
- 论文里说「我们的代码和数据在附录 A」时，可以跑一次复现体检，看数据、超参、代码到底给全了没

## 功能

**解析层**（`m1_parse.py`）

- 用 PyMuPDF 抽文字块，按坐标重建阅读顺序
- 双栏检测：靠左边缘聚类 + 长块宽度中位数判断，避免把双栏论文的左栏和右栏交错拼成一句
- 标题识别：字号、行高、编号模式多判据，同时排除公式碎片和表格分数行
- 段落合并：跨行、跨栏、跨页合并，并且用句末标点判断「这段说完了没」；行尾脚注号不会被误判成段中
- 目录行过滤：只有去掉页码后确实在正文里出现过的标题才摘掉，不会误删正文里的同名小标题
- 解析版本号 `PARSE_VERSION`：解析逻辑一变，旧缓存自动失效并重解析

**阅读器**（`web/reader.html`）

- PDF 原文（pdf.js）+ 结构化段落左右对照，双向跳转
- 段落级批注、用户自己的笔记、追问记录都挂在段落上
- 支持拖入 PDF 直接导入

**模型层**（`llm.py`）

- 任意 OpenAI 兼容接口，默认 DeepSeek 官方
- 长论文按 token 预算自动分块做 map-reduce：先分段批注，再汇总摘要
- 追问时先从正文检索相关段落再回答，不是让模型自由发挥
- 模型输出 JSON 做宽松修复（截断、缺字段、包了 markdown 代码块都能救回来）

**复现体检**（`repro.py`）

从正文里找出数据集、超参、代码/数据可得性，给一份可复现性判断。

**知乎讨论卡**（`zhihu.py`）

把论文里的概念拿到知乎搜一遍，看有没有人踩过同样的坑。需要知乎开放平台凭证，可选功能，不配也能正常用其它部分。

**本地书库**（`store.py`）

按文件内容哈希索引，保存解析结果、摘要、批注、追问、体检报告。换路径不会丢，同一篇论文在两台机器上解析结果一致。

## 环境

- Python 3.10+
- PyMuPDF **1.26.4**（2.x 的 wheel 在 3.10 上装不了，必须钉这个版本）
- 一个 OpenAI 兼容的模型接口（默认 DeepSeek）

## 快速开始

```bash
git clone https://github.com/KevinLIN719/PaperPrism.git
cd PaperPrism
python -m pip install pymupdf==1.26.4

# 配置模型
copy .env.example .env      # Windows；macOS/Linux 用 cp
# 打开 .env，填上 DEEPSEEK_API_KEY

# 启动
python server.py
```

浏览器打开 <http://127.0.0.1:8765>。把 PDF 放进 `papers/` 目录，或者直接在页面上拖进来（会存到 `papers/imported/`）。

换端口：`set PAPERPRISM_PORT=9000` 再启动。

`.env` 里三个变量：`DEEPSEEK_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。想换成 OpenAI、Kimi、本地 vLLM 都行，只改后两行即可。

### 装不上 PyMuPDF 的情况

把 wheel 解开丢到 `vendor/pymupdf_pkg/`，`m1_parse.py` 和 `server.py` 会自动把这个路径加进 `sys.path`，不需要环境变量。

## 验收

```bash
python tools/check.py
```

退出码 0 才算过。三关：

1. `ruff check .`（规则在 `ruff.toml`，只收「一定是 bug」的规则，不含任何风格规则）
2. 4 篇固定样本的解析冒烟：段数和正文字符数必须与 `tools/check_baseline.json` 完全相等
3. 与 `store/` 里同版本的缓存逐段文本对拍

基线漂移时的正确做法是先判断改动是改好还是改坏，确认之后才更新基线，不许为了让检查变绿去改基线。

改 `PARSE_VERSION` 之前先跑 `python tools/migrate_parse_version.py`，否则书库里已有的摘要和批注会对不上段落号。

## 目录

```
m1_parse.py     PDF → 结构化段落（约 1500 行，核心逻辑都在这）
llm.py          模型调用、分块、摘要、批注、追问检索
server.py       本地 HTTP 服务 + JSON API
store.py        本地书库，按内容哈希索引
repro.py        复现可行性体检
zhihu.py        知乎讨论卡
web/            前端页面（index.html 列表页，reader.html 阅读器）
tools/          审计、回归、迁移、验收脚本
zhihu/          知乎搜索 skill 的参考资料（外部资料，版权归原提供方）
ruff.toml       代码门禁规则
```

API 一览：`/api/health`、`/api/papers`、`/api/parse`、`/api/library`、`/api/open`、`/api/upload`、`/api/store`、`/api/annotate`、`/api/ask`、`/api/repro`、`/api/zhihu`、`/api/forget`、`/api/jump1`。

## 一些设计取舍

- **不建数据库**：书库就是一个目录的 JSON 文件，出问题能直接看、能直接改。
- **按内容哈希而不是路径索引**：文件改名、移动目录都不影响已有摘要和批注。
- **解析器不追求「全能」**：目标是解开大多数单双栏学术 PDF，遇到怪版式宁可少拆不硬拼，宁可留一段长的也不要把两个自然段焊成一段。
- **不用现代前端框架**：两个 HTML 文件 + 原生 JS，改起来不用先跑构建。

## 说明

- 仓库里不含论文语料，`papers/` 和 `*.pdf` 都在 `.gitignore` 里。
- 本项目目前未声明开源许可证。如果要让别人使用或二次分发，建议先补一个（MIT 比较合适）。
