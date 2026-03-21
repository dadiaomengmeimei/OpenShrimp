"""
Core business logic for PPT Generator.
Handles LLM orchestration, PPT generation, and session management.
Uses shared file_toolkit for PPT creation and download URL management.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any

from backend.core.llm_service import chat_completion
from backend.core.file_toolkit import (
    generate_ppt as toolkit_generate_ppt,
    make_download_link,
    extract_json_from_text,
)
from . import config
from .models import Slide, ChatMessage, PPTSession
from .prompts import (
    PPT_GENERATION_SYSTEM,
    PPT_UPDATE_SYSTEM,
    STYLE_DESCRIPTIONS,
)


# In-memory session storage (in production, use a database)
_sessions: Dict[str, PPTSession] = {}


def _create_pptx_file(session: PPTSession) -> Path:
    """Create a PowerPoint file from session data using the shared file_toolkit."""
    output_path = config.PPT_OUTPUT_DIR.resolve() / f"{session.session_id}.pptx"

    # Convert Slide model objects into the dict format expected by the toolkit
    slides_data = []
    for s in session.slides:
        slides_data.append({
            "title": s.title,
            "content": s.content,
            "notes": s.notes or "",
        })

    filepath = toolkit_generate_ppt(
        slides_data,
        output_path=output_path,
        title=session.topic,
        style=session.style,
    )
    return filepath


def _register_and_get_download_link(filepath: Path, session: PPTSession) -> str:
    """Register a generated file for download and return a Markdown download link."""
    safe_topic = session.topic[:50].replace("/", "_").replace("\\", "_").replace(":", "_")
    return make_download_link(filepath, label=f"下载 PPT", filename=f"{safe_topic}.pptx")


def _validate_and_create_slides(slides_data: List[Dict[str, Any]], min_count: int = 3) -> List[Slide]:
    """Validate slide data and create Slide objects."""
    slides = []
    for slide_data in slides_data:
        if not isinstance(slide_data, dict):
            continue
        slide = Slide(
            title=slide_data.get("title", "Untitled"),
            content=slide_data.get("content", []) if isinstance(slide_data.get("content"), list) else [],
            notes=slide_data.get("notes")
        )
        slides.append(slide)

    # Ensure minimum slides
    if len(slides) < min_count:
        while len(slides) < min_count:
            slides.append(Slide(
                title=f"补充内容 {len(slides) + 1}" if min_count == 3 else f"Supplementary Content {len(slides) + 1}",
                content=["可根据需要添加更多内容"],
                notes="此幻灯片可以添加更多内容"
            ))

    return slides


async def generate_ppt_from_topic(
    topic: str,
    style: str = "professional",
    language: str = "zh",
    slide_count: Optional[int] = None,
) -> PPTSession:
    """Generate a new PPT presentation from a topic."""
    session_id = uuid.uuid4().hex[:12]

    # Build prompt for LLM with better structure requirements
    system_prompt = PPT_GENERATION_SYSTEM.format(language="Chinese" if language == "zh" else "English")

    user_prompt = f"""请创建一个关于"{topic}"的 PPT 演示文稿大纲。

要求：
- 风格：{style}
- 语言：{language}
- 幻灯片数量：{slide_count or '自动确定（建议 5-15 页）'}

请返回 JSON 数组格式，每个元素包含：
- title: 幻灯片标题（简洁有力，不超过 10 个字）
- content: 关键点数组（每条不超过 15 个字，3-6 条）
- notes: 可选的演讲者备注

结构要求：
1. 第一页：标题页（主题 + 副标题）
2. 第二页：目录/概览
3. 中间页：主要内容（按逻辑分块）
4. 最后一页：总结/展望

确保内容结构清晰、逻辑连贯。"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # Call LLM
    response = await chat_completion(messages)

    # Parse JSON response using shared toolkit
    slides_data = extract_json_from_text(response)

    if slides_data and isinstance(slides_data, list):
        slides = _validate_and_create_slides(slides_data, config.MIN_SLIDE_COUNT)
    else:
        # Fallback: create a well-structured basic outline
        if language == "zh":
            slides = [
                Slide(title=topic, content=[f"关于{topic}的全面介绍"], notes="标题页"),
                Slide(title="目录", content=["第一部分：背景介绍", "第二部分：核心内容", "第三部分：总结展望"], notes="内容概览"),
                Slide(title="背景介绍", content=["相关概念定义", "发展现状分析", "重要性说明"], notes="介绍背景知识"),
                Slide(title="核心内容", content=["关键点一详细说明", "关键点二详细说明", "关键点三详细说明"], notes="主要内容展示"),
                Slide(title="总结展望", content=["要点回顾", "未来发展方向", "感谢聆听"], notes="总结全文"),
            ]
        else:
            slides = [
                Slide(title=topic, content=[f"Comprehensive introduction to {topic}"], notes="Title slide"),
                Slide(title="Table of Contents", content=["Part 1: Introduction", "Part 2: Main Content", "Part 3: Summary"], notes="Overview"),
                Slide(title="Introduction", content=["Key concepts defined", "Current status analysis", "Importance explained"], notes="Background info"),
                Slide(title="Main Content", content=["Key point one detailed", "Key point two detailed", "Key point three detailed"], notes="Core content"),
                Slide(title="Summary", content=["Key points review", "Future outlook", "Thank you"], notes="Conclusion"),
            ]

    # Limit max slides
    if slide_count and len(slides) > slide_count:
        slides = slides[:slide_count]
    elif len(slides) > config.MAX_SLIDE_COUNT:
        slides = slides[:config.MAX_SLIDE_COUNT]

    # Generate PPT file FIRST (before creating session)
    temp_session = PPTSession(
        session_id=session_id,
        topic=topic,
        style=style,
        language=language,
        slides=slides,
        chat_history=[],
        ppt_file_path=None
    )
    filepath = _create_pptx_file(temp_session)

    # Create session with the file path already set
    session = PPTSession(
        session_id=session_id,
        topic=topic,
        style=style,
        language=language,
        slides=slides,
        chat_history=[
            ChatMessage(role="user", content=f"Generate PPT about {topic}"),
            ChatMessage(role="assistant", content=f"Generated {len(slides)}-page PPT outline")
        ],
        ppt_file_path=str(filepath)
    )

    # Store session
    _sessions[session.session_id] = session

    return session


async def update_ppt_session(
    session_id: str,
    instruction: str,
    style: Optional[str] = None,
    language: Optional[str] = None,
) -> PPTSession:
    """Update an existing PPT session based on user instruction."""
    if session_id not in _sessions:
        raise ValueError(f"Session {session_id} not found")

    session = _sessions[session_id]

    # Update style/language if provided
    if style:
        session.style = style
    if language:
        session.language = language

    # Build prompt for LLM update
    system_prompt = PPT_UPDATE_SYSTEM.format(
        slide_count=len(session.slides),
        topic=session.topic,
        language="Chinese" if session.language == "zh" else "English"
    )

    # Prepare current slides as JSON
    current_slides = [slide.model_dump() for slide in session.slides]

    user_prompt = f"""当前用户请求：{instruction}

当前幻灯片内容：
{json.dumps(current_slides, ensure_ascii=False, indent=2)}

请根据用户请求修改幻灯片内容，返回完整的更新后的 JSON 数组。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # Call LLM
    response = await chat_completion(messages)

    # Parse JSON response using shared toolkit
    slides_data = extract_json_from_text(response)

    if slides_data and isinstance(slides_data, list):
        new_slides = _validate_and_create_slides(slides_data, min_count=3)
        session.slides = new_slides
    else:
        # If parsing fails, keep original slides but add a note
        session.chat_history.append(
            ChatMessage(role="user", content=instruction)
        )
        session.chat_history.append(
            ChatMessage(role="assistant", content="抱歉，未能解析更新内容，请重试或提供更明确的指令")
        )
        return session

    # Regenerate PPT file with updated content
    filepath = _create_pptx_file(session)
    session.ppt_file_path = str(filepath)

    # Update chat history
    session.chat_history.append(
        ChatMessage(role="user", content=instruction)
    )
    session.chat_history.append(
        ChatMessage(role="assistant", content=f"已更新幻灯片，现在包含 {len(session.slides)} 页")
    )

    # Store updated session
    _sessions[session_id] = session

    return session