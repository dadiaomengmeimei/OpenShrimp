"""
Tang Poetry Generation Service (唐诗生成服务)
"""

import json
import re
from typing import Dict, Any

from backend.core.llm_service import chat_completion
from .models import PoetryRequest, PoetryResponse
from .prompts import TANG_POET_SYSTEM_PROMPT, build_poetry_prompt


async def generate_tang_poetry(
    theme: str = "春天",
    style: str = "五言绝句",
    mood: str = "淡雅"
) -> PoetryResponse:
    """
    Generate a Tang-style poem based on user specifications.
    
    Args:
        theme: 诗歌主题
        style: 诗歌体裁
        mood: 情感基调
    
    Returns:
        PoetryResponse with generated poem and annotations
    """
    # Build the user prompt
    user_prompt = build_poetry_prompt(theme, style, mood)
    
    # Prepare messages for LLM
    messages = [
        {"role": "system", "content": TANG_POET_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ]
    
    # Call LLM (limit max_tokens for poetry generation – no need for 20000)
    try:
        llm_response = await chat_completion(messages, max_tokens=2000)
    except Exception as e:
        # Fallback: create a simple response if LLM fails
        return _create_fallback_poetry(theme, style, mood)
    
    # Parse LLM response
    poem_data = _parse_poetry_response(llm_response)
    
    # Construct full content string
    content = _format_poem_content(
        poem_data.get("title", "无题"),
        poem_data.get("poem_lines", []),
        poem_data.get("annotation", "")
    )
    
    return PoetryResponse(
        title=poem_data.get("title", "无题"),
        content=content,
        poem_lines=poem_data.get("poem_lines", []),
        annotation=poem_data.get("annotation", ""),
        style=style,
        theme=theme
    )


def _parse_poetry_response(llm_response: str) -> Dict[str, Any]:
    """
    Parse LLM response to extract poem data.
    Handles both JSON and plain text formats.
    """
    # Try to extract JSON from the response
    try:
        # Look for JSON block
        json_match = re.search(r'\{[\s\S]*\}', llm_response)
        if json_match:
            json_str = json_match.group()
            data = json.loads(json_str)
            return {
                "title": data.get("title", "无题"),
                "poem_lines": data.get("poem_lines", []),
                "annotation": data.get("annotation", "")
            }
    except json.JSONDecodeError:
        pass
    
    # Fallback: parse text format
    lines = llm_response.strip().split('\n')
    title = "无题"
    poem_lines = []
    annotation = ""
    
    current_section = ""
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Try to identify title (often has "标题" or is first short line)
        if "标题" in line or "题目" in line:
            title = line.split("：", 1)[-1].strip() if "：" in line else line
            current_section = "title"
            continue
            
        # Collect poem lines (usually short, without punctuation markers)
        if len(line) <= 10 and not any(kw in line for kw in ["注释", "赏析", "说明"]):
            if current_section != "annotation" and not line.startswith(("{", "}")):
                poem_lines.append(line)
                current_section = "poem"
                continue
                
        # Annotation section
        if any(kw in line for kw in ["注释", "赏析", "说明", "注解"]):
            current_section = "annotation"
            annotation = line.split("：", 1)[-1].strip() if "：" in line else ""
            continue
            
        if current_section == "annotation":
            annotation += line
    
    # If we didn't get proper lines, use all short lines
    if len(poem_lines) < 2:
        poem_lines = [l for l in lines if 5 <= len(l) <= 10 and not any(k in l for k in ["标题", "注释", "赏析", "{", "}"])]
    
    return {
        "title": title or "无题",
        "poem_lines": poem_lines[:8],  # Max 8 lines for Tang poetry
        "annotation": annotation or "暂无注释"
    }


def _format_poem_content(title: str, poem_lines: list, annotation: str) -> str:
    """
    Format the poem into a nice string for display.
    """
    content_parts = [f"《{title}》", ""]
    
    # Add poem lines
    for line in poem_lines:
        content_parts.append(line)
    
    content_parts.append("")
    content_parts.append("【赏析】")
    content_parts.append(annotation)
    
    return "\n".join(content_parts)


def _create_fallback_poetry(theme: str, style: str, mood: str) -> PoetryResponse:
    """
    Create a fallback poem when LLM fails.
    """
    title = f"咏{theme}" if theme else "即兴"
    
    # Simple fallback lines based on style
    if "五言" in style:
        poem_lines = ["岁月如流水", "诗心寄远天", "风华今尚在", "雅韵永流传"]
        if "律诗" in style:
            poem_lines.extend(["云霞生异彩", "笔墨写新篇", "且尽杯中酒", "高歌醉酒仙"])
    else:  # 七言
        poem_lines = ["春风拂面柳丝长", "万里江山入画廊", "且把诗心寄明月", "清辉一片照故乡"]
        if "律诗" in style:
            poem_lines.extend(["岁月如歌人易老", "芳华似梦意难忘", "举杯邀月同君醉", "共话桑麻夜未央"])
    
    annotation = f"这是一首以{theme}为主题、{mood}为基调的{style}。诗人借景抒情，表达了对生活的感悟和对美好事物的追求。"
    
    content = _format_poem_content(title, poem_lines, annotation)
    
    return PoetryResponse(
        title=title,
        content=content,
        poem_lines=poem_lines,
        annotation=annotation,
        style=style,
        theme=theme
    )


def parse_user_intent(message: str) -> PoetryRequest:
    """
    Parse user's natural language message to extract poetry generation parameters.
    
    Args:
        message: User's input message
    
    Returns:
        PoetryRequest with extracted parameters
    """
    message = message.strip()
    
    # Default values
    theme = "春天"
    style = "五言绝句"
    mood = "淡雅"
    
    # Detect style
    if "七言律诗" in message or "七律" in message:
        style = "七言律诗"
    elif "五言律诗" in message or "五律" in message:
        style = "五言律诗"
    elif "七言绝句" in message or "七绝" in message:
        style = "七言绝句"
    elif "五言绝句" in message or "五绝" in message:
        style = "五言绝句"
    
    # Detect mood keywords
    mood_keywords = {
        "豪迈": ["豪迈", "豪放", "激昂", "壮志", "雄心"],
        "婉约": ["婉约", "柔美", "细腻", "缠绵"],
        "忧伤": ["忧伤", "悲伤", "愁", "凄凉", "孤寂"],
        "喜悦": ["喜悦", "欢快", "高兴", "欢乐", "欣喜"],
        "恬淡": ["恬淡", "宁静", "闲适", "悠然", "淡雅"],
        "思乡": ["思乡", "乡愁", "怀旧", "思念"]
    }
    
    for mood_key, keywords in mood_keywords.items():
        if any(kw in message for kw in keywords):
            mood = mood_key
            break
    
    # Extract theme - look for "关于..." or "以...为题" patterns
    theme_patterns = [
        r'[关于|以](.+?)[为题|为主题|写|作]',
        r'写(.+?)的',
        r'(.+?)的诗',
        r'主题是(.+?)[的，。]',
    ]
    
    for pattern in theme_patterns:
        match = re.search(pattern, message)
        if match:
            extracted_theme = match.group(1).strip()
            if extracted_theme and len(extracted_theme) <= 10:
                theme = extracted_theme
                break
    
    # Common theme keywords
    common_themes = ["春天", "夏天", "秋天", "冬天", "月亮", "太阳", "山水", "离别", "思乡", "友情", "爱情", "战争", "田园"]
    for t in common_themes:
        if t in message:
            theme = t
            break
    
    return PoetryRequest(theme=theme, style=style, mood=mood)