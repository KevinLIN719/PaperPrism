# PaperPrism 演示实例：Railway / 任意支持 Docker 的平台
# 与本地形态的唯一差别：容器里 papers/ 只有 demo_papers/ 那几篇固定的公开论文。
FROM python:3.10-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PAPERPRISM_HOST=0.0.0.0 \
    PAPERPRISM_DEMO=1

# 解析层依赖；1.26.4 是最后一个提供 cp39-abi3 轮子的版本，3.10 可用
RUN pip install --no-cache-dir pymupdf==1.26.4

COPY server.py llm.py m1_parse.py repro.py store.py zhihu.py ./
COPY web ./web
COPY demo_papers ./papers
RUN mkdir -p /app/papers/imported /app/store

# Railway 会注入 $PORT，server.py 已优先读 PORT
EXPOSE 8765
CMD ["python", "server.py"]
