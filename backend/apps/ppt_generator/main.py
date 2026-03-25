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

from backend.core.file_toolkit import (
    parse_pdf,
    parse_docx,
    parse_excel,
)

from .models import (
    PPTGenerationRequest,
    PPTUpdateRequest,
    PPTResponse,
    PPTSession,
    ChatMessage,
)
from .service import (
    generate_ppt_from_topic,
    generate_ppt_from_document,
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


def _parse_uploaded_file(file_path: str, file_name: str) -> str:
    """
    Parse uploaded file content based on file extension.
    Supports PDF, DOCX, TXT, MD, CSV, XLSX files.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()
    
    print(f"[_parse_uploaded_file] Parsing file: {file_name} (type: {suffix})")
    
    try:
        if suffix == '.pdf':
            return parse_pdf(file_path)
        elif suffix in ['.docx', '.doc']:
            return parse_docx(file_path)
        elif suffix in ['.xlsx', '.xls', '.csv']:
            # For Excel/CSV, convert to a readable text format
            result = parse_excel(file_path)
            # Convert to text representation
            lines = []
            lines.append(f"表格数据: {file_name}")
            lines.append(f"列名: {', '.join(result['headers'])}")
            lines.append(f"数据行数: {result['row_count']}")
            lines.append("")
            lines.append("数据预览 (前10行):")
            for i, row in enumerate(result['rows'][:10], 1):
                row_text = ' | '.join(str(v) for v in row.values())
                lines.append(f"{i}. {row_text}")
            return '\n'.join(lines)
        elif suffix in ['.txt', '.md', '.json', '.py', '.js', '.html', '.css']:
            # Text files - read directly
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        else:
            # Try to read as text for unknown extensions
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
    except Exception as e:
        print(f"[_parse_uploaded_file] Error parsing file: {e}")
        raise ValueError(f"无法解析文件 {file_name}: {str(e)}")


async def handle_chat(messages: List[Dict[str, str]], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Handle multi-turn conversational chat for the PPT Generator app.
    
    This function is the required entry point for the AI App Store platform
    to enable conversational interactions with the PPT Generator.
    
    Supports:
    - Topic-based PPT generation: "生成一个关于AI的PPT"
    - Document-based PPT generation: Upload a file and say "根据这个文件生成PPT"
    - Multi-turn editing: "添加一页关于...的内容"
    
    Args:
        messages: List of chat messages with 'role' and 'content' keys.
                  The last message should be from the user.
                  May also contain 'files' key with uploaded file metadata.
        config: Optional configuration dictionary (e.g., session_id, style, language)
    
    Returns:
        Dictionary containing the response with session info, slides, and download_url.
        The download link is formatted as a markdown hyperlink for clickable download.
    """
    print(f"[ppt_generator] handle_chat called | messages_count={len(messages) if messages else 0}")
    
    if not messages:
        raise HTTPException(status_code=400, detail="Message list cannot be empty")
    
    # Get the last user message
    user_message = None
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg
            break
    
    if not user_message:
        raise HTTPException(status_code=400, detail="No user message found")
    
    user_text = user_message.get("content", "")
    uploaded_files = user_message.get("files", [])
    
    print(f"[ppt_generator] User message: {user_text[:100]}... | files: {len(uploaded_files)}")
    
    # Extract session_id from config
    session_id = None
    if config and "session_id" in config:
        session_id = config["session_id"]
        print(f"[ppt_generator] Using existing session: {session_id}")
    
    # Extract style and language from config or use defaults
    style = config.get("style", "professional") if config else "professional"
    language = config.get("language", "zh") if config else "zh"
    
    # Validate style
    if style not in app_config.SUPPORTED_STYLES:
        style = app_config.DEFAULT_STYLE
    
    # Validate language
    if language not in app_config.SUPPORTED_LANGUAGES:
        language = app_config.DEFAULT_LANGUAGE
    
    # Check if user wants to update existing session
    if session_id and session_id in _sessions:
        print(f"[ppt_generator] Updating existing session: {session_id}")
        try:
            session = await update_ppt_session(
                session_id=session_id,
                instruction=user_text,
            )
            download_link = _register_and_get_download_link(Path(session.ppt_file_path), session)
            return {
                "content": f"PPT 已更新！现在共有 {len(session.slides)} 页幻灯片。\n\n{download_link}",
                "session_id": session.session_id,
                "slides": [slide.model_dump() for slide in session.slides],
                "download_url": download_link,
            }
        except Exception as e:
            print(f"[ppt_generator] Error updating session: {e}")
            raise HTTPException(status_code=500, detail=f"更新 PPT 失败: {str(e)}")
    
    # Handle file upload - generate PPT from document
    if uploaded_files:
        print(f"[ppt_generator] Processing {len(uploaded_files)} uploaded files")
        
        # Parse all uploaded files
        all_document_text = []
        for file_info in uploaded_files:
            file_path = file_info.get("path", "")
            file_name = file_info.get("name", "unknown")
            
            if not file_path or not Path(file_path).exists():
                print(f"[ppt_generator] File not found: {file_path}")
                continue
            
            try:
                content = _parse_uploaded_file(file_path, file_name)
                all_document_text.append(f"=== 文件: {file_name} ===\n{content}\n")
                print(f"[ppt_generator] Parsed file: {file_name} ({len(content)} chars)")
            except Exception as e:
                print(f"[ppt_generator] Failed to parse {file_name}: {e}")
                return {
                    "content": f"抱歉，无法解析文件 '{file_name}'。支持的文件格式：PDF、Word (DOCX)、Excel (XLSX/CSV)、文本文件 (TXT/MD)。\n\n错误信息: {str(e)}"
                }
        
        if not all_document_text:
            return {
                "content": "未能成功解析任何上传的文件。请确保文件格式正确且未损坏。"
            }
        
        # Combine all document content
        combined_document = "\n".join(all_document_text)
        print(f"[ppt_generator] Combined document length: {len(combined_document)} chars")
        
        # Determine topic from user text or file name
        topic = user_text.strip() if user_text.strip() else None
        
        try:
            # Generate PPT from document
            session = await generate_ppt_from_document(
                document_content=combined_document,
                topic=topic,
                style=style,
                language=language,
            )
            download_link = _register_and_get_download_link(Path(session.ppt_file_path), session)
            
            file_names = [f.get("name", "unknown") for f in uploaded_files]
            return {
                "content": f"✅ 已成功根据上传的文件生成 PPT！\n\n"
                          f"📄 文件: {', '.join(file_names)}\n"
                          f"📊 幻灯片数量: {len(session.slides)} 页\n"
                          f"🎨 风格: {style}\n\n"
                          f"{download_link}\n\n"
                          f"您可以继续发送指令来修改 PPT，例如：\n"
                          f"• '添加一页关于...的内容'\n"
                          f"• '删除第3页'\n"
                          f"• '将风格改为creative'",
                "session_id": session.session_id,
                "slides": [slide.model_dump() for slide in session.slides],
                "download_url": download_link,
            }
        except Exception as e:
            print(f"[ppt_generator] Error generating PPT from document: {e}")
            raise HTTPException(status_code=500, detail=f"根据文件生成 PPT 失败: {str(e)}")
    
    # Topic-based generation (no files, just text)
    print(f"[ppt_generator] Generating PPT from topic: {user_text[:50]}...")
    
    if not user_text.strip():
        return {
            "content": "请告诉我您想生成什么主题的 PPT，或者上传一个文件让我为您生成演示文稿。\n\n"
                      "例如：\n"
                      "• '生成一个关于人工智能的PPT'\n"
                      "• '帮我做一个产品介绍的演示文稿'\n"
                      "• 直接上传 PDF、Word 或 Excel 文件"
        }
    
    try:
        session = await generate_ppt_from_topic(
            topic=user_text,
            style=style,
            language=language,
        )
        download_link = _register_and_get_download_link(Path(session.ppt_file_path), session)
        
        return {
            "content": f"✅ PPT 生成成功！\n\n"
                      f"📋 主题: {session.topic}\n"
                      f"📊 幻灯片数量: {len(session.slides)} 页\n"
                      f"🎨 风格: {style}\n\n"
                      f"{download_link}\n\n"
                      f"您可以继续发送指令来修改 PPT，例如：\n"
                      f"• '添加一页关于...的内容'\n"
                      f"• '删除第3页'\n"
                      f"• '将风格改为creative'",
            "session_id": session.session_id,
            "slides": [slide.model_dump() for slide in session.slides],
            "download_url": download_link,
        }
    except Exception as e:
        print(f"[ppt_generator] Error generating PPT: {e}")
        raise HTTPException(status_code=500, detail=f"生成 PPT 失败: {str(e)}")