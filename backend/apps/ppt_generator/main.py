"""
FastAPI router for PPT Generator app.
Thin controller: only route definitions and request handling.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pathlib import Path
from typing import Optional, List, Dict, Any
import aiofiles

from .models import (
    PPTGenerationRequest,
    PPTUpdateRequest,
    PPTResponse,
    PPTSession,
    ChatMessage,
)
from .service import (
    generate_ppt_from_topic,
    update_ppt_session,
    _sessions,
    _register_and_get_download_link,
)
from . import config as app_config

router = APIRouter(prefix="/api/apps/ppt_generator", tags=["PPT Generator"])


def _session_to_response(session: PPTSession) -> PPTResponse:
    """Convert PPTSession to PPTResponse."""
    # Use unified file download URL via file_toolkit
    if session.ppt_file_path and Path(session.ppt_file_path).exists():
        download_url = _register_and_get_download_link(Path(session.ppt_file_path), session)
    else:
        download_url = f"/api/apps/ppt_generator/download/{session.session_id}"
    return PPTResponse(
        session_id=session.session_id,
        topic=session.topic,
        style=session.style,
        language=session.language,
        slide_count=len(session.slides),
        slides=[slide.model_dump() for slide in session.slides],
        download_url=download_url,
        chat_history=session.chat_history,
    )


@router.post("/generate")
async def generate_ppt(
    topic: Optional[str] = Form(None),
    document_text: Optional[str] = Form(None),
    style: str = Form("professional"),
    language: str = Form("zh"),
    slide_count: Optional[int] = Form(None),
    file: Optional[UploadFile] = File(None),
):
    """
    Generate a new PPT presentation from a topic or document.
    
    Supports:
    - Topic-based generation: Provide a topic to generate PPT content
    - Document-based generation: Upload a file or provide text content
    - Style options: professional, creative, minimal, academic
    - Language: zh (Chinese), en (English)
    """
    # Validate input
    if not topic and not document_text and not file:
        raise HTTPException(
            status_code=400,
            detail="Please provide a topic, document_text, or upload a file"
        )
    
    # Validate style
    if style not in app_config.SUPPORTED_STYLES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported style. Supported styles: {', '.join(app_config.SUPPORTED_STYLES)}"
        )
    
    # Validate language
    if language not in app_config.SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language. Supported languages: {', '.join(app_config.SUPPORTED_LANGUAGES)}"
        )
    
    # Handle file upload
    if file:
        try:
            content = await file.read()
            # Try to decode as text (supports txt, md, etc.)
            try:
                document_text = content.decode('utf-8')
            except UnicodeDecodeError:
                # Try other encodings
                try:
                    document_text = content.decode('gbk')
                except UnicodeDecodeError:
                    raise HTTPException(
                        status_code=400,
                        detail="Failed to parse uploaded file. Please upload a text file (txt, md, etc.)"
                    )
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"File read error: {str(e)}"
            )
    
    # Use document_text as topic if topic not provided
    if not topic and document_text:
        # Use first line or first 100 chars as topic
        topic = document_text.split('\n')[0][:100] or "Document Content"
    
    try:
        session = await generate_ppt_from_topic(
            topic=topic,
            style=style,
            language=language,
            slide_count=slide_count,
        )
        return _session_to_response(session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PPT generation failed: {str(e)}")


@router.post("/update")
async def update_ppt(request: PPTUpdateRequest):
    """
    Update an existing PPT session based on user instruction.
    
    Supports multi-turn conversation for:
    - Adding/removing slides
    - Modifying content
    - Changing style
    - Adjusting language
    """
    if request.session_id not in _sessions:
        raise HTTPException(
            status_code=404,
            detail=f"Session {request.session_id} not found"
        )
    
    # Validate style if provided
    if request.style and request.style not in app_config.SUPPORTED_STYLES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported style. Supported styles: {', '.join(app_config.SUPPORTED_STYLES)}"
        )
    
    # Validate language if provided
    if request.language and request.language not in app_config.SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language. Supported languages: {', '.join(app_config.SUPPORTED_LANGUAGES)}"
        )
    
    try:
        session = await update_ppt_session(
            session_id=request.session_id,
            instruction=request.instruction,
            style=request.style,
            language=request.language,
        )
        return _session_to_response(session)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PPT update failed: {str(e)}")


@router.get("/session/{session_id}")
async def get_session(session_id: str):
    """Get the current state of a PPT session."""
    if session_id not in _sessions:
        raise HTTPException(
            status_code=404,
            detail=f"Session {session_id} not found"
        )
    
    session = _sessions[session_id]
    return _session_to_response(session)


@router.get("/download/{session_id}")
async def download_ppt(session_id: str):
    """Download the generated PPT file."""
    if session_id not in _sessions:
        raise HTTPException(
            status_code=404,
            detail=f"Session {session_id} not found"
        )
    
    session = _sessions[session_id]
    
    if not session.ppt_file_path:
        raise HTTPException(
            status_code=404,
            detail="PPT file has not been generated yet"
        )
    
    # Convert to Path object for proper file operations
    filepath = Path(session.ppt_file_path)
    
    # Check if file exists
    if not filepath.exists():
        raise HTTPException(
            status_code=404,
            detail="PPT file not found"
        )
    
    # Use StreamingResponse with explicit file reading to ensure proper streaming
    async def file_iterator():
        async with aiofiles.open(filepath, mode='rb') as f:
            while chunk := await f.read(8192):
                yield chunk
    
    # Sanitize filename (replace problematic characters)
    safe_topic = session.topic[:50].replace('/', '_').replace('\\', '_').replace(':', '_')
    filename = f"{safe_topic}.pptx"
    
    return StreamingResponse(
        file_iterator(),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={
            "Content-Disposition": f'attachment; filename*=UTF-8\'\'{filename}'
        }
    )


@router.post("/chat")
async def chat(session_id: str, instruction: str):
    """
    Chat with the PPT assistant for multi-turn conversation.
    This is a convenience endpoint that combines update and response.
    """
    if session_id not in _sessions:
        raise HTTPException(
            status_code=404,
            detail=f"Session {session_id} not found"
        )
    
    try:
        session = await update_ppt_session(
            session_id=session_id,
            instruction=instruction,
        )
        download_link = _register_and_get_download_link(Path(session.ppt_file_path), session)
        return {
            "session_id": session.session_id,
            "content": f"PPT 已更新，现在包含 {len(session.slides)} 页。\n\n{download_link}",
            "slides": [slide.model_dump() for slide in session.slides],
            "download_url": download_link,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat processing failed: {str(e)}")


async def handle_chat(messages: List[Dict[str, str]], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Handle multi-turn conversational chat for the PPT Generator app.
    
    This function is the required entry point for the AI App Store platform
    to enable conversational interactions with the PPT Generator.
    
    Args:
        messages: List of chat messages with 'role' and 'content' keys.
                  The last message should be from the user.
        config: Optional configuration dictionary (e.g., session_id, style, language)
    
    Returns:
        Dictionary containing the response with session info, slides, and download_url.
        The download link is formatted as a markdown hyperlink for clickable download.
    
    Raises:
        HTTPException: If session not found or processing fails.
    """
    if not messages:
        raise HTTPException(status_code=400, detail="Message list cannot be empty")
    
    # Get the last user message
    user_message = None
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg.get("content", "")
            break
    
    if not user_message:
        raise HTTPException(status_code=400, detail="No user message found")
    
    # Extract session_id from config
    session_id = None
    if config and "session_id" in config:
        session_id = config["session_id"]
    
    # Check if we have an existing session
    if session_id and session_id in _sessions:
        # Update existing session
        try:
            session = await update_ppt_session(
                session_id=session_id,
                instruction=user_message,
                style=config.get("style") if config else None,
                language=config.get("language") if config else None,
            )
            download_link = _register_and_get_download_link(Path(session.ppt_file_path), session)
            # Return response with 'content' key for platform compatibility
            # Format download link as markdown hyperlink for clickable download
            return {
                "content": f"PPT 已更新 '{session.topic}'，现在包含 {len(session.slides)} 页。\n\n{download_link}",
                "session_id": session.session_id,
                "slides": [slide.model_dump() for slide in session.slides],
                "download_url": download_link,
            }
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"PPT update failed: {str(e)}")
    else:
        # Create new session
        try:
            # Extract style and language from config or use defaults
            style = config.get("style", "professional") if config else "professional"
            language = config.get("language", "zh") if config else "zh"
            
            session = await generate_ppt_from_topic(
                topic=user_message,
                style=style,
                language=language,
            )
            download_link = _register_and_get_download_link(Path(session.ppt_file_path), session)
            # Return response with 'content' key for platform compatibility
            # Format download link as markdown hyperlink for clickable download
            return {
                "content": f"已生成关于 '{session.topic}' 的 PPT，包含 {len(session.slides)} 页。\n\n{download_link}",
                "session_id": session.session_id,
                "slides": [slide.model_dump() for slide in session.slides],
                "download_url": download_link,
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"PPT generation failed: {str(e)}")