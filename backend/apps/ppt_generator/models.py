"""
Pydantic models for PPT Generator app.
"""
from __future__ import annotations

from typing import Optional, List
from pydantic import BaseModel


class Slide(BaseModel):
    """Represents a single slide in the presentation."""
    title: str
    content: List[str]  # Bullet points
    notes: Optional[str] = None  # Speaker notes


class PPTGenerationRequest(BaseModel):
    """Request to generate a new PPT from topic or document."""
    topic: Optional[str] = None  # Topic to generate PPT about
    document_text: Optional[str] = None  # Document content to extract PPT from
    style: str = "professional"  # Style: professional, creative, minimal, academic
    language: str = "zh"  # Language: zh (Chinese), en (English)
    slide_count: Optional[int] = None  # Desired number of slides (optional)


class PPTUpdateRequest(BaseModel):
    """Request to update an existing PPT based on conversation."""
    session_id: str
    instruction: str  # User's instruction for modification
    style: Optional[str] = None  # Optional style change
    language: Optional[str] = None  # Optional language change


class ChatMessage(BaseModel):
    """Chat message for multi-turn conversation."""
    role: str  # "user" or "assistant"
    content: str


class PPTSession(BaseModel):
    """Represents a PPT generation session."""
    session_id: str
    topic: str
    style: str
    language: str
    slides: List[Slide]
    chat_history: List[ChatMessage]
    ppt_file_path: Optional[str] = None


class PPTResponse(BaseModel):
    """Response containing PPT info and download link."""
    session_id: str
    topic: str
    style: str
    language: str
    slide_count: int
    slides: List[dict]
    download_url: str
    chat_history: List[ChatMessage]