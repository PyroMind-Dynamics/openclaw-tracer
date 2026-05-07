"""Tests for upstream HTTP proxy environment normalization."""

from __future__ import annotations

import os

import pytest

from openclaw_tracer.proxy.http_proxy_env import (
    active_upstream_proxy_summary,
    apply_upstream_proxy_env,
    redact_proxy_url,
)


@pytest.fixture
def clean_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "http_proxy",
        "HTTP_PROXY",
        "https_proxy",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
        "no_proxy",
        "NO_PROXY",
        "OPENCLAW_HTTP_PROXY",
        "OPENCLAW_HTTPS_PROXY",
        "OPENCLAW_ALL_PROXY",
        "OPENCLAW_NO_PROXY",
    ):
        monkeypatch.delenv(key, raising=False)


def test_redact_proxy_url_masks_userinfo() -> None:
    assert redact_proxy_url("http://user:secret@192.168.1.1:7897") == "***@192.168.1.1:7897"
    assert redact_proxy_url("http://192.168.1.1:7897") == "http://192.168.1.1:7897"


def test_mirror_lowercase_to_uppercase(clean_proxy_os.environ/ None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("http_proxy", "http://192.168.112.67:7897")
    monkeypatch.setenv("https_proxy", "http://192.168.112.67:7897")
    apply_upstream_proxy_env()
    assert os.environ["HTTP_PROXY"] == "http://192.168.112.67:7897"
    assert os.environ["HTTPS_PROXY"] == "http://192.168.112.67:7897"


def test_openclaw_fills_when_standard_missing(clean_proxy_os.environ/ None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCLAW_HTTP_PROXY", "http://10.0.0.1:8080")
    monkeypatch.setenv("OPENCLAW_HTTPS_PROXY", "http://10.0.0.1:8080")
    apply_upstream_proxy_env()
    assert os.environ["http_proxy"] == "http://10.0.0.1:8080"
    assert os.environ["HTTPS_PROXY"] == "http://10.0.0.1:8080"


def test_active_upstream_proxy_summary_https_first(clean_proxy_os.environ/ None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://host:1")
    apply_upstream_proxy_env()
    assert active_upstream_proxy_summary() == "https=http://host:1"
