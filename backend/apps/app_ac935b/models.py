"""
Pydantic models for Tang Poetry Generator (唐诗生成器)
"""

from pydantic import BaseModel, Field
from typing import Literal, Optional


class PoetryRequest(BaseModel):
    """Request model for generating Tang poetry"""
    
    theme: str = Field(
        default="春天",
        description="诗歌主题，如：春天、月亮、山水、离别、思乡等"
    )
    style: Literal["五言绝句", "七言绝句", "五言律诗", "七言律诗"] = Field(
        default="五言绝句",
        description="诗歌体裁"
    )
    mood: str = Field(
        default="淡雅",
        description="诗歌情感基调，如：豪迈、婉约、忧伤、喜悦、恬淡等"
    )


class PoetryResponse(BaseModel):
    """Response model for generated Tang poetry"""
    
    title: str = Field(..., description="诗歌标题")
    content: str = Field(..., description="诗歌正文（用户展示用）")
    poem_lines: list[str] = Field(..., description="诗歌分行列表")
    annotation: str = Field(..., description="注释与赏析")
    style: str = Field(..., description="诗歌体裁")
    theme: str = Field(..., description="诗歌主题")


class ChatResponse(BaseModel):
    """Standard chat response wrapper"""
    
    content: str = Field(..., description="用户展示的回复内容")
    poem_data: Optional[PoetryResponse] = Field(default=None, description="诗歌结构化数据")