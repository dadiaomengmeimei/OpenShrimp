"""Pydantic models for PPT Generator app."""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum


class SlideType(str, Enum):
    """Types of slides."""
    TITLE = "title"
    CONTENT = "content"
    SECTION = "section"
    BULLETS = "bullets"
    TWO_COLUMN = "two_column"
    IMAGE_TEXT = "image_text"
    END = "end"


class SlideContent(BaseModel):
    """Content for a single slide."""
    type: SlideType = Field(..., description="Type of slide")
    title: str = Field(..., description="Slide title")
    content: Optional[str] = Field(None, description="Main content (text, bullet points, etc.)")
    subtitle: Optional[str] = Field(None, description="Subtitle for title slides")
    notes: Optional[str] = Field(None, description="Speaker notes")
    layout: Optional[str] = Field(None, description="Layout hint")


class PPTOutline(BaseModel):
    """Outline for a presentation."""
    title: str = Field(..., description="Presentation title")
    subtitle: Optional[str] = Field(None, description="Presentation subtitle")
    slides: List[SlideContent] = Field(..., description="List of slides")
    theme: str = Field("business", description="Theme name")
    total_slides: int = Field(..., description="Total number of slides")


class PPTSession(BaseModel):
    """Session state for PPT generation."""
    session_id: str
    outline: Optional[PPTOutline] = None
    file_path: Optional[str] = None
    theme: str = "business"
    created_at: float
    last_updated: float
    history: List[Dict[str, Any]] = []


class GenerationRequest(BaseModel):
    """Request to generate a PPT."""
    topic: str = Field(..., description="Topic or description for the presentation")
    theme: Optional[str] = Field("business", description="Theme to use")
    slide_count: Optional[int] = Field(8, ge=3, le=30, description="Number of slides")


class ModificationRequest(BaseModel):
    """Request to modify an existing PPT."""
    session_id: str
    instruction: str = Field(..., description="Modification instruction")


class StyleAdjustment(BaseModel):
    """Style adjustment request."""
    theme: Optional[str] = None
    font_size: Optional[int] = None
    color_scheme: Optional[str] = None
    add_images: Optional[bool] = None


class PPTResponse(BaseModel):
    """Response from PPT generation."""
    success: bool
    message: str
    session_id: Optional[str] = None
    download_url: Optional[str] = None
    file_name: Optional[str] = None
    outline: Optional[Dict] = None