"""llm-gateway：OpenAI 兼容的 LLM 网关。

职责：
  1. 认证：客户端必须携带 GATEWAY_GATEWAY_API_KEYS 中的某个密钥。
  2. 限流：按客户端密钥做令牌桶限流（每分钟 RPM）。
  3. 转发：把 /v1/chat/completions（含流式 SSE）与 /v1/models 转发到上游，
     网关本身不持有客户端真实上游密钥。
  4. 日志：记录时间、客户端、模型、估算 token、耗时。
"""
import hashlib
import logging
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from .config import get_settings
from .ratelimit import RateLimiter

logger = logging.getLogger("llm-gateway")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def _hash_key(key: str) -> str:
    """只记录密钥的短哈希，不落盘明文。"""
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _estimate_tokens(text_len: int) -> int:
    """粗略估算：中文约 1.6 字符/token，英文约 4 字符/token。仅用于日志。"""
    return max(1, int(text_len / 2.5))


class Gateway:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = get_settings()
        self.limiter = RateLimiter(self.settings.rate_limit_rpm)
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=10.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        self._models_cache: dict[str, tuple[float, dict]] = {}

    async def close(self) -> None:
        await self._client.aclose()

    def _upstream_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.upstream_api_key:
            headers["Authorization"] = f"Bearer {self.settings.upstream_api_key}"
        return headers

    def _check_auth(self, request: Request) -> str | None:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            key = auth[7:].strip()
            if key in self.settings.allowed_keys:
                return key
        return None

    async def _forward(self, request: Request) -> Response:
        """转发到上游。流式请求做 SSE 透传，非流式直接返回 JSON。"""
        body = await request.body()
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        stream = bool(payload.get("stream", False))
        path = request.url.path  # 例如 /v1/chat/completions
        upstream_url = self.settings.upstream_base_url.rstrip("/") + path
        started = time.monotonic()

        if stream:
            req = self._client.build_request(
                "POST", upstream_url, headers=self._upstream_headers(), content=body
            )
            resp = await self._client.send(req, stream=True)

            async def event_source():
                try:
                    async for chunk in resp.aiter_raw():
                        yield chunk
                finally:
                    await resp.aclose()

            return StreamingResponse(
                event_source(),
                status_code=resp.status_code,
                media_type=resp.headers.get("content-type", "text/event-stream"),
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        resp = await self._client.post(upstream_url, headers=self._upstream_headers(), content=body)
        elapsed = time.monotonic() - started
        logger.info(
            "proxy %s status=%s latency=%.3fs est_tokens=%d client=%s stream=False",
            path, resp.status_code, elapsed, _estimate_tokens(len(body)), _hash_key("?"),
        )
        return Response(content=resp.content, status_code=resp.status_code,
                        media_type=resp.headers.get("content-type", "application/json"))

    async def models(self) -> Response:
        now = time.monotonic()
        if self._models_cache:
            ts, cached = self._models_cache.get("models", (0, {}))
            if now - ts < self.settings.models_cache_ttl:
                return JSONResponse(cached)
        resp = await self._client.get(
            self.settings.upstream_base_url.rstrip("/") + "/models",
            headers=self._upstream_headers(),
        )
        if resp.status_code == 200:
            data = resp.json()
            self._models_cache["models"] = (now, data)
            return JSONResponse(data)
        return Response(content=resp.content, status_code=resp.status_code,
                        media_type="application/json")


def create_app(transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = get_settings()
    gateway = Gateway(transport=transport)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await gateway.close()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "app": settings.app_name}

    @app.get("/v1/models")
    async def models(request: Request):
        key = gateway._check_auth(request)
        if key is None:
            return JSONResponse({"error": {"message": "unauthorized"}}, status_code=401)
        return await gateway.models()

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        key = gateway._check_auth(request)
        if key is None:
            return JSONResponse({"error": {"message": "unauthorized"}}, status_code=401)
        if not gateway.limiter.allow(key):
            return JSONResponse(
                {"error": {"message": f"rate limit exceeded: {settings.rate_limit_rpm} rpm"}},
                status_code=429,
            )
        started = time.monotonic()
        response = await gateway._forward(request)
        elapsed = time.monotonic() - started
        logger.info("req client=%s path=%s latency=%.3fs", _hash_key(key), request.url.path, elapsed)
        return response

    return app


app = create_app()
