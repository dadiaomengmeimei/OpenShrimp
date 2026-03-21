"""
Shared LLM service – wraps OpenAI-compatible API for all sub-apps.
"""
from __future__ import annotations

import json
from typing import AsyncIterator, Optional

import httpx
from openai import AsyncOpenAI

from backend.config import llm_settings


def _is_kimi(model: str | None = None) -> bool:
    """Check if the current model is a Kimi model."""
    name = (model or llm_settings.model).lower()
    return "kimi" in name or "moonshot" in name


def _is_minimax(model: str | None = None) -> bool:
    """Check if the current model is a MiniMax model."""
    name = (model or llm_settings.model).lower()
    return "minimax" in name


def _get_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=llm_settings.api_key or "sk-placeholder",
        base_url=llm_settings.api_base,
        timeout=httpx.Timeout(300.0, connect=10.0),
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
    effective_model = model or llm_settings.model

    # Kimi models require temperature=1; override any caller value
    if _is_kimi(effective_model):
        effective_temp = 1.0
    else:
        effective_temp = temperature if temperature is not None else llm_settings.temperature

    params = dict(
        model=effective_model,
        messages=messages,
        temperature=effective_temp,
        max_tokens=max_tokens or llm_settings.max_tokens,
        stream=stream,
    )

    # MiniMax M2.7: enable reasoning_split by default so we can access thinking
    if _is_minimax(effective_model):
        merged_extra = {"reasoning_split": True}
        if extra_body:
            merged_extra.update(extra_body)
        params["extra_body"] = merged_extra
    elif extra_body:
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

    content = msg.content or ""

    # Reasoning models may put useful content in thinking fields while
    # content is empty or very short.  Try provider-specific fields.
    if len(content.strip()) < 20:
        reasoning = ""

        # MiniMax: reasoning_details (list of {"text": ...} or strings)
        reasoning_details = getattr(msg, "reasoning_details", None) or []
        if isinstance(reasoning_details, list) and reasoning_details:
            reasoning = " ".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in reasoning_details
            ).strip()
        elif isinstance(reasoning_details, str):
            reasoning = reasoning_details.strip()

        # Kimi / generic: reasoning_content (plain string)
        if not reasoning:
            reasoning = getattr(msg, "reasoning_content", None) or ""

        if reasoning and len(reasoning.strip()) > len(content.strip()):
            import re
            json_match = re.search(r'\{[\s\S]*\}', reasoning)
            if json_match:
                content = json_match.group()
            elif len(reasoning.strip()) > 20:
                content = reasoning.strip()

    return content


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
