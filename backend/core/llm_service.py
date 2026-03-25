"""
Shared LLM service – wraps OpenAI-compatible API for all sub-apps.
"""
from __future__ import annotations

import contextvars
import json
from typing import AsyncIterator, Optional

import httpx
from openai import AsyncOpenAI

from backend.config import llm_settings, fast_llm_settings

# Context variable to control which LLM backend to use per-request.
# When set to True, chat_completion() will automatically route to the fast model.
# This is used by the app chat route to offload app-internal calls to the fast model,
# while keeping the agentic loop on the primary (kimi-k2.5) model.
_use_fast_model: contextvars.ContextVar[bool] = contextvars.ContextVar('_use_fast_model', default=False)


def set_use_fast_model(value: bool) -> contextvars.Token:
    """Set whether the current async context should use the fast LLM model.
    Returns a token that can be used to reset the value."""
    return _use_fast_model.set(value)


def reset_use_fast_model(token: contextvars.Token) -> None:
    """Reset the fast model flag to its previous value."""
    _use_fast_model.reset(token)


def _is_kimi(model: str | None = None) -> bool:
    """Check if the current model is a Kimi model."""
    name = (model or llm_settings.model).lower()
    return "kimi" in name or "moonshot" in name


def _is_minimax(model: str | None = None) -> bool:
    """Check if the current model is a MiniMax model."""
    name = (model or llm_settings.model).lower()
    return "minimax" in name


def _is_qwen(model: str | None = None) -> bool:
    """Check if the current model is a Qwen model (e.g. qwen3-next)."""
    name = (model or llm_settings.model).lower()
    return "qwen" in name


def _strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks from Qwen3-style responses.
    
    Qwen3 models may output thinking in several formats:
    1. Standard: <think>...</think>actual_answer
    2. No opening tag: Thinking Process:\n...\n</think>\n\nactual_answer
    3. Pure text: Thinking Process:\n...\n\nactual_answer (no tags at all)
    """
    import re
    # Case 1: Standard <think>...</think> tags
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # Case 2: Content before </think> without opening <think> tag
    if "</think>" in text:
        text = text.split("</think>")[-1].strip()
    # Case 3: "Thinking Process:" prefix without any tags
    if text.startswith("Thinking Process:") or text.startswith("**Thinking Process"):
        # Try to find the actual answer after the thinking block
        # Usually separated by double newline at the end
        lines = text.rstrip().split('\n')
        # Take non-empty lines from the end that don't look like thinking
        result_lines = []
        for line in reversed(lines):
            stripped = line.strip()
            if not stripped:
                if result_lines:
                    break
                continue
            if stripped.startswith(('*', '-', '#', 'Thinking', '**Thinking')):
                break
            if re.match(r'^\d+\.\s', stripped):
                break
            result_lines.insert(0, stripped)
        if result_lines:
            text = '\n'.join(result_lines)
    return text.strip()


def _get_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=llm_settings.api_key or "sk-placeholder",
        base_url=llm_settings.api_base,
        timeout=httpx.Timeout(300.0, connect=10.0),
    )


def _get_fast_client() -> AsyncOpenAI:
    """Get a client configured for the fast LLM (qwen3-next-new)."""
    return AsyncOpenAI(
        api_key=fast_llm_settings.api_key or llm_settings.api_key or "sk-placeholder",
        base_url=fast_llm_settings.api_base or llm_settings.api_base,
        timeout=httpx.Timeout(120.0, connect=10.0),
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
    # If the fast model context is active and no explicit model is specified,
    # automatically route to the fast model (for app-internal chat calls)
    if not model and not tools and _use_fast_model.get(False):
        return await chat_completion_fast(messages, temperature=temperature, max_tokens=max_tokens)

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

    # Qwen3 models embed thinking in <think>...</think> tags within content
    if _is_qwen(effective_model) and content:
        content = _strip_thinking_tags(content)

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
    """Stream chat completion, filtering out Qwen3 <think>...</think> blocks."""
    resp = await client.chat.completions.create(**params)
    in_think = False
    buffer = ""
    async for chunk in resp:
        delta = chunk.choices[0].delta
        if delta.content:
            text = delta.content
            # Handle <think>...</think> tags that may span multiple chunks
            i = 0
            while i < len(text):
                if in_think:
                    end_idx = text.find("</think>", i)
                    if end_idx != -1:
                        in_think = False
                        i = end_idx + len("</think>")
                    else:
                        break  # Still inside <think>, discard rest
                else:
                    start_idx = text.find("<think>", i)
                    if start_idx != -1:
                        # Yield everything before <think>
                        before = text[i:start_idx]
                        if before:
                            yield before
                        in_think = True
                        i = start_idx + len("<think>")
                    else:
                        # No <think> tag, yield remaining text
                        remaining = text[i:]
                        if remaining:
                            yield remaining
                        break


async def chat_completion_fast(
    messages: list[dict],
    *,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """Send a chat completion request using the fast LLM (qwen3-next-new).
    
    Use this for lightweight tasks: naming, metadata extraction, skill extraction,
    context compression, app-internal chat, etc.
    No tool calling support — for simple text in / text out tasks only.
    """
    client = _get_fast_client()
    effective_model = fast_llm_settings.model or llm_settings.model
    effective_temp = temperature if temperature is not None else fast_llm_settings.temperature

    params = dict(
        model=effective_model,
        messages=messages,
        temperature=effective_temp,
        max_tokens=max_tokens or fast_llm_settings.max_tokens,
    )

    resp = await client.chat.completions.create(**params)
    msg = resp.choices[0].message
    content = msg.content or ""

    # Qwen3 models embed thinking in <think>...</think> tags within content
    if _is_qwen(effective_model) and content:
        content = _strip_thinking_tags(content)

    return content


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
