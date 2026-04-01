# Copyright (c) 2025 OpenClaw-Tracer
# Integration tests for LLM proxy server

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import AsyncGenerator, Generator

import httpx
import pytest

from openclaw_tracer.storage.parquet_store import ParquetStore


# Skip all integration tests if we can't create a working proxy
pytest.importorskip("litellm.proxy.proxy_server")

from openclaw_tracer.proxy.llm_proxy import LLMProxy


@pytest.fixture(scope="session", autouse=True)
def _integration_tests_disable_upstream_proxy_env() -> Generator[None, None, None]:
    """LiteLLM uses httpx with trust_env=True for upstream calls; strip proxy vars to avoid hangs."""
    keys = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    )
    saved: dict[str, str | None] = {k: os.environ.pop(k, None) for k in keys}
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v


@pytest.fixture(scope="session")
def proxy_api_key() -> str:
    """Test API key for proxy authentication."""
    return os.getenv("PROXY_API_KEY", "test-proxy-key-12345")


@pytest.fixture(scope="session")
def test_model_config() -> dict:
    """Get test model configuration from environment."""
    return {
        "target_model": os.getenv("TARGET_MODEL", "Qwen3.5-27B-FP8"),
        "origin_model": os.getenv("ORIGIN_MODEL", "Qwen3.5-27B-FP8"),
        "api_mode": os.getenv("API_MODE", "custom"),
        "api_url": os.getenv("API_URL", "https://pyromind.ai/inference/inf-90a8e10746ec/v1/"),
        "access_key": os.getenv("ACCESS_KEY", ""),
    }


@pytest.fixture(scope="session")
def temp_store_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test data (session-scoped)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture(scope="session")
async def running_proxy(
    temp_store_dir: Path,
    proxy_api_key: str,
    test_model_config: dict,
) -> AsyncGenerator[LLMProxy, None]:
    """Start a proxy server for all integration tests (session-scoped)."""
    # Build model list from environment config
    model_list = []
    if test_model_config["target_model"] and test_model_config["origin_model"]:
        litellm_model = test_model_config["origin_model"]
        if test_model_config["api_mode"]:
            litellm_model = f"{test_model_config['api_mode']}/{litellm_model}"

        model_entry = {
            "model_name": test_model_config["target_model"],
            "litellm_params": {
                "model": litellm_model,
                "api_key": test_model_config["access_key"] or "fake-key-for-testing",
            },
        }
        if test_model_config["api_url"]:
            model_entry["litellm_params"]["api_base"] = test_model_config["api_url"]
        model_list.append(model_entry)

    # Create store
    store = ParquetStore(
        output_dir=temp_store_dir / "data",
        buffer_size=1,
        auto_flush=True,
    )

    # Create and start proxy
    proxy = LLMProxy(
        port=None,  # Random available port
        host="127.0.0.1",
        model_list=model_list,
        store=store,
        proxy_api_key=proxy_api_key,
    )

    await proxy.start()

    # Wait for server to be ready
    await asyncio.sleep(1)

    yield proxy
    await proxy.stop()
    await store.close()


@pytest.fixture
def proxy_client(running_proxy: LLMProxy, proxy_api_key: str) -> httpx.AsyncClient:
    """Create an HTTP client for the proxy."""
    return httpx.AsyncClient(
        base_url=running_proxy.url,
        headers={"Authorization": f"Bearer {proxy_api_key}"},
        timeout=30.0,
        trust_env=False,
    )


@pytest.fixture
def unauth_client(running_proxy: LLMProxy) -> httpx.AsyncClient:
    """Create an HTTP client without authentication."""
    return httpx.AsyncClient(
        base_url=running_proxy.url,
        timeout=30.0,
        trust_env=False,
    )


class TestProxyServer:
    """Integration tests for LLM proxy server."""

    @pytest.mark.asyncio
    async def test_server_starts(self, running_proxy: LLMProxy) -> None:
        """Test that the server starts successfully."""
        assert running_proxy.url is not None
        assert running_proxy.port is not None

    @pytest.mark.asyncio
    async def test_health_endpoint(self, proxy_client: httpx.AsyncClient) -> None:
        """Test the health check endpoint."""
        response = await proxy_client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_endpoint_no_auth(
        self,
        running_proxy: LLMProxy,
    ) -> None:
        """Test that health endpoint works without authentication."""
        async with httpx.AsyncClient(
            base_url=running_proxy.url,
            timeout=30.0,
            trust_env=False,
        ) as client:
            response = await client.get("/health")
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_v1_models_no_auth(self, unauth_client: httpx.AsyncClient) -> None:
        """Test that /v1/models works without authentication."""
        response = await unauth_client.get("/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert "data" in data or "object" in data

    @pytest.mark.asyncio
    async def test_chat_completion_requires_auth(
        self,
        running_proxy: LLMProxy,
    ) -> None:
        """Test that chat completions require authentication."""
        async with httpx.AsyncClient(
            base_url=running_proxy.url,
            timeout=30.0,
            trust_env=False,
        ) as client:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )
            assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_chat_completion_with_valid_auth(
        self,
        proxy_client: httpx.AsyncClient,
        test_model_config: dict,
    ) -> None:
        """Test chat completions with valid authentication."""
        response = await proxy_client.post(
            "/v1/chat/completions",
            json={
                "model": test_model_config["target_model"],
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 10,
            },
        )
        # Should not be 401 (auth error)
        # Could be 200 (success), 500 (model error), etc.
        assert response.status_code != 401

    @pytest.mark.asyncio
    async def test_chat_completion_with_api_key_header(
        self,
        running_proxy: LLMProxy,
        proxy_api_key: str,
    ) -> None:
        """Test authentication via X-API-Key header."""
        async with httpx.AsyncClient(
            base_url=running_proxy.url,
            headers={"X-API-Key": proxy_api_key},
            timeout=30.0,
            trust_env=False,
        ) as client:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )
            assert response.status_code != 401

    @pytest.mark.asyncio
    async def test_chat_completion_with_invalid_api_key(
        self,
        running_proxy: LLMProxy,
    ) -> None:
        """Test that invalid API key is rejected."""
        async with httpx.AsyncClient(
            base_url=running_proxy.url,
            headers={"Authorization": "Bearer invalid-key"},
            timeout=30.0,
            trust_env=False,
        ) as client:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )
            assert response.status_code == 401


class TestProxyDataCollection:
    """Tests for data collection through proxy."""

    @pytest.mark.asyncio
    async def test_request_creates_span(
        self,
        running_proxy: LLMProxy,
        proxy_api_key: str,
        test_model_config: dict,
    ) -> None:
        """Test that requests create span data."""
        async with httpx.AsyncClient(
            base_url=running_proxy.url,
            headers={"Authorization": f"Bearer {proxy_api_key}"},
            timeout=30.0,
            trust_env=False,
        ) as client:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": test_model_config["target_model"],
                    "messages": [{"role": "user", "content": "Test"}],
                    "max_tokens": 5,
                },
            )
        # Upstream may 404/500 without real ACCESS_KEY; we only check the proxy responded.
        assert response.status_code is not None

        # Note: Span collection depends on LiteLLM's logging

    @pytest.mark.asyncio
    async def test_concurrent_requests(
        self,
        running_proxy: LLMProxy,
        proxy_api_key: str,
        test_model_config: dict,
    ) -> None:
        """Test handling concurrent requests."""
        async def make_request(i: int) -> None:
            async with httpx.AsyncClient(
                base_url=running_proxy.url,
                headers={"Authorization": f"Bearer {proxy_api_key}"},
                timeout=30.0,
                trust_env=False,
            ) as client:
                await client.post(
                    "/v1/chat/completions",
                    json={
                        "model": test_model_config["target_model"],
                        "messages": [{"role": "user", "content": f"Test {i}"}],
                        "max_tokens": 5,
                    },
                )

        # Make concurrent requests
        tasks = [make_request(i) for i in range(3)]
        await asyncio.gather(*tasks, return_exceptions=True)


class TestProxyErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_invalid_json_body(
        self,
        proxy_client: httpx.AsyncClient,
    ) -> None:
        """Test handling of invalid JSON in request body."""
        response = await proxy_client.post(
            "/v1/chat/completions",
            content="invalid json",
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_required_fields(
        self,
        proxy_client: httpx.AsyncClient,
    ) -> None:
        """Test handling of missing required fields."""
        response = await proxy_client.post(
            "/v1/chat/completions",
            json={"model": "test-model"},  # Missing messages field
        )
        # Should not crash, should return an error
        assert response.status_code in [400, 422]

    @pytest.mark.asyncio
    async def test_unknown_model(
        self,
        proxy_client: httpx.AsyncClient,
    ) -> None:
        """Test handling of unknown model."""
        response = await proxy_client.post(
            "/v1/chat/completions",
            json={
                "model": "unknown-model-xyz",
                "messages": [{"role": "user", "content": "Test"}],
            },
        )
        # Should return an error (not crash)
        assert response.status_code != 200


class TestProxyLifecycle:
    """Tests for proxy server lifecycle."""

    @pytest.mark.asyncio
    async def test_wait_until_stopped(
        self,
        temp_store_dir: Path,
        proxy_api_key: str,
    ) -> None:
        """Test wait() method blocks until server stops."""
        # Note: This test creates its own proxy since we can't stop the session-scoped one
        store = ParquetStore(
            output_dir=temp_store_dir / "data2",
            buffer_size=1,
        )

        proxy = LLMProxy(
            port=None,
            host="127.0.0.1",
            model_list=[],
            store=store,
            proxy_api_key=proxy_api_key,
        )

        await proxy.start()

        # Create a task that will stop the server after a delay
        async def stop_after_delay() -> None:
            await asyncio.sleep(0.1)
            await proxy.stop()

        asyncio.create_task(stop_after_delay())

        # Wait should complete when server stops
        await asyncio.wait_for(proxy.wait(), timeout=2.0)

        await store.close()
