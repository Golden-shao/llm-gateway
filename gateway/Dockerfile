# 构建：docker build -t llm-gateway:latest gateway/
# 国内网络可传镜像源：docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple -t llm-gateway:latest gateway/
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ARG PIP_INDEX_URL=https://pypi.org/simple

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i ${PIP_INDEX_URL}

COPY app ./app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
