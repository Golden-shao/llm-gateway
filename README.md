# llm-gateway

一个 **OpenAI 兼容的 LLM 网关**：统一认证、限流、日志与流式转发，开箱即用部署到 Kubernetes。

> 一句话：把你的 AI 应用前端统一接到这一个网关，再让它把请求安全地转发给 OpenAI / Anthropic / 任何 OpenAI 兼容上游——客户端永远不碰你的真实上游密钥。

## 特性

- 🔐 **统一认证**：客户端使用网关密钥（`Authorization: Bearer <gateway-key>`），上游真实密钥只存在于服务端。
- ⏱ **令牌桶限流**：按客户端密钥限制每分钟请求数（`GATEWAY_RATE_LIMIT_RPM`）。
- ⚡ **流式透传**：`stream: true` 的 SSE 响应原样透传，低延迟。
- 📊 **结构化日志**：记录时间、客户端哈希、路径、延迟、估算 token。
- ☁️ **K8s 原生**：Helm Chart 一键部署，自带存活/就绪探针、资源限制、HPA 自动扩缩。
- 🚀 **CI/CD**：GitHub Actions 自动测试 + 构建 + 推送 GHCR 镜像。

## 架构

```
┌──────────┐   Bearer <gateway-key>    ┌──────────────────────┐   Bearer <upstream-key>   ┌──────────────┐
│ 客户端 App │ ─────────────────────────▶ │      llm-gateway      │ ───────────────────────▶ │   上游 LLM    │
│ (iOS/Web) │  /v1/chat/completions     │  认证 → 限流 → 转发    │   /v1/chat/completions   │ (OpenAI 等)  │
└──────────┘  stream: true/false        └──────────────────────┘  流式 SSE 透传            └──────────────┘
                                          │  K8s Deployment ×N (HPA 自动扩缩)
                                          ▼
                                    结构化日志 / 健康检查 /v1/models 缓存
```

## 快速开始

### 方式一：本地 Docker

```bash
docker build -t llm-gateway:latest gateway/
# 国内网络：docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple -t llm-gateway:latest gateway/

docker run -d --name llm-gateway -p 8080:8080 \
  -e GATEWAY_UPSTREAM_API_KEY=sk-your-upstream-key \
  -e GATEWAY_GATEWAY_API_KEYS=dev-key \
  llm-gateway:latest

curl http://localhost:8080/healthz
curl -H "Authorization: Bearer dev-key" http://localhost:8080/v1/models
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer dev-key" -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"你好"}]}'
```

### 方式二：Kubernetes + Helm

```bash
# 本地集群（kind）
kind create cluster --name llm-gateway

# 部署
helm install llm-gateway deploy/helm/llm-gateway \
  --set secret.create=true \
  --set secret.upstreamApiKey=sk-your-upstream-key \
  --set secret.gatewayApiKeys=dev-key

# 访问
kubectl port-forward svc/llm-gateway 8080:8080
```

## 配置项（环境变量，前缀 `GATEWAY_`）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `GATEWAY_UPSTREAM_BASE_URL` | `https://api.openai.com/v1` | 上游 OpenAI 兼容地址 |
| `GATEWAY_UPSTREAM_API_KEY` | 空 | 服务端调用上游的密钥 |
| `GATEWAY_GATEWAY_API_KEYS` | 空 | 客户端网关密钥，逗号分隔 |
| `GATEWAY_RATE_LIMIT_RPM` | `60` | 每客户端每分钟请求上限 |
| `GATEWAY_MODELS_CACHE_TTL` | `60` | `/v1/models` 缓存秒数 |

## 目录结构

```
llm-gateway/
├── gateway/              # 网关服务（FastAPI）
│   ├── app/              # 主程序：认证/限流/转发/日志
│   ├── tests/            # 单元测试
│   └── Dockerfile
├── deploy/helm/          # Helm Chart（Deployment/Service/HPA/探针）
├── web/                  # 项目官网（GitHub Pages）
└── .github/workflows/    # CI + Pages
```

## 路线图

- [ ] Redis 分布式限流（跨副本精确限流）
- [ ] 多上游路由（按模型/权重分发）
- [ ] 请求/响应缓存与成本统计
- [ ] Prometheus 指标
- [ ] 管理端 Web 控制台（可配合 Flutter 客户端）

## 开源协议

[MIT](LICENSE)
