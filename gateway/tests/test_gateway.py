"""网关核心功能测试：认证、转发、限流。使用 httpx MockTransport 模拟上游。"""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


def make_client() -> TestClient:
    settings = get_settings()
    # 测试注入两个客户端密钥
    settings.gateway_api_keys = "test-key-1,test-key-2"
    settings.upstream_api_key = "upstream-secret"

    calls = []

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer upstream-secret"
        if request.url.path.endswith("/v1/models"):
            return httpx.Response(200, json={"object": "list", "data": [{"id": "gpt-test"}]})
        body = json.loads(request.content)
        if body.get("stream"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n',
            )
        return httpx.Response(200, json={"id": "cmpl-test", "choices": [{"message": {"role": "assistant", "content": "hello"}}]})

    transport = httpx.MockTransport(upstream_handler)
    return TestClient(create_app(transport=transport)), calls


@pytest.fixture()
def client():
    return make_client()


def test_healthz(client):
    c, _ = client
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_unauthorized(client):
    c, _ = client
    r = c.post("/v1/chat/completions", json={"model": "gpt-test", "messages": []})
    assert r.status_code == 401


def test_chat_completion_proxied(client):
    c, calls = client
    r = c.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key-1"},
        json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "hello"
    assert len(calls) == 1


def test_streaming_proxied(client):
    c, _ = client
    r = c.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key-2"},
        json={"model": "gpt-test", "messages": [], "stream": True},
    )
    assert r.status_code == 200
    assert "data:" in r.text
    assert "[DONE]" in r.text


def test_rate_limit(client):
    settings = get_settings()
    old = settings.rate_limit_rpm
    settings.rate_limit_rpm = 3
    try:
        c, _ = client
        headers = {"Authorization": "Bearer test-key-1"}
        for _ in range(3):
            r = c.post("/v1/chat/completions", headers=headers, json={"model": "gpt-test", "messages": []})
            assert r.status_code == 200
        r = c.post("/v1/chat/completions", headers=headers, json={"model": "gpt-test", "messages": []})
        assert r.status_code == 429
    finally:
        settings.rate_limit_rpm = old


def test_models_list(client):
    c, _ = client
    r = c.get("/v1/models", headers={"Authorization": "Bearer test-key-1"})
    assert r.status_code == 200
    assert r.json()["data"][0]["id"] == "gpt-test"
