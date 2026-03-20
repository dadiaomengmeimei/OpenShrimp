"""
Code Agent – agentic coding loop for generating/modifying sub-apps.

Uses the platform LLM (Kimi k2.5) with tool calling (OpenAI function calling format) to:
1. Read existing code in sub-app directories
2. Generate new sub-apps based on user descriptions
3. Modify existing sub-apps based on user instructions

Supports standard OpenAI function calling format for tool invocation.
Execution process is streamed to the frontend via SSE (Server-Sent Events).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.core.llm_service import chat_completion
from backend.config import llm_settings, platform_settings
from backend.core import app_registry

router = APIRouter(prefix="/api/agent", tags=["agent"])

# Path to the project root's backend/apps directory
APPS_DIR = Path("backend/apps")
# Maximum agentic loop iterations (high ceiling; relies on context compression & user interrupt)
MAX_ITERATIONS = 200
# Maximum skills text length (controls context budget)
MAX_SKILLS_CHARS = 2000
# Skills filename stored in each app directory
SKILLS_FILENAME = "skills.json"
# Context compression: compress conversation every N iterations to keep token budget manageable
COMPRESS_EVERY_N = 8
# Maximum conversation messages before forcing a compression
MAX_MESSAGES_BEFORE_COMPRESS = 20

# ─────────────────────────────────────────────────
# Tool definitions (for OpenAI-standard function calling)
# ─────────────────────────────────────────────────

TOOLS_SPEC = [
    {
        "type": "function",
        "function": {
            "name": "ls",
            "description": "List files and directories at the given path. Returns file names, sizes, and types.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to list (relative or absolute)"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read the content of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to read"}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write",
            "description": "Write content to a file. Creates parent directories if needed. Overwrites existing content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to write"},
                    "content": {"type": "string", "description": "Full content to write to the file"}
                },
                "required": ["file_path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command and return stdout + stderr. Use for testing, checking file structure, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"}
                },
                "required": ["command"]
            }
        }
    },
]


# ─────────────────────────────────────────────────
# Skills management
# ─────────────────────────────────────────────────

def _load_skills(app_id: str) -> dict:
    """
    Load skills.json for a given app.
    Returns dict with keys: items (list of skill strings), updated_at (ISO timestamp).
    """
    skills_path = APPS_DIR / app_id / SKILLS_FILENAME
    if skills_path.exists():
        try:
            data = json.loads(skills_path.read_text(encoding="utf-8"))
            return data
        except (json.JSONDecodeError, KeyError):
            pass
    return {"items": [], "updated_at": None}


def _save_skills(app_id: str, skills_data: dict) -> None:
    """Persist skills.json for a given app."""
    skills_path = APPS_DIR / app_id / SKILLS_FILENAME
    skills_path.parent.mkdir(parents=True, exist_ok=True)
    skills_path.write_text(
        json.dumps(skills_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _format_skills_for_prompt(skills_data: dict) -> str:
    """
    Format skills into a text block to inject into the system prompt.
    Returns empty string if no skills exist.
    """
    items = skills_data.get("items", [])
    if not items:
        return ""

    lines = ["## Accumulated skills & knowledge for this app\n"]
    lines.append("The following insights were distilled from previous development sessions. ")
    lines.append("Use them to guide your decisions and avoid repeating past mistakes.\n")
    for i, skill in enumerate(items, 1):
        lines.append(f"{i}. {skill}")
    return "\n".join(lines)


async def _extract_and_merge_skills(
    app_id: str,
    user_description: str,
    agent_conversation: list[dict],
    files_modified: list[str],
) -> dict:
    """
    After an agent session, use LLM to extract new skills from the conversation,
    then merge & distill with existing skills under the character budget.

    Skill categories:
    - User intent / preference (what the user really wanted)
    - Debugging lessons (errors encountered and how they were fixed)
    - Architecture decisions (why certain patterns were chosen)
    - Potential extensions (features hinted at but not yet implemented)
    """
    existing = _load_skills(app_id)
    existing_items = existing.get("items", [])

    # Build a condensed view of the conversation for extraction
    conv_summary_parts = []
    for msg in agent_conversation:
        role = msg.get("role", "")
        content = msg.get("content", "")
        # Truncate each message to keep extraction input manageable
        if len(content) > 800:
            content = content[:800] + "..."
        conv_summary_parts.append(f"[{role}]: {content}")
    conv_text = "\n".join(conv_summary_parts)

    # Limit total conv_text to avoid blowing up the extraction call
    if len(conv_text) > 6000:
        conv_text = conv_text[:6000] + "\n... [truncated]"

    existing_text = "\n".join(f"- {s}" for s in existing_items) if existing_items else "(none)"

    extract_prompt = f"""You are a skill extractor for an AI App Store development platform.

A developer just used a code agent to {'modify' if existing_items else 'create'} an app.
Your job: extract valuable, reusable insights from this session and merge them with any existing skills.

User's request: {user_description}
Files modified: {', '.join(files_modified) if files_modified else '(none)'}

=== Conversation (condensed) ===
{conv_text}

=== Existing skills ===
{existing_text}

=== Instructions ===
1. Extract NEW insights from this session. Categories:
   - **User intent**: What the user really wanted, preferences, style choices
   - **Debugging lessons**: Errors encountered, root causes, fixes applied
   - **Architecture decisions**: Why certain patterns/structures were chosen
   - **Potential extensions**: Features mentioned or hinted but not yet built
2. Merge with existing skills: remove duplicates, combine overlapping items
3. Distill: each skill should be 1-2 concise sentences
4. Total output must be ≤ {MAX_SKILLS_CHARS} characters
5. Output ONLY a JSON array of strings, e.g. ["skill 1", "skill 2", ...]
   No markdown fences, no extra text."""

    messages = [
        {"role": "system", "content": "You are a precise skill extractor. Output ONLY a JSON array of strings."},
        {"role": "user", "content": extract_prompt},
    ]

    try:
        raw = await chat_completion(messages, temperature=0.1, max_tokens=1500)
        raw = _strip_thinking(raw).strip()
        # Remove markdown code fences if present
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

        new_items = json.loads(raw)
        if not isinstance(new_items, list):
            raise ValueError("Expected JSON array")

        # Enforce character budget: trim items from the end if over limit
        total_chars = 0
        trimmed = []
        for item in new_items:
            if not isinstance(item, str):
                continue
            item = item.strip()
            if total_chars + len(item) > MAX_SKILLS_CHARS:
                break
            trimmed.append(item)
            total_chars += len(item)

        from datetime import datetime
        skills_data = {
            "items": trimmed,
            "updated_at": datetime.utcnow().isoformat(),
            "session_count": existing.get("session_count", 0) + 1,
        }
        _save_skills(app_id, skills_data)
        return skills_data

    except Exception as e:
        # If extraction fails, keep existing skills unchanged
        return existing


def _build_system_prompt(cwd: str, skills_text: str = "") -> str:
    """Build the system prompt for the coding agent."""
    base = f"""You are an expert coding agent for the OpenShrimp AI App Store platform.

You have the following tools available:
- **ls**: List files and directories
- **read**: Read file content
- **write**: Write/create files (creates parent dirs automatically)
- **bash**: Run shell commands

Your working directory is: {cwd}

## Platform architecture

Every sub-app lives in its own directory under `backend/apps/<app_id>/` and MUST have:
- `__init__.py` (can be empty)
- `main.py` (the entry point, containing the FastAPI APIRouter)

### File structure guidelines

For **simple apps** (< 150 lines of logic), a single `main.py` is fine.

For **medium to complex apps** (150+ lines, or with distinct concerns), you MUST split the code into multiple files:

```
backend/apps/<app_id>/
├── __init__.py          # Can be empty
├── main.py              # Entry point: router + endpoints only (thin controller)
├── models.py            # Pydantic models, data schemas, type definitions
├── service.py           # Core business logic, LLM orchestration, data processing
├── utils.py             # Helper functions, formatters, validators
├── prompts.py           # LLM prompt templates (if the app uses LLM)
├── config.py            # App-specific configuration / constants
└── templates/           # Static templates, if needed
```

**Rules for splitting**:
- `main.py` should be a **thin controller**: only route definitions, request parsing, and calling service functions. Aim for < 100 lines.
- Business logic goes into `service.py` (or multiple service files like `analyzer.py`, `generator.py` for distinct domains)
- Pydantic models and schemas go into `models.py`
- LLM prompt strings go into `prompts.py` (keeps them maintainable and easy to tune)
- Use relative imports between files in the same app: `from .models import MyModel`

Sub-apps can import shared services:
```python
from backend.core.llm_service import chat_completion
from backend.core.asr_service import transcribe
```

The router pattern in `main.py` MUST follow:
```python
from fastapi import APIRouter
router = APIRouter(prefix="/api/apps/<app_id>", tags=["<app_name>"])
```

## `handle_chat` Protocol (CRITICAL)

Every app MUST expose a top-level `handle_chat` async function in `main.py`. This is how the platform's chat interface talks to your app.

### Signature
```python
async def handle_chat(
    messages: list[dict],  # [{{"role": "user"|"assistant"|"system", "content": "..."}}]
    *,
    config: dict | None = None
) -> str | dict:
```

### Return value rules
The platform extracts the reply text from `handle_chat`'s return value using this priority chain:
1. If return value is a **string** → used directly as the reply
2. If return value is a **dict** → the platform checks keys in order: `content` → `reply` → `text` → `response` → `str(result)` (fallback)

**IMPORTANT**: If your app returns a dict, make sure it has a `content` key with the user-facing reply text. Otherwise the user will see a raw `str(dict)` dump.

### Good example (simple app):
```python
async def handle_chat(messages: list[dict], *, config: dict | None = None) -> str:
    # Simple: call LLM and return string directly.
    system_msg = {{"role": "system", "content": "You are a helpful assistant."}}
    return await chat_completion([system_msg] + messages)
```

### Good example (complex app returning structured data):
```python
async def handle_chat(messages: list[dict], *, config: dict | None = None) -> dict:
    # Complex: do processing and return dict with 'content' key.
    user_msg = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    result = await my_complex_processing(user_msg)
    return {{
        "content": f"Here's your result: {{result['summary']}}",  # <-- user-facing reply
        "data": result["data"],  # additional structured data
    }}
```

### BAD example (DO NOT do this):
```python
async def handle_chat(messages, *, config=None) -> dict:
    result = await some_processing(...)
    return {{
        "session_id": "...",
        "response": "done",  # 'response' is lowest priority, not ideal
        "slides": [...],
    }}
    # Problem: no 'content' key -> platform falls through to str(result) -> user sees garbage
```

### LLM Prompt Engineering Tips
If your app calls an LLM (via `chat_completion`):
- Design clear, specific system prompts that constrain the output format
- If you need JSON from the LLM, provide examples and use `json.loads()` with try/except fallback
- Test your prompts mentally: would the LLM understand what format to return?
- For multi-step generation (e.g. outlines → content), validate each step's output before proceeding

## Your workflow

1. **First**: Use `ls` to examine the current directory structure
2. **Assess complexity**: Estimate how complex the app will be. If it involves multiple concerns (routes + business logic + models + prompts), plan a multi-file structure.
3. **Plan**: Decide which files to create and what each file is responsible for
4. **Implement**: Use `write` to create/modify files one by one. Start with models/schemas, then services, then routes.
5. **Verify**: Use `ls` and `read` to verify files were created correctly

## Step Logging (MANDATORY)

**Before EVERY tool call**, you MUST output a structured step log in the following format:

```
[STEP] <action_verb>: <brief description>
[INTENT] <why you are doing this — what you expect to learn or achieve>
[PROGRESS] <current status — what's done, what remains>
```

Example:
```
[STEP] Read: examining service.py to understand the LLM prompt logic
[INTENT] Find out why the output format doesn't match expectations — suspect the prompt template is wrong
[PROGRESS] Files read: main.py, models.py. Remaining: service.py, prompts.py. Issue: handle_chat returns dict without 'content' key.
```

After completing a tool call and seeing its result, if the result is unexpected or reveals an error, add:
```
[OBSERVATION] <what you learned from the tool result>
[DECISION] <what you will do next and why>
```

**This is not optional.** These logs are collected into an execution trace that you will see later for self-correction. High-quality logs = better self-awareness = fewer mistakes.

## Rules

- ALWAYS use tools to perform actions. Don't just describe what you would do.
- ALWAYS output step logs before every tool call (see Step Logging above)
- Write clean, well-structured, production-quality Python code
- Split code into multiple files when logic exceeds ~150 lines or involves distinct concerns
- Keep `main.py` as a thin controller — complex logic belongs in service files
- Include proper error handling, type hints, and docstrings
- Make sure all imports are correct (use relative imports for same-app files)
- Reply in the same language the user uses
- After creating all files, provide a brief summary of what was created

## Execution Trace (self-awareness)

You will periodically receive an **Execution Trace** summarizing your previous actions and their results. Use it to:
- **Avoid repeating mistakes**: If a tool call failed before, don't repeat the same action blindly
- **Track progress**: Know which files you've already created/modified
- **Self-correct**: If you notice you wrote code that doesn't align with the platform's `handle_chat` protocol, fix it immediately
- **Stay focused**: Don't re-read files you've already read unless the content has changed
- **Review your own reasoning**: Your [STEP]/[INTENT] logs show what you were thinking — check if your assumptions were correct

When you receive verification failures or behavior fix requests, ALWAYS review the trace first to understand what you did wrong before attempting a fix."""

    if skills_text:
        base += "\n\n" + skills_text

    return base


# ─────────────────────────────────────────────────
# Tool execution
# ─────────────────────────────────────────────────

def _exec_tool(tool_name: str, params: dict, cwd: str) -> str:
    """Execute a tool and return the result as a string."""
    try:
        if tool_name == "ls":
            path = params.get("path", ".").strip()
            target = Path(cwd) / path if not Path(path).is_absolute() else Path(path)
            if not target.exists():
                return f"Error: Path does not exist: {target}"
            if not target.is_dir():
                return f"Error: Not a directory: {target}"
            entries = []
            for item in sorted(target.iterdir()):
                if item.name.startswith("__pycache__") or item.name.startswith("."):
                    continue
                if item.is_dir():
                    count = sum(1 for _ in item.iterdir()) if item.exists() else 0
                    entries.append(f"  {item.name}/  ({count} items)")
                else:
                    size = item.stat().st_size
                    entries.append(f"  {item.name}  ({size} bytes)")
            return f"Directory listing of {target}:\n" + "\n".join(entries) if entries else f"Empty directory: {target}"

        elif tool_name == "read":
            file_path = params.get("file_path", "").strip()
            target = Path(cwd) / file_path if not Path(file_path).is_absolute() else Path(file_path)
            if not target.exists():
                return f"Error: File not found: {target}"
            content = target.read_text(encoding="utf-8", errors="replace")
            if len(content) > 10000:
                content = content[:10000] + "\n... [truncated]"
            return content

        elif tool_name == "write":
            file_path = params.get("file_path", "").strip()
            content = params.get("content", "")
            # Don't strip content - preserve original formatting, only strip the first/last newline
            if content.startswith("\n"):
                content = content[1:]
            if content.endswith("\n"):
                content = content[:-1]
            target = Path(cwd) / file_path if not Path(file_path).is_absolute() else Path(file_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} bytes to {target}"

        elif tool_name == "bash":
            command = params.get("command", "").strip()
            # Security: basic sandboxing
            dangerous = ["rm -rf /", "sudo", "mkfs", "dd if=", "> /dev/"]
            for d in dangerous:
                if d in command:
                    return f"Error: Command blocked for safety: {command}"
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=30, cwd=cwd
            )
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR: {result.stderr}"
            if result.returncode != 0:
                output += f"\n(exit code: {result.returncode})"
            if len(output) > 5000:
                output = output[:5000] + "\n... [truncated]"
            return output.strip() if output.strip() else "(no output)"

        else:
            return f"Error: Unknown tool: {tool_name}"

    except subprocess.TimeoutExpired:
        return "Error: Command timed out (30s limit)"
    except Exception as e:
        return f"Error executing {tool_name}: {type(e).__name__}: {e}"


# ─────────────────────────────────────────────────
# Execution trace helpers — structured logging for agent self-awareness
# ─────────────────────────────────────────────────

def _summarize_tool_params(tool_name: str, params: dict) -> str:
    """Create a concise summary of tool parameters for the execution trace."""
    if tool_name == "ls":
        return f"path={params.get('path', '.')}"
    elif tool_name == "read":
        return f"file={params.get('file_path', '?')}"
    elif tool_name == "write":
        fp = params.get("file_path", "?")
        content = params.get("content", "")
        return f"file={fp} ({len(content)} chars)"
    elif tool_name == "bash":
        cmd = params.get("command", "?")
        return f"cmd={cmd[:80]}{'...' if len(cmd) > 80 else ''}"
    return str(params)[:100]


def _parse_step_logs(text: str) -> dict:
    """
    Parse structured [STEP]/[INTENT]/[PROGRESS]/[OBSERVATION]/[DECISION] logs
    from agent output text. Returns a dict of extracted fields.
    """
    tags = ["STEP", "INTENT", "PROGRESS", "OBSERVATION", "DECISION"]
    result = {}
    for tag in tags:
        pattern = rf"\[{tag}\]\s*(.+?)(?:\n|$)"
        m = re.search(pattern, text)
        if m:
            result[tag.lower()] = m.group(1).strip()
    return result


def _format_execution_trace(trace: list[dict]) -> str:
    """
    Format the execution trace into a readable summary for the agent.
    This gives the agent self-awareness of what it has done so far.
    Uses structured step logs ([STEP]/[INTENT]/[PROGRESS]) when available.
    """
    if not trace:
        return "(no actions taken yet)"

    lines = []
    for entry in trace:
        iter_num = entry["iter"]
        tools = entry.get("tools", [])
        step_logs = entry.get("step_logs", {})
        text_summary = entry.get("text_summary", "")

        tool_strs = []
        for t in tools:
            status = "✓" if t["success"] else "✗"
            tool_strs.append(f"  [{status}] {t['name']}({t['params_summary']})")
            if not t["success"]:
                tool_strs.append(f"      Error: {t['result_summary']}")

        lines.append(f"**Step {iter_num}**:")
        # Prefer structured step logs over raw text_summary
        if step_logs.get("step"):
            lines.append(f"  Action: {step_logs['step']}")
        if step_logs.get("intent"):
            lines.append(f"  Intent: {step_logs['intent']}")
        if step_logs.get("progress"):
            lines.append(f"  Progress: {step_logs['progress']}")
        if step_logs.get("observation"):
            lines.append(f"  Observation: {step_logs['observation']}")
        if step_logs.get("decision"):
            lines.append(f"  Decision: {step_logs['decision']}")
        # Fallback: if no structured logs, use raw text summary
        if not step_logs and text_summary:
            lines.append(f"  Reasoning: {text_summary}")
        lines.extend(tool_strs)

    # Append current state summary
    if trace:
        last = trace[-1]
        files = last.get("files_modified_so_far", [])
        if files:
            lines.append(f"\n**Files modified so far**: {', '.join(files)}")
        errors = [
            t for entry in trace for t in entry.get("tools", []) if not t["success"]
        ]
        if errors:
            lines.append(f"**Errors encountered**: {len(errors)} tool call(s) failed")

    return "\n".join(lines)


# ─────────────────────────────────────────────────
# Parse Qwen3 XML tool calls
# ─────────────────────────────────────────────────

def _parse_tool_calls(text: str) -> list[dict]:
    """
    Parse Qwen3-style XML tool calls from the response text.

    Format:
    <tool_call>
    <function=tool_name>
    <parameter=param_name>value</parameter>
    </function>
    </tool_call>
    """
    tool_calls = []

    # Pattern to match <tool_call>...</tool_call> blocks
    pattern = r"<tool_call>\s*<function=(\w+)>(.*?)</function>\s*</tool_call>"
    matches = re.finditer(pattern, text, re.DOTALL)

    for match in matches:
        func_name = match.group(1)
        params_text = match.group(2)

        # Parse <parameter=name>value</parameter> pairs
        params = {}
        param_pattern = r"<parameter=(\w+)>(.*?)</parameter>"
        for pm in re.finditer(param_pattern, params_text, re.DOTALL):
            # Strip leading/trailing whitespace from parameter values
            # Qwen3 often adds \n around values
            value = pm.group(2).strip()
            params[pm.group(1)] = value

        tool_calls.append({
            "name": func_name,
            "params": params,
        })

    return tool_calls


def _strip_thinking(text: str) -> str:
    """Remove <think>...</think> blocks from the response."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _strip_tool_calls(text: str) -> str:
    """Remove <tool_call>...</tool_call> blocks from the response."""
    return re.sub(r"<tool_call>.*?</tool_call>", "", text, flags=re.DOTALL).strip()


# ─────────────────────────────────────────────────
# Request model
# ─────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    """Request to generate or modify a sub-app."""
    description: str
    app_id: Optional[str] = None  # None = create new app; set = modify existing
    base_app_id: Optional[str] = None  # optional: clone from an existing app


# ─────────────────────────────────────────────────
# SSE streaming agent
# ─────────────────────────────────────────────────

def _sse(event: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(event)}\n\n"


@router.post("/generate")
async def generate_app(req: GenerateRequest):
    """
    Agentic coding loop: LLM generates tool calls → backend executes → feed results back.
    Returns Server-Sent Events stream with real-time execution progress.
    Supports up to 200 iterations with automatic context compression.
    """
    import uuid as _uuid
    session_id = f"gen-{_uuid.uuid4().hex[:8]}"
    print(f"[api] POST /generate | app_id={req.app_id} | session={session_id} | desc_len={len(req.description)}")

    async def event_stream():
        session = _create_session(session_id)
        try:
            # Determine working directory
            inferred_app_id = None
            if req.app_id:
                target_dir = (APPS_DIR / req.app_id).resolve()
                target_dir.mkdir(parents=True, exist_ok=True)
            else:
                # Pre-infer app_id so we can restrict cwd to the new app's own directory,
                # preventing the agent from browsing and being contaminated by other apps.
                inferred_app_id = await _infer_app_id(req.description)
                target_dir = (APPS_DIR / inferred_app_id).resolve()
                target_dir.mkdir(parents=True, exist_ok=True)

            cwd = str(target_dir)

            yield _sse({"type": "start", "method": "agentic-loop", "app_id": req.app_id, "session_id": session_id})
            yield _sse({"type": "log", "message": f"Working directory: {cwd}"})
            yield _sse({"type": "log", "message": f"Model: {llm_settings.model}"})
            yield _sse({"type": "log", "message": f"Max iterations: {MAX_ITERATIONS} (with auto context compression)"})

            # Build the prompt
            if req.app_id:
                user_prompt = (
                    f"Modify the existing sub-app '{req.app_id}' in the current directory.\n"
                    f"Requirements: {req.description}"
                )
            elif req.base_app_id:
                base_dir = str((APPS_DIR / req.base_app_id).resolve())
                user_prompt = (
                    f"Create a new sub-app. Use the code in '{base_dir}' as reference.\n"
                    f"Requirements: {req.description}"
                )
            else:
                user_prompt = (
                    f"Create a new Python FastAPI sub-app in the current directory (app_id: '{inferred_app_id}').\n"
                    f"Your working directory is already set to the new app's folder. "
                    f"Do NOT browse or read any other app directories. "
                    f"Build everything from scratch based on the requirements.\n"
                    f"Requirements: {req.description}"
                )

            # Load existing skills for the app (if editing)
            skills_text = ""
            effective_app_id = req.app_id
            if req.app_id:
                skills_data = _load_skills(req.app_id)
                skills_text = _format_skills_for_prompt(skills_data)
                if skills_text:
                    yield _sse({"type": "log", "message": f"Loaded {len(skills_data.get('items', []))} skills for app '{req.app_id}'"})

            system_prompt = _build_system_prompt(cwd, skills_text)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            yield _sse({"type": "log", "message": "Starting agentic coding loop..."})

            # Run the shared agentic loop
            files_modified = []
            full_output = ""
            last_execution_trace = []
            async for event_str in _run_agentic_loop(messages, cwd, session):
                # Intercept the internal _loop_done event
                try:
                    event_data = json.loads(event_str.replace("data: ", "").strip())
                    if event_data.get("type") == "_loop_done":
                        files_modified = event_data.get("files_modified", [])
                        full_output = event_data.get("output", "")
                        last_execution_trace = event_data.get("execution_trace", [])
                        continue
                except (json.JSONDecodeError, AttributeError):
                    pass
                yield event_str

            # Self-verification
            new_app_id = req.app_id
            if not new_app_id:
                new_app_id = await _discover_and_register_app(req.description, cwd, inferred_app_id)

            if new_app_id and files_modified:
                yield _sse({"type": "log", "message": "🔍 Running self-verification..."})
                verify = _self_verify(new_app_id, cwd)
                for check in verify["checks"]:
                    status = "✅" if check["passed"] else "❌"
                    yield _sse({"type": "log", "message": f"{status} {check['name']}: {check['detail'][:200]}"})

                if not verify["ok"]:
                    # Feed verification errors back to agent for auto-repair, with execution trace
                    failed_checks = [c for c in verify["checks"] if not c["passed"]]
                    repair_msg = "## Self-Verification FAILED\n\nThe following checks failed after your changes:\n\n"
                    for c in failed_checks:
                        repair_msg += f"- **{c['name']}**: {c['detail']}\n"
                    # Include execution trace so agent knows what it did
                    if last_execution_trace:
                        trace_text = _format_execution_trace(last_execution_trace)
                        repair_msg += f"\n## Your Previous Execution Trace\n{trace_text}\n\n"
                    repair_msg += "\nPlease fix these issues. Use `read` and `write` tools to correct the code."
                    messages.append({"role": "user", "content": repair_msg})

                    yield _sse({"type": "log", "message": "🔄 Auto-repairing verification failures..."})
                    async for event_str in _run_agentic_loop(messages, cwd, session, max_iterations=10):
                        try:
                            event_data = json.loads(event_str.replace("data: ", "").strip())
                            if event_data.get("type") == "_loop_done":
                                extra_files = event_data.get("files_modified", [])
                                files_modified.extend(f for f in extra_files if f not in files_modified)
                                continue
                        except (json.JSONDecodeError, AttributeError):
                            pass
                        yield event_str

                    # Re-verify
                    verify2 = _self_verify(new_app_id, cwd)
                    status_msg = "✅ Verification passed after repair" if verify2["ok"] else "⚠️ Some checks still failing"
                    yield _sse({"type": "log", "message": status_msg})

            if new_app_id:
                yield _sse({"type": "log", "message": f"App registered: {new_app_id}"})
                try:
                    app_registry.reload_app_module(new_app_id)
                except Exception:
                    pass

            # Extract and save skills
            skill_app_id = new_app_id or effective_app_id
            if skill_app_id and len(messages) > 2:
                yield _sse({"type": "log", "message": "Extracting skills from session..."})
                try:
                    updated_skills = await _extract_and_merge_skills(
                        skill_app_id, req.description, messages, files_modified,
                    )
                    skill_count = len(updated_skills.get("items", []))
                    yield _sse({"type": "log", "message": f"Saved {skill_count} skills for app '{skill_app_id}'"})
                    yield _sse({"type": "skills_updated", "app_id": skill_app_id, "count": skill_count, "items": updated_skills.get("items", [])})
                except Exception as e:
                    yield _sse({"type": "log", "message": f"Warning: skill extraction failed: {e}"})

            yield _sse({
                "type": "done",
                "output": full_output[:3000],
                "files_modified": files_modified,
                "app_id": new_app_id,
            })
        finally:
            _destroy_session(session_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _discover_and_register_app(description: str, cwd: str, inferred_app_id: Optional[str] = None) -> Optional[str]:
    """Discover newly created app directories and register them."""
    # If we pre-inferred an app_id, check that directory first
    if inferred_app_id:
        candidate = APPS_DIR / inferred_app_id
        if candidate.is_dir() and (candidate / "main.py").exists():
            existing = await app_registry.get_app(inferred_app_id)
            if not existing:
                metadata = await _extract_metadata(description, inferred_app_id)
                await app_registry.register_app(
                    inferred_app_id,
                    name=metadata.get("name", inferred_app_id),
                    description=metadata.get("description", description),
                    icon=metadata.get("icon", "🤖"),
                    category=metadata.get("category", "general"),
                )
                return inferred_app_id

    # Fallback: scan all directories
    apps_dir = APPS_DIR
    for d in apps_dir.iterdir():
        if d.is_dir() and d.name not in ("__pycache__", "excel_analyzer", "rag_reader"):
            if (d / "main.py").exists():
                app_id = d.name
                existing = await app_registry.get_app(app_id)
                if not existing:
                    metadata = await _extract_metadata(description, app_id)
                    await app_registry.register_app(
                        app_id,
                        name=metadata.get("name", app_id),
                        description=metadata.get("description", description),
                        icon=metadata.get("icon", "🤖"),
                        category=metadata.get("category", "general"),
                    )
                    return app_id
    return None


async def _infer_app_id(description: str) -> str:
    """Use LLM to infer a snake_case app_id from the user's description before the agentic loop starts."""
    messages = [
        {
            "role": "system",
            "content": (
                "Given a user's app description, generate a short snake_case identifier for the app. "
                "Rules: lowercase, only letters/digits/underscores, 3-30 chars, descriptive but concise. "
                "ONLY output the identifier string, nothing else."
            ),
        },
        {"role": "user", "content": description},
    ]
    try:
        raw = await chat_completion(messages, temperature=0.1, max_tokens=50)
        raw = _strip_thinking(raw).strip().strip('"').strip("'").strip('`')
        # Sanitize: only allow valid Python identifier chars
        import re
        sanitized = re.sub(r'[^a-z0-9_]', '_', raw.lower()).strip('_')
        if sanitized and len(sanitized) >= 3:
            return sanitized[:30]
    except Exception:
        pass
    # Fallback: generate from first few words of description
    import re
    words = re.findall(r'[a-zA-Z0-9\u4e00-\u9fff]+', description)[:3]
    fallback = '_'.join(w.lower() for w in words if w.isascii()) or f"app_{__import__('uuid').uuid4().hex[:6]}"
    return fallback[:30]


async def _extract_metadata(description: str, app_id: str) -> dict:
    """Use LLM to extract structured metadata from the app description."""
    messages = [
        {
            "role": "system",
            "content": (
                "Extract metadata from the user's app description. "
                "Return a JSON object with: app_id (snake_case), name, description, icon (emoji), category. "
                "ONLY output JSON, no extra text, no markdown fences."
            ),
        },
        {"role": "user", "content": f"App ID: {app_id}\nApp description: {description}"},
    ]
    try:
        raw = await chat_completion(messages, temperature=0.1, max_tokens=500)
        raw = _strip_thinking(raw).strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = raw[:-3]
        return json.loads(raw.strip())
    except Exception:
        return {
            "app_id": app_id,
            "name": app_id.replace("_", " ").title(),
            "description": description,
            "icon": "🤖",
            "category": "general",
        }


@router.get("/skills/{app_id}")
async def get_skills(app_id: str):
    """Get the accumulated skills for an app."""
    skills_data = _load_skills(app_id)
    return {
        "app_id": app_id,
        "items": skills_data.get("items", []),
        "updated_at": skills_data.get("updated_at"),
        "session_count": skills_data.get("session_count", 0),
        "total_chars": sum(len(s) for s in skills_data.get("items", [])),
        "max_chars": MAX_SKILLS_CHARS,
    }


class SkillUpdateRequest(BaseModel):
    """Request to manually add or replace skills."""
    items: Optional[list[str]] = None  # If set, replace all skills
    add_item: Optional[str] = None     # If set, append a single skill
    remove_index: Optional[int] = None # If set, remove skill at index


@router.put("/skills/{app_id}")
async def update_skills(app_id: str, req: SkillUpdateRequest):
    """Manually update skills for an app (add, remove, or replace all)."""
    skills_data = _load_skills(app_id)
    items = skills_data.get("items", [])

    if req.items is not None:
        # Replace all
        items = req.items
    elif req.add_item is not None:
        items.append(req.add_item)
    elif req.remove_index is not None:
        if 0 <= req.remove_index < len(items):
            items.pop(req.remove_index)

    # Enforce character budget
    total_chars = 0
    trimmed = []
    for item in items:
        if total_chars + len(item) > MAX_SKILLS_CHARS:
            break
        trimmed.append(item)
        total_chars += len(item)

    from datetime import datetime
    skills_data = {
        "items": trimmed,
        "updated_at": datetime.utcnow().isoformat(),
        "session_count": skills_data.get("session_count", 0),
    }
    _save_skills(app_id, skills_data)

    return {
        "app_id": app_id,
        "items": trimmed,
        "updated_at": skills_data["updated_at"],
        "total_chars": sum(len(s) for s in trimmed),
        "max_chars": MAX_SKILLS_CHARS,
    }


# ─────────────────────────────────────────────────
# Session management for interrupt & user message injection
# ─────────────────────────────────────────────────

# Active agent sessions: session_id -> session state
_active_sessions: dict[str, dict] = {}


def _create_session(session_id: str) -> dict:
    """Create a new agent session for interrupt / inject support."""
    session = {
        "id": session_id,
        "interrupted": False,
        "injected_messages": [],  # Queue of user messages to inject
        "running": True,
    }
    _active_sessions[session_id] = session
    return session


def _destroy_session(session_id: str) -> None:
    """Remove a finished session."""
    _active_sessions.pop(session_id, None)


# ─────────────────────────────────────────────────
# Context compression — summarize old conversation rounds
# ─────────────────────────────────────────────────

async def _compress_context(messages: list[dict], keep_last_n: int = 4) -> list[dict]:
    """
    Compress the conversation history to save tokens.
    Keeps: system prompt (messages[0]), last N messages, and a summary of everything in between.
    The summary preserves: original goal, key decisions, files modified, errors encountered, current state.
    """
    if len(messages) <= keep_last_n + 2:
        return messages  # Nothing to compress

    system_msg = messages[0]
    middle = messages[1:-keep_last_n]  # Messages to be compressed
    recent = messages[-keep_last_n:]   # Messages to keep verbatim

    # Build a condensed view of middle messages for summarization
    middle_parts = []
    for msg in middle:
        role = msg.get("role", "")
        content = msg.get("content", "")
        # Truncate long messages for the summarization call
        if len(content) > 600:
            content = content[:600] + "..."
        middle_parts.append(f"[{role}]: {content}")
    middle_text = "\n".join(middle_parts)

    # Limit the input to the summarization call
    if len(middle_text) > 8000:
        middle_text = middle_text[:8000] + "\n... [truncated]"

    compress_prompt = f"""Summarize the following agent conversation history into a concise status report.
Preserve:
- The original user goal / task
- Files that were created or modified (with paths)
- Key decisions made
- Errors encountered and how they were resolved
- Current state: what has been done and what remains

Format as a structured summary, ~300 words max. Be factual and precise.

=== Conversation to summarize ===
{middle_text}"""

    try:
        summary = await chat_completion(
            [
                {"role": "system", "content": "You are a conversation summarizer. Output a concise structured summary."},
                {"role": "user", "content": compress_prompt},
            ],
            temperature=0.1,
            max_tokens=1000,
        )
        summary = _strip_thinking(summary).strip()
    except Exception:
        # If summarization fails, do a crude truncation
        summary = f"[Context compressed: {len(middle)} messages summarized. Recent context preserved.]"

    compressed = [
        system_msg,
        {
            "role": "user",
            "content": f"## Context Summary (compressed from {len(middle)} earlier messages)\n\n{summary}\n\n---\nContinue from where you left off. The recent messages below show the latest state.",
        },
        *recent,
    ]
    return compressed


# ─────────────────────────────────────────────────
# Self-verification — validate app after modifications
# ─────────────────────────────────────────────────

def _self_verify(app_id: str, cwd: str) -> dict:
    """
    Run automated checks on an app after the agent finishes.
    Returns {ok: bool, checks: [{name, passed, detail}]}
    """
    checks = []
    app_dir = Path(cwd) if Path(cwd).name == app_id else APPS_DIR / app_id

    # Check 1: main.py exists
    main_py = app_dir / "main.py"
    checks.append({
        "name": "main.py exists",
        "passed": main_py.exists(),
        "detail": str(main_py),
    })

    # Check 2: __init__.py exists
    init_py = app_dir / "__init__.py"
    checks.append({
        "name": "__init__.py exists",
        "passed": init_py.exists(),
        "detail": str(init_py),
    })

    # Check 3: Python syntax check on all .py files
    py_files = list(app_dir.glob("*.py"))
    for pf in py_files:
        try:
            result = subprocess.run(
                [sys.executable, "-c", f"import py_compile; py_compile.compile('{pf}', doraise=True)"],
                capture_output=True, text=True, timeout=10,
            )
            passed = result.returncode == 0
            detail = result.stderr.strip() if not passed else "OK"
        except Exception as e:
            passed = False
            detail = str(e)
        checks.append({
            "name": f"syntax: {pf.name}",
            "passed": passed,
            "detail": detail,
        })

    # Check 4: Try importing the module
    try:
        result = subprocess.run(
            [sys.executable, "-c", f"import backend.apps.{app_id}.main"],
            capture_output=True, text=True, timeout=15,
            cwd=str(Path(".").resolve()),
        )
        passed = result.returncode == 0
        detail = result.stderr.strip()[-500:] if not passed else "OK"
    except Exception as e:
        passed = False
        detail = str(e)
    checks.append({
        "name": "module import",
        "passed": passed,
        "detail": detail,
    })

    all_ok = all(c["passed"] for c in checks)
    return {"ok": all_ok, "checks": checks}


# ─────────────────────────────────────────────────
# Shared agentic loop — used by both /generate and /auto-fix
# ─────────────────────────────────────────────────

async def _run_agentic_loop(
    messages: list[dict],
    cwd: str,
    session: dict,
    max_iterations: int = MAX_ITERATIONS,
    temperature: float = 0.3,
    continuation_prompt: str = "Continue with the next step. Use tools to create/modify more files if needed, or provide a summary if you're done.",
):
    """
    Core agentic loop generator. Yields SSE events.
    Supports: context compression, self-verification, user interrupt, user message injection.
    """
    import time as _time
    _loop_start = _time.time()
    print(f"[agent] _run_agentic_loop started | cwd={cwd} | max_iter={max_iterations}")
    files_modified = []
    full_output = ""
    iteration = 0
    # Execution trace: structured log of each step for agent self-awareness
    # Each entry: {"iter": N, "tools": [{"name": ..., "params_summary": ..., "success": bool, "result_summary": ...}], "text_summary": ...}
    execution_trace: list[dict] = []

    while iteration < max_iterations:
        # --- Check for interrupt ---
        if session["interrupted"]:
            yield _sse({"type": "log", "message": "⛔ Agent interrupted by user"})
            break

        # --- Check for injected user messages ---
        while session["injected_messages"]:
            injected = session["injected_messages"].pop(0)
            yield _sse({"type": "log", "message": f"📝 User supervision: {injected}"})
            messages.append({"role": "user", "content": f"[USER SUPERVISION MESSAGE]: {injected}"})

        # --- Context compression ---
        if iteration > 0 and iteration % COMPRESS_EVERY_N == 0 and len(messages) > MAX_MESSAGES_BEFORE_COMPRESS:
            yield _sse({"type": "log", "message": f"🗜️ Compressing context ({len(messages)} messages)..."})
            messages[:] = await _compress_context(messages)
            yield _sse({"type": "log", "message": f"Context compressed to {len(messages)} messages"})

        iteration += 1
        yield _sse({"type": "log", "message": f"--- Iteration {iteration}/{max_iterations} ---"})

        # --- Call LLM ---
        try:
            _llm_start = _time.time()
            print(f"[agent] LLM call #{iteration} | msgs={len(messages)} | temp={temperature}")
            raw_message = await chat_completion(
                messages,
                temperature=temperature,
                max_tokens=20000,
                tools=TOOLS_SPEC,
                return_raw_message=True,
            )
            print(f"[agent] LLM call #{iteration} done | {_time.time()-_llm_start:.1f}s")
        except Exception as e:
            print(f"[agent] LLM call #{iteration} FAILED: {e}")
            yield _sse({"type": "error", "error": f"LLM call failed: {e}"})
            break

        # Extract text content from the message
        text_content = raw_message.content or ""
        text_content = _strip_thinking(text_content)

        if text_content:
            full_output += text_content + "\n"
            yield _sse({"type": "text_delta", "delta": text_content})

        # Extract tool calls from the OpenAI-standard message object
        api_tool_calls = raw_message.tool_calls or []

        if not api_tool_calls:
            yield _sse({"type": "log", "message": "Agent finished (no more tool calls)"})
            break

        # Build the assistant message for multi-turn conversation (with tool_calls)
        assistant_msg = {"role": "assistant", "content": text_content or None}
        # kimi-k2.5 thinking mode: preserve reasoning_content so the API doesn't reject the message
        reasoning = getattr(raw_message, "reasoning_content", None)
        if reasoning:
            assistant_msg["reasoning_content"] = reasoning
        assistant_msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in api_tool_calls
        ]
        messages.append(assistant_msg)

        # Execute each tool call
        tool_results = []
        trace_tools = []  # For execution trace
        for tc in api_tool_calls:
            # Check interrupt between tool executions
            if session["interrupted"]:
                yield _sse({"type": "log", "message": "⛔ Interrupted during tool execution"})
                break

            tool_name = tc.function.name
            try:
                params = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                params = {}

            yield _sse({"type": "tool_call", "tool": tool_name, "input": params})

            result = _exec_tool(tool_name, params, cwd)
            tool_results.append({"name": tool_name, "result": result, "tool_call_id": tc.id})

            # Build trace entry for this tool call
            is_error = result.startswith("Error")
            params_summary = _summarize_tool_params(tool_name, params)
            result_summary = result[:200] + "..." if len(result) > 200 else result
            trace_tools.append({
                "name": tool_name,
                "params_summary": params_summary,
                "success": not is_error,
                "result_summary": result_summary,
            })

            yield _sse({"type": "tool_result", "tool": tool_name, "output": result[:500]})

            if tool_name == "write":
                fp = params.get("file_path", "").strip()
                if fp and fp not in files_modified:
                    files_modified.append(fp)
                    yield _sse({"type": "file_modified", "path": fp})

        if session["interrupted"]:
            break

        # Record execution trace for this iteration
        step_logs = _parse_step_logs(text_content)
        text_summary = text_content[:200] + "..." if len(text_content) > 200 else text_content
        execution_trace.append({
            "iter": iteration,
            "tools": trace_tools,
            "step_logs": step_logs,
            "text_summary": text_summary,
            "files_modified_so_far": list(files_modified),
        })

        # Add tool results as individual "tool" role messages (OpenAI standard format)
        for tr in tool_results:
            messages.append({
                "role": "tool",
                "tool_call_id": tr["tool_call_id"],
                "content": tr["result"],
            })

        # Inject execution trace summary every few iterations so agent can self-reflect
        if iteration % 3 == 0 or iteration == 1:
            trace_summary = _format_execution_trace(execution_trace)
            trace_msg = f"\n---\n## Execution Trace (your progress so far)\n{trace_summary}\n---\n\n{continuation_prompt}"
            messages.append({"role": "user", "content": trace_msg})

        # Small yield to allow event loop to process interrupts
        await asyncio.sleep(0)

    if iteration >= max_iterations:
        yield _sse({"type": "log", "message": f"Reached max iterations ({max_iterations})"})

    # Return metadata via a special internal event (include trace for downstream use)
    yield _sse({
        "type": "_loop_done",
        "files_modified": files_modified,
        "output": full_output[:3000],
        "iterations": iteration,
        "execution_trace": execution_trace[-10:],  # Last 10 entries to keep size bounded
    })


# ─────────────────────────────────────────────────
# Auto-fix: detect runtime errors and auto-repair
# ─────────────────────────────────────────────────


class AutoFixRequest(BaseModel):
    """Request to auto-fix a broken app."""
    app_id: str
    error_message: str
    error_type: str = ""
    traceback: str = ""
    user_input: str = ""  # The user message that triggered the error
    phase: str = "runtime"  # "import", "structure", "runtime"
    # Behavior fix mode: no crash, but output is wrong
    mode: str = "error"  # "error" = crash/exception, "behavior" = output not as expected
    conversation_history: list[dict] = []  # Full chat history [{role, content}, ...]
    actual_output: str = ""  # The app's actual (wrong) output
    expected_behavior: str = ""  # User's description of what they expected


class InjectMessageRequest(BaseModel):
    """Inject a user supervision message into a running agent session."""
    session_id: str
    message: str


def _build_autofix_prompt(req: AutoFixRequest) -> str:
    """Build a detailed prompt for the auto-fix agent."""
    if req.mode == "behavior":
        return _build_behavior_fix_prompt(req)
    return _build_error_fix_prompt(req)


def _build_error_fix_prompt(req: AutoFixRequest) -> str:
    """Build prompt for error/crash mode auto-fix."""
    parts = [
        f"## Bug Report for app '{req.app_id}'",
        "",
        f"**Error Phase**: {req.phase}",
        f"**Error Type**: {req.error_type}" if req.error_type else "",
        f"**Error Message**: {req.error_message}",
    ]

    if req.traceback:
        parts.append("")
        parts.append("**Full Traceback**:")
        parts.append("```")
        tb = req.traceback if len(req.traceback) < 3000 else req.traceback[-3000:]
        parts.append(tb)
        parts.append("```")

    if req.user_input:
        parts.append("")
        parts.append(f"**User input that triggered the error**: {req.user_input}")

    parts.append("")
    parts.append("## Your Task")
    parts.append("")
    parts.append("1. Read all source files of this app to understand the current code")
    parts.append("2. Analyze the error: identify the root cause from the traceback and error message")
    parts.append("3. Fix the bug by rewriting the affected file(s)")
    parts.append("4. Verify the fix makes sense (check imports, types, logic)")
    parts.append("5. Provide a brief summary of what was wrong and how you fixed it")
    parts.append("")
    parts.append("IMPORTANT:")
    parts.append("- Start by reading the existing files with `read` and `ls`")
    parts.append("- Make minimal, targeted changes — don't rewrite everything unless necessary")
    parts.append("- Ensure all imports are correct")
    parts.append("- Test your fix mentally: will the same input still cause an error?")

    return "\n".join(parts)


def _build_behavior_fix_prompt(req: AutoFixRequest) -> str:
    """Build prompt for behavior mode auto-fix (no crash, but output is wrong)."""
    parts = [
        f"## Behavior Issue Report for app '{req.app_id}'",
        "",
        "The app runs without errors, but the output does not match the user's expectations.",
        "",
    ]

    # Include conversation history so the agent can understand the full context
    if req.conversation_history:
        parts.append("### Conversation History")
        parts.append("")
        for msg in req.conversation_history[-10:]:  # Last 10 messages max
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if len(content) > 1000:
                content = content[:1000] + "..."
            parts.append(f"**[{role}]**: {content}")
            parts.append("")
    elif req.user_input:
        parts.append(f"### User Input")
        parts.append(f"")
        parts.append(f"{req.user_input}")
        parts.append("")

    if req.actual_output:
        parts.append("### Actual Output (what the app returned)")
        parts.append("")
        parts.append("```")
        output = req.actual_output if len(req.actual_output) < 2000 else req.actual_output[:2000] + "..."
        parts.append(output)
        parts.append("```")
        parts.append("")

    if req.expected_behavior:
        parts.append("### Expected Behavior (what the user wanted)")
        parts.append("")
        parts.append(f"{req.expected_behavior}")
        parts.append("")

    if req.error_message and req.error_message != req.actual_output:
        parts.append(f"### Additional Context")
        parts.append(f"")
        parts.append(f"{req.error_message}")
        parts.append("")

    parts.append("## Your Task")
    parts.append("")
    parts.append("1. Read all source files of this app to understand the current code and logic")
    parts.append("2. Analyze the conversation history, actual output, and expected behavior")
    parts.append("3. Identify WHY the output doesn't match expectations (logic bug, missing feature, wrong prompt, etc.)")
    parts.append("4. Fix the code so the app would produce output matching the user's expectations")
    parts.append("5. Think about edge cases: will similar inputs also be handled correctly?")
    parts.append("6. Provide a brief summary of what was wrong and how you fixed it")
    parts.append("")
    parts.append("IMPORTANT:")
    parts.append("- Start by reading the existing files with `read` and `ls`")
    parts.append("- Focus on understanding the app's logic flow: input → processing → output")
    parts.append("- The app did NOT crash — this is a logic/behavior issue, not a syntax/import error")
    parts.append("- Make targeted changes to fix the behavior without breaking other functionality")
    parts.append("- If the app uses LLM prompts, check if the prompt needs adjustment")
    parts.append("")
    parts.append("## Platform Context (how the platform displays app output)")
    parts.append("")
    parts.append("The platform calls `handle_chat(messages, config=config)` and extracts the reply:")
    parts.append("- If return is a **string** → displayed directly")
    parts.append("- If return is a **dict** → platform checks keys: `content` → `reply` → `text` → `response` → `str(result)` (fallback)")
    parts.append("- If none of the above keys exist, the user sees a raw `str(dict)` dump — this is a common bug!")
    parts.append("")
    parts.append("**Common behavior fix**: If the app returns a dict without a `content`/`reply`/`text` key, ")
    parts.append("the user will see garbage output. Fix this by ensuring the dict has a `content` key with user-facing text.")
    parts.append("")
    parts.append("**If the app's core logic (e.g. LLM prompting, data processing) is wrong**, ")
    parts.append("don't just fix the return format — fix the actual logic so the output content matches expectations.")

    return "\n".join(parts)


@router.post("/auto-fix")
async def auto_fix_app(req: AutoFixRequest):
    """
    Auto-fix a broken app using the code agent.
    Reads the app's source code, analyzes the error, and applies a fix.
    Returns SSE stream with real-time progress (same format as /generate).
    Supports interrupt and user supervision message injection.
    """
    import uuid as _uuid
    print(f"[api] POST /auto-fix | app_id={req.app_id} | mode={req.mode} | error={req.error_message[:100]}")
    session_id = f"fix-{_uuid.uuid4().hex[:8]}"

    async def event_stream():
        session = _create_session(session_id)
        try:
            target_dir = (APPS_DIR / req.app_id).resolve()
            if not target_dir.exists():
                yield _sse({"type": "error", "error": f"App directory not found: {target_dir}"})
                return

            cwd = str(target_dir)
            print(f"[api] auto-fix | app_id={req.app_id} | mode={req.mode} | session={session_id}")

            fix_mode_label = "behavior fix" if req.mode == "behavior" else "error fix"
            yield _sse({"type": "start", "method": "auto-fix", "app_id": req.app_id, "session_id": session_id})
            yield _sse({"type": "log", "message": f"🔧 Auto-fix ({fix_mode_label}) started for app '{req.app_id}'"})
            if req.mode == "behavior":
                yield _sse({"type": "log", "message": f"Issue: Output not as expected"})
                if req.expected_behavior:
                    yield _sse({"type": "log", "message": f"Expected: {req.expected_behavior[:200]}"})
            else:
                yield _sse({"type": "log", "message": f"Error: {req.error_message}"})
            yield _sse({"type": "log", "message": f"Working directory: {cwd}"})

            # Load skills for context
            skills_data = _load_skills(req.app_id)
            skills_text = _format_skills_for_prompt(skills_data)
            if skills_text:
                yield _sse({"type": "log", "message": f"Loaded {len(skills_data.get('items', []))} skills"})

            # Build system prompt with auto-fix emphasis
            system_prompt = _build_system_prompt(cwd, skills_text)
            system_prompt += "\n\n## CURRENT MODE: AUTO-FIX\nYou are debugging and fixing a broken app. Be surgical and precise."

            user_prompt = _build_autofix_prompt(req)

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            yield _sse({"type": "log", "message": "Starting auto-fix agentic loop..."})

            # Run the shared agentic loop
            files_modified = []
            full_output = ""
            last_execution_trace = []
            async for event_str in _run_agentic_loop(
                messages, cwd, session,
                temperature=0.2,
                continuation_prompt="Continue fixing. If the fix is complete, provide a summary of what was wrong and how you fixed it.",
            ):
                try:
                    event_data = json.loads(event_str.replace("data: ", "").strip())
                    if event_data.get("type") == "_loop_done":
                        files_modified = event_data.get("files_modified", [])
                        full_output = event_data.get("output", "")
                        last_execution_trace = event_data.get("execution_trace", [])
                        continue
                except (json.JSONDecodeError, AttributeError):
                    pass
                yield event_str

            # Self-verification after fix
            if files_modified:
                yield _sse({"type": "log", "message": "🔍 Verifying fix..."})
                verify = _self_verify(req.app_id, cwd)
                for check in verify["checks"]:
                    status = "✅" if check["passed"] else "❌"
                    yield _sse({"type": "log", "message": f"{status} {check['name']}: {check['detail'][:200]}"})

                if not verify["ok"]:
                    # Auto-repair verification failures with execution trace
                    failed_checks = [c for c in verify["checks"] if not c["passed"]]
                    repair_msg = "## Self-Verification FAILED\n\nThe following checks failed after your fix:\n\n"
                    for c in failed_checks:
                        repair_msg += f"- **{c['name']}**: {c['detail']}\n"
                    # Include execution trace so agent can self-reflect
                    if last_execution_trace:
                        trace_text = _format_execution_trace(last_execution_trace)
                        repair_msg += f"\n## Your Previous Execution Trace\n{trace_text}\n\n"
                    repair_msg += "\nPlease fix these issues."
                    messages.append({"role": "user", "content": repair_msg})

                    yield _sse({"type": "log", "message": "🔄 Auto-repairing verification failures..."})
                    async for event_str in _run_agentic_loop(messages, cwd, session, max_iterations=10):
                        try:
                            event_data = json.loads(event_str.replace("data: ", "").strip())
                            if event_data.get("type") == "_loop_done":
                                extra_files = event_data.get("files_modified", [])
                                files_modified.extend(f for f in extra_files if f not in files_modified)
                                continue
                        except (json.JSONDecodeError, AttributeError):
                            pass
                        yield event_str

                # Reload module
                yield _sse({"type": "log", "message": "Reloading app module..."})
                try:
                    app_registry.reload_app_module(req.app_id)
                    yield _sse({"type": "log", "message": "App module reloaded successfully"})
                except Exception as e:
                    yield _sse({"type": "log", "message": f"Warning: module reload failed: {e}"})

            # Extract skills from the debugging session
            if len(messages) > 2:
                yield _sse({"type": "log", "message": "Extracting debugging insights..."})
                try:
                    updated_skills = await _extract_and_merge_skills(
                        req.app_id,
                        f"Auto-fix: {req.error_message}",
                        messages,
                        files_modified,
                    )
                    skill_count = len(updated_skills.get("items", []))
                    yield _sse({"type": "log", "message": f"Saved {skill_count} skills (including fix insights)"})
                    yield _sse({"type": "skills_updated", "app_id": req.app_id, "count": skill_count, "items": updated_skills.get("items", [])})
                except Exception as e:
                    yield _sse({"type": "log", "message": f"Warning: skill extraction failed: {e}"})

            yield _sse({
                "type": "done",
                "output": full_output[:3000],
                "files_modified": files_modified,
                "app_id": req.app_id,
            })
        finally:
            _destroy_session(session_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─────────────────────────────────────────────────
# Interrupt & message injection endpoints
# ─────────────────────────────────────────────────

@router.post("/interrupt/{session_id}")
async def interrupt_agent(session_id: str):
    """Interrupt a running agent session."""
    session = _active_sessions.get(session_id)
    if not session:
        raise HTTPException(404, f"Session not found: {session_id}")
    session["interrupted"] = True
    return {"ok": True, "session_id": session_id, "message": "Interrupt signal sent"}


@router.post("/inject")
async def inject_message(req: InjectMessageRequest):
    """Inject a user supervision message into a running agent session."""
    session = _active_sessions.get(req.session_id)
    if not session:
        raise HTTPException(404, f"Session not found: {req.session_id}")
    if not session["running"]:
        raise HTTPException(400, "Session is not running")
    session["injected_messages"].append(req.message)
    return {"ok": True, "session_id": req.session_id, "queued": len(session["injected_messages"])}


@router.get("/sessions")
async def list_sessions():
    """List active agent sessions."""
    return [
        {"id": s["id"], "running": s["running"], "interrupted": s["interrupted"]}
        for s in _active_sessions.values()
    ]


@router.get("/status")
async def agent_status():
    """Check the agent's readiness status."""
    return {
        "agent_ready": True,
        "method": "agentic-loop",
        "llm_configured": bool(llm_settings.api_key and llm_settings.api_key != "your-api-key-here"),
        "llm_model": llm_settings.model,
        "llm_base": llm_settings.api_base,
        "max_iterations": MAX_ITERATIONS,
        "active_sessions": len(_active_sessions),
    }
