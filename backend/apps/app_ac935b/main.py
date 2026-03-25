"""
Tang Poetry Generator App (唐诗生成器)

A FastAPI sub-app that generates Tang-style Chinese poetry based on user preferences.
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Literal, Optional, List, Dict

from .models import PoetryRequest, ChatResponse
from .service import generate_tang_poetry, parse_user_intent

router = APIRouter(prefix="/api/apps/app_ac935b", tags=["唐诗生成器"])


class GeneratePoetryRequest(BaseModel):
    """API request model for direct poetry generation"""
    theme: str = Field(default="春天", description="诗歌主题")
    style: Literal["五言绝句", "七言绝句", "五言律诗", "七言律诗"] = Field(default="五言绝句", description="诗歌体裁")
    mood: str = Field(default="淡雅", description="情感基调")


@router.post("/generate")
async def generate_poetry_endpoint(request: GeneratePoetryRequest):
    """
    Direct API endpoint for generating Tang poetry.
    
    Args:
        request: Poetry generation parameters
    
    Returns:
        Generated poem with title, content, and annotation
    """
    result = await generate_tang_poetry(
        theme=request.theme,
        style=request.style,
        mood=request.mood
    )
    return {
        "success": True,
        "data": result.model_dump()
    }


@router.get("/info")
async def get_app_info():
    """Get app information"""
    return {
        "id": "app_ac935b",
        "name": "唐诗生成器",
        "description": "一个智能写唐诗的机器人，可以根据主题、体裁和情感基调创作格律严谨的唐诗",
        "version": "1.0.0",
        "author": "AppShrimp",
        "supported_styles": ["五言绝句", "七言绝句", "五言律诗", "七言律诗"]
    }


# Required handle_chat function for the platform
async def handle_chat(
    messages: List[Dict],
    *,
    config: Optional[Dict] = None
) -> Dict:
    """
    Handle chat messages from the platform.
    
    This is the main entry point for the chat interface.
    Extracts user intent and generates Tang poetry accordingly.
    
    Args:
        messages: List of chat messages (user and assistant history)
        config: Optional configuration dictionary
    
    Returns:
        Dict with 'content' key containing the user-facing reply
    """
    # Get the latest user message
    user_message = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg.get("content", "")
            break
    
    if not user_message:
        return {
            "content": "您好！我是唐诗生成器，可以为您创作各种风格的唐诗。\n\n请告诉我您想要的：\n• 主题（如：春天、月亮、山水、离别等）\n• 体裁（如：五言绝句、七言绝句、五言律诗、七言律诗）\n• 情感基调（如：豪迈、婉约、忧伤、喜悦、恬淡等）\n\n例如：\"请写一首关于月亮的七言绝句，情感要忧伤一些\""
        }
    
    # Check if user wants help/info
    help_keywords = ["帮助", "help", "怎么用", "说明", "介绍", "功能"]
    if any(kw in user_message for kw in help_keywords):
        return {
            "content": "📜 **唐诗生成器使用说明**\n\n我可以为您创作格律严谨的唐诗！\n\n**支持的体裁：**\n• 五言绝句（4句，每句5字）\n• 七言绝句（4句，每句7字）\n• 五言律诗（8句，每句5字）\n• 七言律诗（8句，每句7字）\n\n**示例请求：**\n• \"写一首关于春天的五言绝句\"\n• \"以离别为主题，创作一首七言律诗，情感要忧伤\"\n• \"来一首豪迈的山水诗\"\n\n直接告诉我您的想法即可！"
        }
    
    # Parse user intent
    poetry_request = parse_user_intent(user_message)
    
    # Generate poetry
    try:
        result = await generate_tang_poetry(
            theme=poetry_request.theme,
            style=poetry_request.style,
            mood=poetry_request.mood
        )
        
        return {
            "content": result.content,
            "poem_data": result.model_dump()
        }
        
    except Exception as e:
        return {
            "content": f"抱歉，生成诗歌时出现了一些问题。请再试一次，或直接告诉我：\n• 主题（如：春天、月亮、山水）\n• 体裁（五言/七言 + 绝句/律诗）\n• 情感（豪迈、婉约、忧伤等）\n\n错误信息：{str(e)}"
        }