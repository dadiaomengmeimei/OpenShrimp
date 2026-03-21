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
COMPRESS_EVERY_N = 5
# Maximum conversation messages before forcing a compression
MAX_MESSAGES_BEFORE_COMPRESS = 16

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
    {
        "type": "function",
        "function": {
            "name": "edit",
            "description": "Replace a specific text snippet in a file with new content. Use this for targeted edits instead of rewriting the entire file with 'write'. The old_string must match exactly (including whitespace and indentation).",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to edit"},
                    "old_string": {"type": "string", "description": "The exact text to find and replace (must match the file content exactly, including whitespace)"},
                    "new_string": {"type": "string", "description": "The replacement text"}
                },
                "required": ["file_path", "old_string", "new_string"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_app_features",
            "description": "Update the app's UI feature flags in the platform config. Use this to enable frontend capabilities like file upload. Available features: 'file_upload' (shows file upload button in chat UI). The features list replaces the current one.",
            "parameters": {
                "type": "object",
                "properties": {
                    "features": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of feature flags to enable. Available: 'file_upload'"
                    }
                },
                "required": ["features"]
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
    base = """You are an expert coding agent for the OpenShrimp AI App Store platform.

You have the following tools available:
- **ls**: List files and directories
- **read**: Read file content
- **write**: Write/create files (creates parent dirs automatically)
- **edit**: Replace a specific text snippet in a file (for targeted edits without rewriting the whole file)
- **bash**: Run shell commands
- **update_app_features**: Update the app's frontend UI features (e.g. enable file upload button in chat)

Your working directory is: __CWD_PLACEHOLDER__

## Platform architecture

Every sub-app lives in its own directory under `backend/apps/<app_id>/` and MUST have:
- `__init__.py` (can be empty)
- `main.py` (the entry point, containing the FastAPI APIRouter)

### File structure guidelines

For **simple apps** (< 150 lines of logic), a single `main.py` is sufficient. Keep it simple.

For **medium to complex apps** (150+ lines, or with distinct concerns), split the code into multiple files. **You decide the file names and structure** based on the app's actual needs — there is no fixed template. Use domain-appropriate names (e.g. `analyzer.py`, `generator.py`, `parser.py`) rather than generic ones.

The ONLY mandatory files are:
- `__init__.py` (can be empty)
- `main.py` (entry point: router + `handle_chat` function)

**Guidelines for splitting** (not rules — use your judgment):
- `main.py` should be a **thin controller**: only route definitions, request parsing, and calling functions from other files. Aim for < 100 lines.
- Group related logic into files by domain (e.g. `translator.py`, `data_processor.py`), not by layer
- If the app uses LLM prompts, keeping them in a separate file (e.g. `prompts.py`) makes them easier to tune
- Use relative imports between files in the same app: `from .my_module import MyClass`

Sub-apps can import shared services:
```python
from backend.core.llm_service import chat_completion
from backend.core.asr_service import transcribe
```

### Shared File Toolkit (IMPORTANT — use this instead of writing file operations from scratch!)

The platform provides a powerful file toolkit at `backend.core.file_toolkit`. **Always use this for file operations** instead of writing PDF/PPT/Excel code from scratch.

```python
from backend.core.file_toolkit import (
    # PDF
    parse_pdf,           # parse_pdf(file_path) -> str (extracted text)
    generate_pdf,        # generate_pdf(content, title=...) -> Path
    # PPT
    generate_ppt,        # generate_ppt(slides=[{"title": ..., "content": [...], "notes": ...}], title=..., style=...) -> Path
    # Excel / CSV
    parse_excel,         # parse_excel(file_path, sheet_name=...) -> {"headers": [...], "rows": [...], "row_count": int}
    generate_excel,      # generate_excel(data=[{"col": val, ...}], sheet_name=..., headers=...) -> Path
    generate_csv,        # generate_csv(data, headers=...) -> Path
    # Word
    parse_docx,          # parse_docx(file_path) -> str (extracted text)
    # Charts / Images
    generate_chart,      # generate_chart("bar"|"line"|"pie"|"scatter"|"histogram", data, title=...) -> Path
    # Download URL management
    register_download,   # register_download(file_path, filename=...) -> token (str)
    get_download_url,    # get_download_url(token) -> "/api/files/download/{token}"
    # Convenience: generate + register in one step
    generate_and_register_pdf,   # -> {"token": ..., "url": ..., "path": ..., "markdown_link": "[📥 下载 file.pdf](/api/files/download/xxx)"}
    generate_and_register_ppt,   # -> {"token": ..., "url": ..., "path": ..., "markdown_link": "[📥 下载 file.pptx](/api/files/download/xxx)"}
    generate_and_register_excel, # -> {"token": ..., "url": ..., "path": ..., "markdown_link": "[📥 下载 file.xlsx](/api/files/download/xxx)"}
    generate_and_register_chart, # -> {"token": ..., "url": ..., "path": ..., "markdown_link": ..., "image_embed": "![chart](/api/files/preview/xxx)", "preview_url": ...}
    register_existing_file,      # -> {"token": ..., "url": ..., "path": ..., "markdown_link": "[📥 下载 file](/api/files/download/xxx)"}
    # Text / String utilities
    truncate_text,         # truncate_text(text, max_length=500) -> str
    extract_json_from_text,# extract_json_from_text(llm_response) -> parsed JSON or None
    sanitize_filename,     # sanitize_filename(name) -> safe filename str
    # Markdown / HTML
    markdown_to_html,      # markdown_to_html(md) -> html str
    format_table_as_markdown, # format_table_as_markdown(headers, rows) -> markdown table str
    # Data utilities
    flatten_dict,          # flatten_dict({"a": {"b": 1}) -> {"a.b": 1}
    chunk_list,            # chunk_list([1,2,3,4,5], 2) -> [[1,2],[3,4],[5]]
    # Date / Time
    format_datetime,       # format_datetime(dt=None, fmt=...) -> str (defaults to now)
    # Download Link Helper (RECOMMENDED — simplest way to serve files)
    make_download_link,    # make_download_link(file_path, label=..., filename=...) -> "[📥 下载 file.pdf](/api/files/download/xxx)"
    # Preview / Inline Display Helpers (for images, charts, PDFs displayed in chat)
    get_preview_url,       # get_preview_url(token) -> "/api/files/preview/{token}"
    make_preview_link,     # make_preview_link(file_path, label=...) -> "[🔍 预览 file.pdf](/api/files/preview/xxx)"
    make_image_embed,      # make_image_embed(file_path, alt_text=...) -> "![chart](/api/files/preview/xxx)" (displays image inline in chat)
)
```

### ⚠️ File Download Rules (CRITICAL — read carefully!)

**NEVER** construct download URLs manually. **NEVER** use `http://localhost:...` or any absolute URL for downloads. The frontend ONLY recognises relative paths matching `/api/files/download/` rendered as **Markdown links**. Violating these rules will result in broken, non-clickable links.

**Simplest approach — use `make_download_link()` (RECOMMENDED):**
```python
from backend.core.file_toolkit import generate_ppt, make_download_link

# Step 1: Generate the file
path = generate_ppt(slides=[...], title="My PPT", style="professional")

# Step 2: One function call returns a ready-to-use Markdown link
link = make_download_link(path, label="下载演示文稿", filename="presentation.pptx")
# link = "[📥 下载演示文稿](/api/files/download/abc123...)"

# Step 3: Embed in your reply
return {"content": f"文件已生成！\\n\\n{link}"}
```

**Alternative — use `generate_and_register_*()` convenience functions:**
```python
from backend.core.file_toolkit import generate_and_register_ppt

result = generate_and_register_ppt(
    slides=[{"title": "Hello", "content": ["Point 1", "Point 2"]}],
    title="My Presentation",
    style="professional",
)
# result has: token, url, path, markdown_link
# Use result["markdown_link"] directly in the reply:
return {"content": f"PPT generated!\\n\\n{result['markdown_link']}"}
```

**Alternative — manual register (for custom file types):**
```python
from backend.core.file_toolkit import register_download, get_download_url

token = register_download(file_path, filename="report.pdf")
url = get_download_url(token)  # ALWAYS relative: "/api/files/download/xxx"
# You MUST format it as a Markdown link:
return {"content": f"[📥 下载报告]({url})"}
```

**Rules summary:**
1. ✅ Use `make_download_link()` — returns a Markdown link, zero boilerplate
2. ✅ Use `result["markdown_link"]` from `generate_and_register_*()` — also returns a Markdown link
3. ✅ Always use **relative paths** (`/api/files/download/xxx` or `/api/files/preview/xxx`)
4. ✅ Always format as **Markdown links** (`[📥 text](url)`)
5. ❌ NEVER hardcode `http://localhost:8000` or any absolute URL
6. ❌ NEVER return a raw URL as plain text (it won't be clickable)

### 📊 Displaying Charts / Images Inline in Chat

If your app generates chart images or any images that should be **displayed inline** in the chat (not downloaded), use the **preview** endpoint instead:

```python
# Option A: Use make_image_embed() (RECOMMENDED for images/charts)
from backend.core.file_toolkit import generate_chart, make_image_embed

path = generate_chart("bar", {"labels": ["A", "B"], "values": [10, 20]}, title="Sales")
img_tag = make_image_embed(path, alt_text="Sales Chart")
# img_tag = "![Sales Chart](/api/files/preview/xxx)"
return {"content": f"Here is the chart:\\n\\n{img_tag}"}

# Option B: Use generate_and_register_chart() with image_embed
from backend.core.file_toolkit import generate_and_register_chart

result = generate_and_register_chart("bar", data, title="Sales")
# result["image_embed"] = "![Sales](/api/files/preview/xxx)"  <-- inline display
# result["markdown_link"] = "[📥 下载 chart.png](/api/files/download/xxx)"  <-- download link
return {"content": f"{result['image_embed']}\\n\\n{result['markdown_link']}"}
```

**Image Rules:**
- ✅ Use `make_image_embed()` or `result["image_embed"]` for inline chart/image display
- ✅ Use `/api/files/preview/xxx` for inline display (Content-Disposition: inline)
- ✅ Use `/api/files/download/xxx` for file downloads (Content-Disposition: attachment)
- ✅ Use Markdown image syntax `![alt](url)` — the frontend renders these as styled images

**Supported styles for PPT:** "professional", "creative", "minimal", "academic"

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
    messages: list[dict],  # [{"role": "user"|"assistant"|"system", "content": "..."}]
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
    system_msg = {"role": "system", "content": "You are a helpful assistant."}
    return await chat_completion([system_msg] + messages)
```

### Good example (complex app returning structured data):
```python
async def handle_chat(messages: list[dict], *, config: dict | None = None) -> dict:
    # Complex: do processing and return dict with 'content' key.
    user_msg = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    result = await my_complex_processing(user_msg)
    return {
        "content": f"Here's your result: {result['summary']}",  # <-- user-facing reply
        "data": result["data"],  # additional structured data
    }
```

### BAD example (DO NOT do this):
```python
async def handle_chat(messages, *, config=None) -> dict:
    result = await some_processing(...)
    return {
        "session_id": "...",
        "response": "done",  # 'response' is lowest priority, not ideal
        "slides": [...],
    }
    # Problem: no 'content' key -> platform falls through to str(result) -> user sees garbage
```

### LLM Prompt Engineering Tips
If your app calls an LLM (via `chat_completion`):
- Design clear, specific system prompts that constrain the output format
- If you need JSON from the LLM, provide examples and use `json.loads()` with try/except fallback
- Test your prompts mentally: would the LLM understand what format to return?
- For multi-step generation (e.g. outlines → content), validate each step's output before proceeding

## UI Features (Frontend Capabilities)

The platform's generic chat UI can dynamically enable extra UI components based on the app's config. Use the `update_app_features` tool to toggle these features.

### Available features:
- **`file_upload`**: Adds a file upload button (📎) to the chat input. When a user uploads a file, the platform saves it and attaches file metadata to the chat message. Your `handle_chat` function will receive messages with a `files` field:
  ```python
  # Message with file attachment:
  {"role": "user", "content": "Analyze this file", "files": [{"path": "/data/uploads/app_id/abc123.pdf", "name": "report.pdf", "size": 12345}]}
  ```

### When to use:
- If the user requests file upload functionality (e.g. "add file upload", "support uploading documents"), you should:
  1. Call `update_app_features` with `features: ["file_upload"]` to enable the upload button in the UI
  2. Modify `handle_chat` to read and process files from `message.get("files", [])`
  3. Both steps are required — the backend code handles the file, the feature flag shows the UI

### Example:
```python
async def handle_chat(messages, *, config=None):
    user_msg = messages[-1] if messages else {}
    text = user_msg.get("content", "")
    files = user_msg.get("files", [])
    
    if files:
        # Process uploaded files
        for f in files:
            file_path = f["path"]
            file_name = f["name"]
            # Read and process the file...
    
    return {"content": "Processing complete!"}
```

## Dependency management

Each app has its own isolated virtual environment at `.venv/` inside its directory.
- Before writing code, think about what third-party packages the app needs
- **IMPORTANT**: Check the Shared File Toolkit first! If your app needs PDF/PPT/Excel/CSV/Word operations, use `backend.core.file_toolkit` instead of writing those from scratch. This saves time and avoids dependency issues.
- After writing code, create a `requirements.txt` file listing all third-party dependencies (one per line, with version pins)
- The platform will automatically install dependencies from `requirements.txt` into the app's `.venv` before running
- Do NOT include packages that are already available from the platform (fastapi, pydantic, sqlalchemy, openai, python-pptx, pandas, openpyxl, PyPDF2, python-docx, matplotlib, etc.)
- Only list packages that are specific to THIS app's functionality

Example `requirements.txt` for an app that generates charts:
```
matplotlib>=3.7.0
numpy>=1.24.0
```

## Your workflow

1. **First**: Use `ls` to examine the current directory structure
2. **Assess complexity**: Estimate how complex the app will be based on what it needs to do
3. **Plan**: Decide the file structure based on the app's actual needs — simple apps need fewer files
4. **Implement**: Use `write` to create new files, and `edit` to make targeted changes to existing files.
   - Use `write` when creating a file from scratch or when you need to rewrite most of its content
   - Use `edit` when you only need to change a small part of an existing file (e.g. fix a bug, add a function, modify an import). This is more efficient and less error-prone than rewriting the whole file.
   - `edit` requires an exact match of `old_string` — always `read` the file first to get the precise text
5. **Dependencies**: If the app needs third-party packages, create a `requirements.txt`
6. **Verify**: Use `ls` and `read` to verify files were created correctly

## Logging in generated code (IMPORTANT)

Always add meaningful `print()` or `logging` statements in the generated app code, especially:
- At the start of `handle_chat`: log the user input (truncated)
- Before and after LLM calls: log what's being sent and a summary of what was returned
- On errors: log the full exception with traceback
- At key decision points: log what path the code is taking and why

This helps with debugging when the app doesn't behave as expected. Example:
```python
async def handle_chat(messages, *, config=None):
    user_msg = messages[-1]["content"] if messages else ""
    print(f"[my_app] handle_chat called | input_len={len(user_msg)}")
    try:
        result = await process(user_msg)
        print(f"[my_app] process done | result_type={type(result).__name__}")
        return result
    except Exception as e:
        print(f"[my_app] ERROR: {type(e).__name__}: {e}")
        raise
```

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

    # Replace the placeholder with actual cwd value
    base = base.replace("__CWD_PLACEHOLDER__", cwd)

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

        elif tool_name == "edit":
            file_path = params.get("file_path", "").strip()
            old_string = params.get("old_string", "")
            new_string = params.get("new_string", "")
            target = Path(cwd) / file_path if not Path(file_path).is_absolute() else Path(file_path)
            if not target.exists():
                return f"Error: File not found: {target}"
            content = target.read_text(encoding="utf-8", errors="replace")
            if old_string not in content:
                # Try to help the agent: show a snippet around approximate location
                return (
                    f"Error: old_string not found in {target}. "
                    f"Make sure the text matches exactly (including whitespace and indentation). "
                    f"Use 'read' to check the current file content first."
                )
            count = content.count(old_string)
            if count > 1:
                return (
                    f"Error: old_string found {count} times in {target}. "
                    f"Provide more surrounding context to make the match unique."
                )
            new_content = content.replace(old_string, new_string, 1)
            target.write_text(new_content, encoding="utf-8")
            old_lines = old_string.count("\n") + 1
            new_lines = new_string.count("\n") + 1
            return f"Successfully edited {target}: replaced {old_lines} lines with {new_lines} lines"

        elif tool_name == "update_app_features":
            # Update the app's UI feature flags in the platform config
            features = params.get("features", [])
            if not isinstance(features, list):
                return "Error: features must be a list of strings"
            # Determine the app_id from the cwd (last directory component under backend/apps/)
            cwd_path = Path(cwd) if cwd else None
            if not cwd_path:
                return "Error: No working directory set"
            parts = cwd_path.parts
            app_id_from_cwd = parts[-1] if parts else None
            if not app_id_from_cwd:
                return "Error: Could not determine app_id from working directory"

            # Use synchronous sqlite3 to avoid async event loop issues
            import sqlite3
            db_path = "data/platform.db"
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.execute("SELECT config_json FROM apps WHERE id = ?", (app_id_from_cwd,))
                row = cursor.fetchone()
                if not row:
                    conn.close()
                    return f"Error: App '{app_id_from_cwd}' not found in registry"
                config = json.loads(row[0]) if row[0] else {}
                config["features"] = features
                conn.execute("UPDATE apps SET config_json = ? WHERE id = ?", (json.dumps(config), app_id_from_cwd))
                conn.commit()
                conn.close()
                return f"Successfully updated app '{app_id_from_cwd}' features: {features}"
            except Exception as e:
                return f"Error updating app features: {type(e).__name__}: {e}"

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
    elif tool_name == "edit":
        fp = params.get("file_path", "?")
        old_s = params.get("old_string", "")
        new_s = params.get("new_string", "")
        return f"file={fp} (replace {len(old_s)} chars with {len(new_s)} chars)"
    elif tool_name == "update_app_features":
        features = params.get("features", [])
        return f"features={features}"
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

# ─────────────────────────────────────────────────
# Capability scope check — refuse requests beyond platform abilities
# ─────────────────────────────────────────────────

async def _check_capability_scope(description: str) -> dict:
    """
    Use LLM to quickly evaluate whether the user's request is within
    the platform's capability scope.

    The platform can handle:
    - Self-contained apps that process text, generate content, analyze data
    - Apps that call LLM APIs for generation/analysis
    - Simple file processing (Excel, PDF, images)
    - Lightweight utilities (converters, formatters, calculators)

    The platform CANNOT handle:
    - Apps requiring external databases (MySQL, PostgreSQL, Redis clusters)
    - Apps requiring persistent background services or workers
    - Apps requiring external API keys the platform doesn't have
    - Large-scale systems (recommendation engines, search engines, training pipelines)
    - Apps requiring real-time external data feeds (stock prices, weather)
    - Apps requiring user authentication systems beyond what the platform provides

    Returns: {"feasible": bool, "reason": str, "suggestion": str}
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are a capability evaluator for a lightweight AI App Store platform. "
                "The platform can create small, self-contained Python FastAPI apps that: "
                "1) Process user text input and generate responses via LLM, "
                "2) Analyze uploaded files (Excel, PDF, text), "
                "3) Generate content (text, simple charts, formatted output), "
                "4) Perform calculations, conversions, formatting. "
                "\nThe platform CANNOT: "
                "1) Set up external databases, message queues, or caching clusters, "
                "2) Access real-time external data (stock prices, live weather, web scraping), "
                "3) Run persistent background workers or scheduled tasks, "
                "4) Build full-stack web apps with their own frontend, "
                "5) Train or fine-tune ML models, "
                "6) Access APIs requiring keys the platform doesn't provide. "
                "\nIMPORTANT: Be generous — if the app can work in a simplified/self-contained way, "
                "it IS feasible. Only reject clearly impossible requests. "
                "For example, 'build a todo list' is feasible (can use in-memory or file storage). "
                "'Build a recommendation system' using LLM is feasible (LLM-based recommendations). "
                "'Build a real-time stock trading bot' is NOT feasible. "
                "\nOutput ONLY a JSON object: {\"feasible\": true/false, \"reason\": \"...\", \"suggestion\": \"...\"} "
                "If feasible, reason should be empty and suggestion should be empty. "
                "If not feasible, reason should explain why, and suggestion should offer a simpler alternative the platform CAN do."
            ),
        },
        {"role": "user", "content": f"User request: {description}"},
    ]
    try:
        raw = await chat_completion(messages, temperature=0.1, max_tokens=300)
        raw = _strip_thinking(raw).strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = raw[:-3]
        result = json.loads(raw.strip())
        if not isinstance(result, dict) or "feasible" not in result:
            return {"feasible": True, "reason": "", "suggestion": ""}
        return result
    except Exception:
        # If the check itself fails, don't block — assume feasible
        return {"feasible": True, "reason": "", "suggestion": ""}


# ─────────────────────────────────────────────────
# App venv management — isolated dependencies per app
# ─────────────────────────────────────────────────

def _ensure_app_venv(app_dir: str) -> str:
    """
    Ensure the app has its own .venv directory.
    Creates one if it doesn't exist.
    Returns the path to the venv's Python executable.
    """
    venv_dir = Path(app_dir) / ".venv"
    python_path = venv_dir / "bin" / "python"
    if not venv_dir.exists():
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", str(venv_dir)],
                capture_output=True, text=True, timeout=60,
            )
        except Exception as e:
            print(f"[venv] Failed to create venv at {venv_dir}: {e}")
            return sys.executable  # Fallback to system Python
    return str(python_path) if python_path.exists() else sys.executable


def _check_and_install_deps(app_dir: str) -> dict:
    """
    Check if the app's .venv has all required packages installed.
    If requirements.txt exists and some packages are missing, install them.

    Returns: {"ok": bool, "installed": list[str], "errors": list[str]}
    """
    req_file = Path(app_dir) / "requirements.txt"
    if not req_file.exists():
        return {"ok": True, "installed": [], "errors": []}

    python_path = _ensure_app_venv(app_dir)
    venv_dir = Path(app_dir) / ".venv"
    pip_path = venv_dir / "bin" / "pip"

    if not pip_path.exists():
        # No venv pip, fall back to system pip
        pip_path = Path(sys.executable).parent / "pip"
        if not pip_path.exists():
            return {"ok": False, "installed": [], "errors": ["pip not found"]}

    # Read requirements
    requirements = []
    for line in req_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            requirements.append(line)

    if not requirements:
        return {"ok": True, "installed": [], "errors": []}

    # Check which packages are already installed
    try:
        result = subprocess.run(
            [str(pip_path), "freeze"],
            capture_output=True, text=True, timeout=30,
        )
        installed_pkgs = set()
        for line in result.stdout.splitlines():
            pkg_name = line.split("==")[0].split(">=")[0].split("<=")[0].strip().lower()
            if pkg_name:
                installed_pkgs.add(pkg_name)
    except Exception:
        installed_pkgs = set()

    # Find missing packages
    missing = []
    for req in requirements:
        pkg_name = req.split("==")[0].split(">=")[0].split("<=")[0].split("[")[0].strip().lower()
        if pkg_name not in installed_pkgs:
            missing.append(req)

    if not missing:
        return {"ok": True, "installed": [], "errors": []}

    # Install missing packages
    installed = []
    errors = []
    for pkg in missing:
        try:
            result = subprocess.run(
                [str(pip_path), "install", pkg],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                installed.append(pkg)
            else:
                errors.append(f"{pkg}: {result.stderr.strip()[-200:]}")
        except subprocess.TimeoutExpired:
            errors.append(f"{pkg}: installation timed out")
        except Exception as e:
            errors.append(f"{pkg}: {e}")

    return {"ok": len(errors) == 0, "installed": installed, "errors": errors}


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
    print(f"[api] POST /generate | app_id={req.app_id} | base_app_id={req.base_app_id} | session={session_id} | desc_len={len(req.description)}")
    print(f"[api] Description: {req.description[:200]}")

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
            print(f"[agent] Working directory resolved: {cwd} | is_edit={bool(req.app_id)} | inferred_app_id={inferred_app_id}")

            yield _sse({"type": "start", "method": "agentic-loop", "app_id": req.app_id, "session_id": session_id})
            yield _sse({"type": "log", "message": f"Working directory: {cwd}"})
            yield _sse({"type": "log", "message": f"Model: {llm_settings.model}"})
            yield _sse({"type": "log", "message": f"Max iterations: {MAX_ITERATIONS} (with auto context compression)"})

            # Capability scope check (only for new apps, not modifications)
            if not req.app_id:
                yield _sse({"type": "log", "message": "🔍 Checking capability scope..."})
                scope_result = await _check_capability_scope(req.description)
                if not scope_result.get("feasible", True):
                    reason = scope_result.get("reason", "Request exceeds platform capabilities")
                    suggestion = scope_result.get("suggestion", "")
                    msg = f"⚠️ This request may be beyond the platform's capabilities: {reason}"
                    if suggestion:
                        msg += f"\n💡 Suggestion: {suggestion}"
                    yield _sse({"type": "scope_warning", "message": msg, "reason": reason, "suggestion": suggestion})
                    yield _sse({"type": "done", "output": msg, "files_modified": [], "app_id": None})
                    return
                yield _sse({"type": "log", "message": "✅ Request is within platform capabilities"})

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
            print(f"[agent] Starting agentic loop | cwd={cwd} | msgs={len(messages)} | is_edit={bool(req.app_id)}")

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
            print(f"[agent] Agentic loop finished | files_modified={files_modified} | output_len={len(full_output)}")
            new_app_id = req.app_id
            if not new_app_id:
                new_app_id = await _discover_and_register_app(req.description, cwd, inferred_app_id)
                print(f"[agent] Discovered app_id: {new_app_id}")
            else:
                print(f"[agent] Using existing app_id: {new_app_id}")

            if new_app_id and files_modified:
                print(f"[agent] Running self-verification for '{new_app_id}' | files={files_modified}")
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

                # Setup venv and install dependencies for the new app
                yield _sse({"type": "log", "message": "📦 Setting up app environment..."})
                _ensure_app_venv(cwd)
                deps_result = _check_and_install_deps(cwd)
                if deps_result["installed"]:
                    yield _sse({"type": "log", "message": f"📦 Installed: {', '.join(deps_result['installed'])}"})
                if deps_result["errors"]:
                    for err in deps_result["errors"]:
                        yield _sse({"type": "log", "message": f"⚠️ Dep install error: {err}"})
                if deps_result["ok"]:
                    yield _sse({"type": "log", "message": "✅ App environment ready"})

                print(f"[agent] Reloading app module '{new_app_id}'...")
                try:
                    app_registry.reload_app_module(new_app_id)
                    print(f"[agent] ✅ reload_app_module succeeded for '{new_app_id}'")
                    yield _sse({"type": "log", "message": f"✅ App module '{new_app_id}' reloaded successfully"})
                except Exception as e:
                    print(f"[agent] ⚠️ reload_app_module failed for '{new_app_id}': {e}")
                    import traceback as _tb
                    _tb.print_exc()
                    yield _sse({"type": "log", "message": f"⚠️ Module reload failed: {e}. App may need a server restart."})

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

            print(f"[agent] ✅ Agent session complete | app_id={new_app_id} | files_modified={files_modified} | output_len={len(full_output)}")
            yield _sse({
                "type": "done",
                "output": full_output[:3000],
                "files_modified": files_modified,
                "app_id": new_app_id,
            })
        except Exception as _gen_err:
            print(f"[agent] ❌ CRITICAL ERROR in event_stream: {_gen_err}")
            import traceback as _tb
            _tb.print_exc()
            yield _sse({"type": "error", "error": f"Internal error: {_gen_err}"})
        finally:
            print(f"[agent] Session {session_id} destroyed")
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
                "You are a naming assistant. Your ONLY job is to generate a short, descriptive snake_case "
                "identifier (like a Python package name) that summarizes the PURPOSE of the app.\n\n"
                "Rules:\n"
                "- 2-4 English words joined by underscores, e.g. 'todo_list', 'ppt_generator', 'weather_bot'\n"
                "- Lowercase letters, digits, and underscores ONLY\n"
                "- 3-30 characters total\n"
                "- Must describe WHAT the app does, NOT what the user said\n"
                "- Do NOT include words like 'app', 'user', 'want', 'create', 'make', 'build', 'please'\n"
                "- Do NOT repeat or paraphrase the user's sentence\n\n"
                "Examples:\n"
                "  User: '帮我做一个生成PPT的工具' → ppt_generator\n"
                "  User: 'I want to build a todo list app' → todo_list\n"
                "  User: '做一个能分析CSV数据的应用' → csv_analyzer\n"
                "  User: '写一个天气查询机器人' → weather_query\n"
                "  User: '帮我写一个记账本' → expense_tracker\n"
                "  User: '做个图片压缩工具' → image_compressor\n\n"
                "Output ONLY the identifier, nothing else. No quotes, no backticks, no explanation."
            ),
        },
        {"role": "user", "content": description},
    ]
    import re
    try:
        raw = await chat_completion(messages, temperature=0.1, max_tokens=50)
        raw = _strip_thinking(raw).strip().strip('"').strip("'").strip('`').strip()
        # Sanitize: only allow valid Python identifier chars
        sanitized = re.sub(r'[^a-z0-9_]', '_', raw.lower())
        # Collapse multiple underscores and strip leading/trailing
        sanitized = re.sub(r'_+', '_', sanitized).strip('_')
        # Reject if it still looks like a sentence or contains noise words
        noise_words = {'the', 'user', 'wants', 'want', 'me', 'to', 'generate', 'create',
                       'make', 'build', 'please', 'help', 'app', 'application', 'a', 'an'}
        parts = sanitized.split('_')
        cleaned_parts = [p for p in parts if p and p not in noise_words]
        if cleaned_parts:
            sanitized = '_'.join(cleaned_parts)[:30]
        if sanitized and len(sanitized) >= 3:
            # Check for directory collision, append suffix if needed
            candidate = APPS_DIR / sanitized
            if candidate.exists():
                for i in range(2, 100):
                    alt = f"{sanitized[:26]}_{i}"
                    if not (APPS_DIR / alt).exists():
                        return alt
            return sanitized
    except Exception:
        pass
    # Fallback: extract meaningful words from description
    words = re.findall(r'[a-zA-Z]+', description)
    # Filter out noise words
    noise = {'the', 'a', 'an', 'i', 'want', 'to', 'make', 'create', 'build', 'help',
             'me', 'please', 'app', 'write', 'do', 'generate', 'user', 'wants'}
    meaningful = [w.lower() for w in words if w.lower() not in noise and len(w) > 1][:3]
    fallback = '_'.join(meaningful) if meaningful else f"app_{__import__('uuid').uuid4().hex[:6]}"
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

    IMPORTANT: Ensures assistant+tool message pairs are never split apart, as the OpenAI API
    requires tool-role messages to immediately follow the assistant message containing the
    corresponding tool_calls. Splitting them causes API errors or hangs.
    """
    if len(messages) <= keep_last_n + 2:
        return messages  # Nothing to compress

    system_msg = messages[0]
    body = messages[1:]  # Everything except system message

    # --- Find a safe split point that doesn't break assistant↔tool pairs ---
    # Walk backwards from the desired split point to find a safe boundary.
    # A safe boundary is a position where the message is NOT a "tool" role
    # (i.e., we don't start the "recent" slice in the middle of tool responses).
    desired_keep = keep_last_n
    split_idx = len(body) - desired_keep

    # Ensure split_idx >= 1 so we have something to compress
    if split_idx < 1:
        return messages

    # Walk backwards: if body[split_idx] is a "tool" message, move split_idx earlier
    # until we hit an "assistant" message (which owns the tool_calls), and include it.
    while split_idx > 0 and body[split_idx].get("role") == "tool":
        split_idx -= 1
    # Now body[split_idx] should be the "assistant" message that owns the tool_calls.
    # Include it in the "recent" portion so the pair stays intact.

    middle = body[:split_idx]
    recent = body[split_idx:]

    if not middle:
        return messages  # Nothing to compress

    # --- Build condensed text for summarization ---
    middle_parts = []
    for msg in middle:
        role = msg.get("role", "")
        content = msg.get("content", "") or ""
        # Skip tool-role messages in summary (they are verbose tool outputs)
        if role == "tool":
            content = content[:150] + "..." if len(content) > 150 else content
        elif len(content) > 400:
            content = content[:400] + "..."
        middle_parts.append(f"[{role}]: {content}")
    middle_text = "\n".join(middle_parts)

    # Limit the total input to the summarization call
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
        summary = await asyncio.wait_for(
            chat_completion(
                [
                    {"role": "system", "content": "You are a conversation summarizer. Output a concise structured summary."},
                    {"role": "user", "content": compress_prompt},
                ],
                temperature=0.1,
                max_tokens=1000,
            ),
            timeout=60.0,  # 60-second hard timeout to prevent hangs
        )
        summary = _strip_thinking(summary).strip()
    except asyncio.TimeoutError:
        summary = f"[Context compressed: {len(middle)} messages summarized (summarization timed out). Recent context preserved.]"
    except Exception:
        # If summarization fails, do a crude truncation
        summary = f"[Context compressed: {len(middle)} messages summarized. Recent context preserved.]"

    # --- Clean recent messages: strip reasoning_content to avoid API issues ---
    cleaned_recent = []
    for msg in recent:
        cleaned = dict(msg)
        # Remove reasoning_content from compressed context — it's for the API's internal
        # use and can cause issues when replayed in a new conversation sequence
        cleaned.pop("reasoning_content", None)
        cleaned_recent.append(cleaned)

    compressed = [
        system_msg,
        {
            "role": "user",
            "content": f"## Context Summary (compressed from {len(middle)} earlier messages)\n\n{summary}\n\n---\nContinue from where you left off. The recent messages below show the latest state.",
        },
        *cleaned_recent,
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
            # Log tool execution details to server console
            is_success = not result.startswith("Error")
            print(f"[agent] Tool '{tool_name}' | params={_summarize_tool_params(tool_name, params)} | success={is_success} | result_len={len(result)}")
            if not is_success:
                print(f"[agent] Tool '{tool_name}' ERROR: {result[:300]}")
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

            if tool_name in ("write", "edit"):
                fp = params.get("file_path", "").strip()
                if fp and fp not in files_modified:
                    files_modified.append(fp)
                    print(f"[agent] File modified: {fp} (total: {len(files_modified)})")
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
