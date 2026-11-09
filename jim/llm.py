"""One client for every provider.

Ollama, LM Studio, Groq, Gemini, Cerebras, OpenRouter, Mistral, GitHub Models,
Together, DeepSeek, Hugging Face router ... all speak the OpenAI
`/chat/completions` format, so a single client covers them. To add a new LLM you
only need its base URL, a model id and (usually) an API key.
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)


class LLMError(Exception):
    pass


def _headers(p: dict) -> dict:
    h = {"Content-Type": "application/json"}
    if p.get("api_key"):
        h["Authorization"] = f"Bearer {p['api_key']}"
    if "openrouter.ai" in p.get("base_url", ""):
        h["HTTP-Referer"] = "http://localhost"
        h["X-Title"] = "JIM Assistant"
    return h


def _url(p: dict, path: str) -> str:
    return p["base_url"].rstrip("/") + path


def _body(p: dict, messages: list[dict], temperature: float, max_tokens: int, stream: bool) -> dict:
    return {
        "model": p["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream,
    }


def _err(p: dict, r: httpx.Response) -> LLMError:
    try:
        detail = r.json()
        detail = detail.get("error", detail)
        if isinstance(detail, dict):
            detail = detail.get("message", json.dumps(detail))
    except Exception:
        detail = r.text[:300]
    return LLMError(f"{p['name']}: HTTP {r.status_code} - {detail}")


def _conn_err(p: dict, e: Exception) -> LLMError:
    if isinstance(e, httpx.ConnectError):
        hint = " Is Ollama installed and running? (ollama.com)" if "11434" in p["base_url"] else \
               " Is LM Studio's server started?" if "1234" in p["base_url"] else " Check the base URL / internet."
        return LLMError(f"{p['name']}: can't connect to {p['base_url']}.{hint}")
    if isinstance(e, httpx.TimeoutException):
        return LLMError(f"{p['name']}: timed out.")
    return LLMError(f"{p['name']}: {type(e).__name__} {e}")


async def complete(p: dict, messages: list[dict], temperature=0.7, max_tokens=1024) -> str:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        try:
            r = await c.post(_url(p, "/chat/completions"), headers=_headers(p),
                             json=_body(p, messages, temperature, max_tokens, False))
        except httpx.HTTPError as e:
            raise _conn_err(p, e) from e
        if r.status_code >= 400:
            raise _err(p, r)
        data = r.json()
        try:
            return (data["choices"][0]["message"].get("content") or "").strip()
        except (KeyError, IndexError) as e:
            raise LLMError(f"{p['name']}: unexpected response {str(data)[:200]}") from e


async def stream(p: dict, messages: list[dict], temperature=0.7, max_tokens=1024) -> AsyncIterator[str]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        try:
            async with c.stream("POST", _url(p, "/chat/completions"), headers=_headers(p),
                                json=_body(p, messages, temperature, max_tokens, True)) as r:
                if r.status_code >= 400:
                    await r.aread()
                    raise _err(p, r)
                async for line in r.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                        delta = chunk["choices"][0].get("delta", {}).get("content")
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    if delta:
                        yield delta
        except httpx.HTTPError as e:
            raise _conn_err(p, e) from e


async def list_models(p: dict) -> list[str]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as c:
        r = await c.get(_url(p, "/models"), headers=_headers(p))
        if r.status_code >= 400:
            raise _err(p, r)
        data = r.json()
        items = data.get("data", data if isinstance(data, list) else data.get("models", []))
        ids = []
        for m in items:
            mid = m.get("id") or m.get("name") if isinstance(m, dict) else m
            if mid:
                ids.append(str(mid).removeprefix("models/"))
        # free OpenRouter models first
        return sorted(set(ids), key=lambda x: (":free" not in x, x))


async def test(p: dict) -> str:
    return await complete(p, [{"role": "user", "content": "Reply with exactly: online"}],
                          temperature=0, max_tokens=10)
