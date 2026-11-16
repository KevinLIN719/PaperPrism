# 部署到 Railway（演示实例）

> 这份文档只做一件事：把 PaperPrism 变成一个**公网可访问的演示链接**。
> 与本地形态的差别只有两点：①容器里 `papers/` 只有 4 篇固定论文；②页面顶部常驻一句「PDF 会留在这台服务器上」。
> 全程约 15 分钟，不需要改代码。

---

## 0. 你需要准备

| 需要 | 说明 |
|---|---|
| Railway 账号 + 额度 | 你已有 $5 额度。**Railway 的额度只付服务器**，模型调用走你自己的 DeepSeek key，另算。 |
| GitHub 仓库 | 代码要能被 Railway 拉取。当前本地 `master` 已 commit，push 需要你在自己终端执行（沙箱内 push 会失败）。 |
| DeepSeek API key | 填进 Railway 变量，不放仓库、不放进镜像。 |

**模型费用**：单篇约 $0.007（解析免费，摘要 + 全篇批注才花）。演示时点 4 篇全跑一遍 ≈ $0.03；$5 的 DeepSeek 额度够跑几百篇。

---

## 1. push 代码（你自己终端里执行）

```bash
cd D:\Projects\PaperPrism
git push
```

确认 `demo_papers/` 那 4 篇（约 4MB）进了仓库：

```bash
git ls-files demo_papers
# 应该看到 4 个 .pdf
```

> 这 4 篇都是 arXiv / NBER 公开论文，放公开仓库没问题。
> 如果不想让它们进公开仓库，备选是部署后在 Railway 的终端里 `curl` 下载——但那条路要多做脚本，不推荐。

---

## 2. 在 Railway 建项目

1. https://railway.app/new → **Deploy from GitHub repo** → 选 PaperPrism 仓库。
2. 它会自动发现根目录的 `Dockerfile`（本仓库已带）。
3. 部署开始后先不管它，去第 3 步填变量。

---

## 3. 填环境变量（Variables）

在项目 → 服务 → **Variables** 里加：

| 变量 | 值 | 说明 |
|---|---|---|
| `LLM_API_KEY` | 你的 DeepSeek key | 必填，否则摘要/批注会报「请先填 key」 |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | 默认就是这个，可省 |
| `LLM_MODEL` | `deepseek-chat` | 默认就是这个，可省 |
| `PAPERPRISM_DEMO` | `1` | **必填**：显示演示说明条 + 锁掉访客改模型设置 |
| `ZHIHU_ACCESS_SECRET` | 你的知乎 token | 可选；不填则知乎标签显示「未配置」而不会报错 |

> `PORT` 不用填，Railway 会注入，`server.py` 已优先读它。

---

## 4. 开公网域名

项目 → 服务 → **Settings → Networking → Generate Domain**。

拿到类似 `paperprism-production.up.railway.app` 的地址，浏览器打开应该看到：

- 顶部黄条：「这是一台演示实例：你上传的 PDF 会留在这台服务器上……」
- 下拉框里只有 4 篇：`resnet_1512.03385.pdf`、`attention_1706.03762.pdf`、`science.1133687.pdf`、`c4_nber_w31161.pdf`
- 顶栏**没有**「设置」按钮（演示实例锁掉了，防止访客换 key）

---

## 5. 上线前的自检清单

| 检查 | 期望 |
|---|---|
| 打开首页 | 有黄条、有 4 篇论文、无设置按钮 |
| 点「解析」 | 2–4 s 出页面，段落可点 |
| 点「重跑摘要」 | 5–20 s 出摘要，页脚显示 `模型 deepseek-chat · tokens … · 成本 ≈$0.00x` |
| 拖入篇外论文 | 能解析（演示实例允许上传，但会占服务器空间；评审期够了） |
| `curl https://<域名>/api/health` | `{"ok":true,"demo":true,...}` |

---

## 6. 已知限制（演示实例特有，评审前先说清）

1. **文件留存**：演示实例上 PDF 会存在容器里。页面已常驻说明；正式形态是本机运行、PDF 不上传。
2. **缓存是临时的**：Railway 容器重建（重新部署/重启）后 `store/` 会清空，之前生成的摘要与批注会丢——**重新点一次会再花一次模型钱**（每篇 $0.007 量级）。评审期固定 4 篇，问题不大。
3. **没有数据库**：书库就是容器里的 JSON 文件，这是产品本身的取舍（本地优先），不是部署妥协。
4. **额度**：$5 额度按容器常驻时间扣，具体以 Railway 的 Usage 页为准；演示期结束后把服务暂停（Pause）即可停止扣费。

---

## 7. 排障

| 现象 | 原因 | 处理 |
|---|---|---|
| 打开是 502 / Application failed to respond | 服务没监听 `0.0.0.0` 或端口没用 `$PORT` | 本仓库 `server.py` 已用 `PAPERPRISM_HOST`（Dockerfile 设为 `0.0.0.0`）和 `PORT`，确认 Dockerfile 没被改动 |
| 解析报 `No module named pymupdf` | 镜像没装依赖 | `requirements.txt` / Dockerfile 里 `pymupdf==1.26.4` 要保留 |
| 摘要报 401 | key 没填或填错 | Railway Variables 里改 `LLM_API_KEY`，改完会自动重新部署 |
| 构建很慢 | 无缓存首次构建 | 正常，第二次起有层缓存 |

---

## 8. 本地先验证镜像（可选，但建议）

装了 Docker 的话，先本地跑一遍，避免上线才发现问题：

```bash
docker build -t paperprism-demo .
docker run --rm -p 8788:8765 -e PORT=8765 -e LLM_API_KEY=sk-xxx -e PAPERPRISM_DEMO=1 paperprism-demo
# 打开 http://127.0.0.1:8788/
```
