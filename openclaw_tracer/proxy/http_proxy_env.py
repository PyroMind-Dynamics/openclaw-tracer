# Copyright (c) 2025 OpenClaw-Tracer
"""Normalize HTTP(S) proxy environment variables for upstream LLM calls.

LiteLLM uses httpx with ``trust_env=True`` by default; outbound requests honor
standard proxy variables. Different stacks expect ``http_proxy`` vs ``HTTP_PROXY``
— we mirror both forms and support optional ``OPENCLAW_*`` overrides for .env-only setups.
"""

from __future__ import annotations

import os
from typing import Iterable, Mapping, MutableMapping, Optional, Tuple

_ProxyPair = Tuple[str, str]

_PROXY_PAIRS: Tuple[_ProxyPair, ...] = (
    ("http_proxy", "HTTP_PROXY"),
    ("https_proxy", "HTTPS_PROXY"),
    ("all_proxy", "ALL_PROXY"),
    ("no_proxy", "NO_PROXY"),
)


def redact_proxy_url(url: str) -> str:
    """Hide userinfo in proxy URLs for logs."""
    if not url or "@" not in url:
        return url
    _, _, tail = url.rpartition("@")
    return f"***@{tail}"


def _mirror_pairs(environ: MutableMapping[str, str], pairs: Iterable[_ProxyPair]) -> None:
    for lower, upper in pairs:
        low = environ.get(lower)
        up = environ.get(upper)
        if low and not up:
            environ[upper] = low
        elif up and not low:
            environ[lower] = up


def _apply_openclaw_defaults(environ: MutableMapping[str, str]) -> None:
    """Fill standard proxy keys from OPENCLAW_* when globals are unset."""
    oc_http = environ.get("OPENCLAW_HTTP_PROXY")
    oc_https = environ.get("OPENCLAW_HTTPS_PROXY")
    oc_all = environ.get("OPENCLAW_ALL_PROXY")
    oc_no = environ.get("OPENCLAW_NO_PROXY")

    def _missing_http() -> bool:
        return not environ.get("http_proxy") and not environ.get("HTTP_PROXY")

    def _missing_https() -> bool:
        return not environ.get("https_proxy") and not environ.get("HTTPS_PROXY")

    def _missing_all() -> bool:
        return not environ.get("all_proxy") and not environ.get("ALL_PROXY")

    def _missing_no() -> bool:
        return not environ.get("no_proxy") and not environ.get("NO_PROXY")

    if oc_http and _missing_http():
        environ["http_proxy"] = oc_http
        environ["HTTP_PROXY"] = oc_http
    if oc_https and _missing_https():
        environ["https_proxy"] = oc_https
        environ["HTTPS_PROXY"] = oc_https
    if oc_all and _missing_all():
        environ["all_proxy"] = oc_all
        environ["ALL_PROXY"] = oc_all
    if oc_no and _missing_no():
        environ["no_proxy"] = oc_no
        environ["NO_PROXY"] = oc_no


def active_upstream_proxy_summary(environ: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Return a one-line summary if any upstream proxy is configured, else None."""
    env = environ if environ is not None else os.environ
    https = env.get("HTTPS_PROXY") or env.get("https_proxy")
    http = env.get("HTTP_PROXY") or env.get("http_proxy")
    if https:
        return f"https={redact_proxy_url(https)}"
    if http:
        return f"http={redact_proxy_url(http)}"
    all_p = env.get("ALL_PROXY") or env.get("all_proxy")
    if all_p:
        return f"all={redact_proxy_url(all_p)}"
    return None


def apply_upstream_proxy_env(environ: Optional[MutableMapping[str, str]] = None) -> None:
    """Mirror proxy-related env vars and apply OPENCLAW_* defaults.

    Safe to call multiple times (idempotent given stable inputs).
    Modifies ``os.environ`` by default.
    """
    target: MutableMapping[str, str] = environ if environ is not None else os.environ
    _apply_openclaw_defaults(target)
    _mirror_pairs(target, _PROXY_PAIRS)
