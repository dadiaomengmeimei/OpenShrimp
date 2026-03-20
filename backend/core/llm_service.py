"""
Shared LLM service – wraps OpenAI-compatible API for all sub-apps.
"""
from __future__ import annotations

import json
from typing import AsyncIterator, Optional

from openai import AsyncOpenAI

from backend.config import llm_settings


def _get_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=llm_settings.api_key or "sk-placeholder",
        base_url=llm_settings.api_base,
    )


async def chat_completion(
    messages: list[dict],
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    stream: bool = False,
    extra_body: Optional[dict] = None,
    tools: Optional[list[dict]] = None,
    return_raw_message: bool = False,
) -> str | AsyncIterator[str]:
    """Send a chat completion request.

    When *return_raw_message* is True **and** tools are provided, returns the
    raw OpenAI ChatCompletionMessage object so callers can inspect tool_calls.
    Otherwise returns plain text (or an async iterator when streaming).
    """
    client = _get_client()
    # kimi-k2.5 only allows temperature=1; force override any caller value
    effective_temp = llm_settings.temperature
    params = dict(
        model=model or llm_settings.model,
        messages=messages,
        temperature=effective_temp,
        max_tokens=max_tokens or llm_settings.max_tokens,
        stream=stream,
    )

    # Only add extra_body if explicitly provided (Kimi doesn't need qwen-specific params)
    if extra_body:
        params["extra_body"] = extra_body

    # Pass tools if provided (for function calling)
    if tools:
        params["tools"] = tools
        params["tool_choice"] = "auto"

    if stream:
        return _stream(client, params)

    resp = await client.chat.completions.create(**params)
    msg = resp.choices[0].message

    # When caller needs the raw message (e.g. code_agent for tool_calls)
    if return_raw_message and tools:
        return msg

    return msg.content or ""


async def _stream(client: AsyncOpenAI, params: dict) -> AsyncIterator[str]:
    resp = await client.chat.completions.create(**params)
    async for chunk in resp:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content


async def function_call(
    messages: list[dict],
    tools: list[dict],
    *,
    model: Optional[str] = None,
) -> dict:
    """Execute a function-calling request and return the tool call result."""
    client = _get_client()
    resp = await client.chat.completions.create(
        model=model or llm_settings.model,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        temperature=llm_settings.temperature,
    )
    msg = resp.choices[0].message
    if msg.tool_calls:
        tc = msg.tool_calls[0]
        return {
            "name": tc.function.name,
            "arguments": json.loads(tc.function.arguments),
        }
    return {"name": None, "arguments": {}, "content": msg.content}
