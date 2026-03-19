"""LLM client for the sensemaking agent.

Provides a thin async text-generation interface over Ollama and
OpenAI-compatible REST APIs.  Network calls are executed in a thread
executor so the async event loop is never blocked.

Adapted from V1 patterns (AI-Driven-Autonomous-Research-Agent llm_client.py)
with a focused interface matching V2 needs.

No graph logic, contradiction logic, or orchestration state belongs here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_OLLAMA_URL = "http://localhost:11434"
_DEFAULT_OPENAI_URL = "https://api.openai.com/v1"


def _normalize_provider(provider: str) -> str:
    v = (provider or "ollama").strip().lower()
    if v in {"openai-compatible", "openai_compatible", "siliconflow", "online"}:
        return "openai"
    return v


def _read_json(req: urllib.request.Request, timeout: int) -> dict:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data if isinstance(data, dict) else {}


def _call_ollama_sync(
    prompt: str,
    model: str,
    base_url: str,
    timeout: int,
) -> Optional[str]:
    payload = json.dumps(
        {"model": model, "prompt": prompt, "stream": False}
    ).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        data = _read_json(req, timeout)
        response = data.get("response")
        return response if isinstance(response, str) else ""
    except urllib.error.HTTPError as exc:
        logger.warning("Ollama call failed (HTTP %d): %s", exc.code, exc)
        return None
    except Exception as exc:
        logger.warning("Ollama call failed: %s", exc)
        return None


def _call_openai_sync(
    prompt: str,
    model: str,
    base_url: str,
    api_key: str,
    timeout: int,
) -> Optional[str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
    ).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers=headers,
        method="POST",
    )
    try:
        data = _read_json(req, timeout)
        choices = data.get("choices") or []
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get("message") or {}
            content = msg.get("content")
            return content if isinstance(content, str) else ""
        return ""
    except urllib.error.HTTPError as exc:
        logger.warning("OpenAI-compatible call failed (HTTP %d): %s", exc.code, exc)
        return None
    except Exception as exc:
        logger.warning("OpenAI-compatible call failed: %s", exc)
        return None


def generate_text_sync(
    prompt: str,
    model: str,
    base_url: str = _DEFAULT_OLLAMA_URL,
    provider: str = "ollama",
    api_key: str = "",
    timeout: int = 120,
) -> Optional[str]:
    """Synchronous LLM text generation.

    Returns the generated text string, an empty string on known API errors, or
    ``None`` when the call fails entirely.
    """
    norm = _normalize_provider(provider)
    if norm == "openai":
        return _call_openai_sync(prompt, model, base_url, api_key, timeout)
    return _call_ollama_sync(prompt, model, base_url, timeout)


async def generate_text(
    prompt: str,
    model: str,
    base_url: str = _DEFAULT_OLLAMA_URL,
    provider: str = "ollama",
    api_key: str = "",
    timeout: int = 120,
) -> Optional[str]:
    """Async LLM text generation — runs the synchronous call in a thread executor.

    Returns the generated text string, an empty string on known API errors, or
    ``None`` when the call fails entirely.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        generate_text_sync,
        prompt,
        model,
        base_url,
        provider,
        api_key,
        timeout,
    )
