# Copyright (c) 2025 OpenClaw-Tracer
# Persist data-URL images as JPEG files and replace URLs with paths relative to output_dir.

from __future__ import annotations

import base64
import copy
import json
import logging
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image

logger = logging.getLogger(__name__)

_DATA_IMAGE_BASE64 = re.compile(
    r"^data:image/(?P<subtype>[\w.+-]+);base64,(?P<payload>.*)$",
    re.DOTALL | re.IGNORECASE,
)


class _ImageIndex:
    __slots__ = ("n",)

    def __init__(self) -> None:
        self.n = 0

    def next(self) -> int:
        v = self.n
        self.n += 1
        return v


def _to_rgb(img: Image.Image) -> Image.Image:
    if img.mode == "RGBA":
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        return background
    if img.mode == "P":
        img = img.convert("RGBA")
        return _to_rgb(img)
    return img.convert("RGB")


def _write_data_url_as_jpeg(
    data_url: str,
    output_dir: Path,
    trace_id: str,
    span_id: str,
    index: _ImageIndex,
) -> Optional[str]:
    m = _DATA_IMAGE_BASE64.match(data_url.strip())
    if not m:
        if data_url.startswith("data:image/") and ";base64," not in data_url:
            logger.warning("Skipping non-base64 data image URL")
        return None

    raw_b64 = m.group("payload")
    try:
        raw = base64.b64decode(raw_b64)
    except Exception as e:
        logger.warning("Invalid base64 in data image URL: %s", e)
        return None

    if not raw:
        logger.warning("Empty payload in data image URL")
        return None

    try:
        img = Image.open(BytesIO(raw))
        rgb = _to_rgb(img)
    except Exception as e:
        logger.warning("Could not decode image for externalize: %s", e)
        return None

    idx = index.next()
    rel = Path("media") / "images" / trace_id / f"{span_id}_{idx}.jpg"
    abs_path = output_dir / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        rgb.save(abs_path, format="JPEG", quality=85)
    except Exception as e:
        logger.warning("Failed to write JPEG %s: %s", abs_path, e)
        return None

    return rel.as_posix()


def _externalize_url(url: str, output_dir: Path, trace_id: str, span_id: str, index: _ImageIndex) -> str:
    if not url.startswith("data:"):
        return url
    replaced = _write_data_url_as_jpeg(url, output_dir, trace_id, span_id, index)
    if replaced is None:
        return url
    return replaced


def _externalize_image_url_obj(
    obj: Dict[str, Any],
    output_dir: Path,
    trace_id: str,
    span_id: str,
    index: _ImageIndex,
) -> None:
    url = obj.get("url")
    if isinstance(url, str):
        obj["url"] = _externalize_url(url, output_dir, trace_id, span_id, index)


def _externalize_content_part(
    part: Dict[str, Any],
    output_dir: Path,
    trace_id: str,
    span_id: str,
    index: _ImageIndex,
) -> None:
    if not isinstance(part, dict):
        return
    ptype = part.get("type")
    if ptype == "image_url" and isinstance(part.get("image_url"), dict):
        _externalize_image_url_obj(part["image_url"], output_dir, trace_id, span_id, index)
    elif ptype == "image_url" and isinstance(part.get("image_url"), str):
        part["image_url"] = _externalize_url(part["image_url"], output_dir, trace_id, span_id, index)


def externalize_message_content(
    content: Any,
    output_dir: Path,
    trace_id: str,
    span_id: str,
    index: _ImageIndex,
) -> Any:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: List[Any] = []
        for item in content:
            if isinstance(item, dict):
                block = copy.deepcopy(item)
                _externalize_content_part(block, output_dir, trace_id, span_id, index)
                out.append(block)
            else:
                out.append(copy.deepcopy(item))
        return out
    if isinstance(content, dict):
        block = copy.deepcopy(content)
        _externalize_content_part(block, output_dir, trace_id, span_id, index)
        return block
    return content


def externalize_inline_images_for_span(
    output_dir: Path,
    trace_id: str,
    span_id: str,
    messages_for_storage: List[Dict[str, Any]],
    system_message: Any,
) -> tuple[List[Dict[str, Any]], Any]:
    """Deep-copy messages and system content; replace data:image base64 URLs with JPEG paths.

    Paths are POSIX strings relative to ``output_dir`` (e.g. ``media/images/...``).
    ``http(s)`` URLs are left unchanged. On decode/write failure the original URL is kept.
    """
    index = _ImageIndex()
    out_messages: List[Dict[str, Any]] = []
    for msg in messages_for_storage:
        m = copy.deepcopy(msg)
        if "content" in m:
            m["content"] = externalize_message_content(
                m["content"], output_dir, trace_id, span_id, index
            )
        out_messages.append(m)

    out_system: Any
    if isinstance(system_message, (str, type(None))):
        out_system = system_message
    else:
        out_system = externalize_message_content(
            system_message, output_dir, trace_id, span_id, index
        )

    return out_messages, out_system


_INLINE_IMAGE_PLACEHOLDER = "<inline_image_base64_redacted>"

_DATA_URL_LOG_RE = re.compile(
    r"data:image/[\w.+-]+;base64,[A-Za-z0-9+/=\r\n]+",
    re.IGNORECASE,
)


def _is_data_image_url(s: str) -> bool:
    return isinstance(s, str) and s.startswith("data:image/") and ";base64," in s


def _redact_url_string(url: str) -> str:
    if _is_data_image_url(url):
        return _INLINE_IMAGE_PLACEHOLDER
    return url


def _redact_content_part_for_log(part: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(part, dict):
        return part
    if part.get("type") != "image_url":
        return part
    iu = part.get("image_url")
    if isinstance(iu, dict) and "url" in iu:
        iu = dict(iu)
        iu["url"] = _redact_url_string(str(iu["url"]))
        part = dict(part)
        part["image_url"] = iu
    elif isinstance(iu, str):
        part = dict(part)
        part["image_url"] = _redact_url_string(iu)
    return part


def _redact_message_content_for_log(content: Any) -> Any:
    if content is None:
        return content
    if isinstance(content, str):
        return _INLINE_IMAGE_PLACEHOLDER if _is_data_image_url(content) else content
    if isinstance(content, list):
        out: List[Any] = []
        for p in content:
            if isinstance(p, dict):
                out.append(_redact_content_part_for_log(copy.deepcopy(p)))
            elif isinstance(p, str) and _is_data_image_url(p):
                out.append(_INLINE_IMAGE_PLACEHOLDER)
            else:
                out.append(p)
        return out
    if isinstance(content, dict):
        return _redact_content_part_for_log(copy.deepcopy(content))
    return content


def redact_data_url_images_in_json_body_for_log(body: str) -> str:
    """Replace ``data:image/...;base64,...`` in chat-style JSON bodies so HTTP logs stay short.

    Parses JSON when possible and walks ``messages[].content`` (multimodal lists). If parsing
    fails, falls back to a regex that strips base64 payloads from data URLs.
    """
    if not body or "data:image" not in body:
        return body
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return _DATA_URL_LOG_RE.sub("data:image/*;base64,<redacted>", body)
    if not isinstance(payload, dict):
        return body
    messages = payload.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if isinstance(msg, dict) and "content" in msg:
                msg["content"] = _redact_message_content_for_log(msg["content"])
    return json.dumps(payload, ensure_ascii=False)
