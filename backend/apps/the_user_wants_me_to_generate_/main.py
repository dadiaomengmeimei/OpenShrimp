"""Main entry point for PPT Generator app."""

import os
import shutil
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse

from backend.core.file_toolkit import make_download_link
from .models import PPTResponse
from .service import (
    create_session,
    get_session,
    update_session,
    generate_outline,
    generate_outline_from_content,
    modify_outline,
    create_ppt_file,
    get_theme_list,
    format_outline_for_display,
)
from .file_parser import extract_files_from_messages, parse_file, combine_parsed_files
from .config import PPT_STORAGE_DIR, AVAILABLE_THEMES, BASE_URL

router = APIRouter(prefix="/api/apps/the_user_wants_me_to_generate_", tags=["PPT生成器"])

# Directory for temporary uploaded files
UPLOAD_DIR = os.path.join(PPT_STORAGE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _is_missing_dependency_error(error: Exception) -> bool:
    """Check if error is due to missing python-pptx dependency."""
    error_str = str(error).lower()
    return (
        isinstance(error, ImportError)
        and ("python-pptx" in error_str or "pptx" in error_str)
    )


def _format_dependency_error() -> dict:
    """Return formatted error message for missing dependency."""
    return {
        "content": "⚠️ **需要安装Python包**：`python-pptx`\n\n"
                   "请运行以下命令安装依赖：\n"
                   "```bash\n"
                   "pip install python-pptx\n"
                   "```\n\n"
                   "安装完成后即可正常生成PPT。",
        "success": False,
    }


def _build_download_url(file_path: str, display_name: str = "presentation.pptx") -> str:
    """
    Register a file for download via file_toolkit and return a relative URL.
    
    Uses the shared file_toolkit make_download_link() to produce a Markdown link
    matching `/api/files/download/{token}` that the frontend renders as a download button.
    
    Args:
        file_path: Absolute path to the generated PPT file.
        display_name: Filename shown to the user when downloading.
        
    Returns:
        Relative download URL like `/api/files/download/{token}`.
    """
    link = make_download_link(file_path, label="点击下载 PPT", filename=display_name)
    # Extract just the URL from the markdown link for backward compatibility
    # link format: "[📥 点击下载 PPT](/api/files/download/{token})"
    import re
    url_match = re.search(r'\((.*?)\)', link)
    return url_match.group(1) if url_match else link


@router.get("/themes")
async def list_themes():
    """Get list of available themes."""
    return {
        "success": True,
        "themes": get_theme_list()
    }


@router.get("/download/{session_id}")
async def download_ppt(session_id: str):
    """Download generated PPT file."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    if not session.file_path or not os.path.exists(session.file_path):
        raise HTTPException(status_code=404, detail="PPT file not found")
    
    filename = os.path.basename(session.file_path)
    
    return FileResponse(
        path=session.file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )


@router.get("/session/{session_id}")
async def get_session_info(session_id: str):
    """Get session information and outline."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    return {
        "success": True,
        "session_id": session_id,
        "theme": session.theme,
        "outline": session.outline.dict() if session.outline else None,
        "has_file": session.file_path is not None and os.path.exists(session.file_path),
        "created_at": session.created_at,
    }


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    topic: str = Query(default="", description="Optional topic or instructions for the PPT"),
    theme: str = Query(default="professional", description="PPT theme style"),
):
    """
    Upload a file and auto-generate PPT from its content.
    
    Supports file types: TXT, Markdown, PDF, Word, Excel, PowerPoint.
    
    Args:
        file: The uploaded file
        topic: Optional topic/title instruction
        theme: Theme style for the PPT
        
    Returns:
        Generated PPT outline and download link
    """
    print(f"[PPT Generator] File upload received: {file.filename}")
    
    # Validate file extension
    allowed_extensions = {'.txt', '.md', '.csv', '.docx', '.pdf', '.xlsx', '.xls', '.pptx'}
    file_ext = os.path.splitext(file.filename)[1].lower() if file.filename else ''
    
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file_ext}. 支持的类型: {', '.join(allowed_extensions)}"
        )
    
    # Save uploaded file temporarily
    temp_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}{file_ext}")
    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        print(f"[PPT Generator] Saved uploaded file to: {temp_path}")
        
        # Parse the file content
        parsed = parse_file(temp_path)
        print(f"[PPT Generator] Parsed file: {parsed.filename} | type={parsed.file_type} | length={len(parsed.content)}")
        
        # Create session and generate PPT
        session = create_session()
        
        outline = await generate_outline_from_content(
            parsed.content, 
            theme=theme, 
            user_request=topic or parsed.filename
        )
        session.outline = outline
        
        # Create PPT file
        ppt_path = create_ppt_file(outline, session.session_id)
        session.file_path = ppt_path
        
        update_session(session)
        
        # Build response
        outline_display = format_outline_for_display(outline)
        download_url = _build_download_url(ppt_path, f"{outline.title[:20]}.pptx")
        
        return {
            "success": True,
            "message": "PPT已根据上传文件内容生成",
            "session_id": session.session_id,
            "file_processed": {
                "name": parsed.filename,
                "type": parsed.file_type,
                "size": parsed.metadata.get('char_count', 0),
            },
            "outline": outline.dict(),
            "outline_display": outline_display,
            "download_url": download_url,
            "download_link": f"[📥 下载PPT]({download_url})",
        }
        
    except Exception as e:
        print(f"[PPT Generator] Upload error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"处理文件时出错: {str(e)}")
    finally:
        # Cleanup temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)


async def handle_chat(
    messages: list[dict],
    *,
    config: Optional[dict] = None
) -> dict:
    """
    Main chat handler for PPT generation.
    
    Supports multi-turn dialogue:
    - First message: Generate PPT from topic
    - With file upload: Parse file content and generate adaptive PPT
    - Follow-up messages: Modify PPT style/content
    
    Args:
        messages: List of conversation messages (may include file attachments)
        config: Optional configuration with session_id
        
    Returns:
        Dict with content and metadata
    """
    print(f"[PPT Generator] handle_chat called | messages_count={len(messages)}")
    
    # Get user input
    user_msg = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_msg = msg.get("content", "")
            break
    
    # ── File Upload Support ───────────────────────────────────────────────────
    # Extract files from message attachments and parse their content
    try:
        files_info = extract_files_from_messages(messages)
        if files_info:
            print(f"[PPT Generator] Detected {len(files_info)} uploaded file(s)")
            parsed_contents = []
            for f in files_info:
                file_path = f.get("path") or f.get("file_path", "")
                if file_path:
                    parsed = parse_file(file_path)
                    parsed_contents.append(parsed)
                    print(f"[PPT Generator] Parsed: {parsed.filename} | type={parsed.file_type} | length={len(parsed.content)}")
            
            if parsed_contents:
                combined_content = combine_parsed_files(parsed_contents)
                print(f"[PPT Generator] Combined content length: {len(combined_content)}")
                
                # Auto-generate PPT from file content
                session = create_session()
                theme = config.get("theme", "professional") if config else "professional"
                
                outline = await generate_outline_from_content(combined_content, theme, user_request=user_msg)
                session.outline = outline
                
                ppt_file_path = create_ppt_file(outline, session.session_id)
                session.file_path = ppt_file_path
                
                update_session(session)
                
                outline_display = format_outline_for_display(outline)
                download_url = _build_download_url(ppt_file_path, f"{outline.title[:20]}.pptx")
                
                file_summary = "\n\n📄 **已处理文件：**\n" + "\n".join([
                    f"• {p.filename} ({p.file_type.upper()})" for p in parsed_contents
                ])
                
                return {
                    "content": f"✅ **已根据上传的文件内容自动生成PPT！**{file_summary}\n\n🎯 **生成的大纲：**\n{outline_display}\n\n[📥 点击下载 PPT]({download_url})\n\n您可以继续调整内容或样式，例如：'把第二页改成双栏布局' 或 '增加一页关于xxx的内容'",
                    "success": True,
                    "session_id": session.session_id,
                    "download_url": download_url,
                    "type": "ppt_generated_from_file"
                }
    except Exception as e:
        print(f"[PPT Generator] File processing error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        # Continue with normal processing if file handling fails
    
    # If no user message after file processing, prompt for input
    if not user_msg:
        return {
            "content": "请告诉我您想要生成什么主题的PPT，或者直接上传文件！\n\n支持的格式：TXT、Markdown、PDF、Word、Excel、PPT",
            "success": False,
        }
    
    # Check for session in config
    session_id = config.get("session_id") if config else None
    session = None
    
    if session_id:
        session = get_session(session_id)
    
    # Detect intent
    user_msg_lower = user_msg.lower()
    
    # Help command
    if any(word in user_msg_lower for word in ["帮助", "help", "怎么用", "主题"]):
        themes_info = "\n".join([
            f"• **{t['name']}** ({key}): {t['description']}"
            for key, t in [(k, AVAILABLE_THEMES[k]) for k in AVAILABLE_THEMES]
        ])
        
        help_text = f'''🎨 **PPT生成器使用指南**

我可以帮您一键生成专业PPT！

**使用方法：**
1. 直接告诉我PPT主题，如："生成一个关于人工智能的PPT"
2. 选择主题风格（可选）
3. 生成后可要求调整内容和样式

**可用主题：**
{themes_info}

**多轮对话示例：**
- "帮我生成一个关于新能源的PPT"
- "把主题换成创意橙风格"
- "增加一页关于市场前景的内容"
- "把第三页的标题改得更吸引人"

请告诉我您想要什么主题的PPT？'''
        
        return {
            "content": help_text,
            "success": True,
        }
    
    # Check if this is a modification request
    modification_keywords = [
        "修改", "调整", "更换", "改变", "换成", "添加", "删除", "增加",
        "改", "变", "换", "加", "删", "样式", "风格", "主题", "颜色",
        "more", "change", "modify", "add", "delete", "remove", "style",
        "theme", "adjust", "update",
    ]
    
    is_modification = any(kw in user_msg_lower for kw in modification_keywords)
    
    # If we have a session and user wants modification
    if session and is_modification and session.outline:
        try:
            # Apply modification
            new_outline = await modify_outline(session, user_msg)
            session.outline = new_outline
            
            # Regenerate file
            file_path = create_ppt_file(new_outline, session.session_id)
            session.file_path = file_path
            
            update_session(session)
            
            outline_display = format_outline_for_display(new_outline)
            safe_topic = session.outline.title[:50].replace("/", "_").replace("\\", "_")
            download_url = _build_download_url(file_path, f"{safe_topic}.pptx")
            
            print(f"[PPT Generator] Modification complete. Download URL: {download_url}")
            
            return {
                "content": f"✅ **已根据您的要求调整PPT！**\n\n{outline_display}\n\n[📥 点击下载 PPT]({download_url})\n\n您还可以继续调整，或告诉我其他需求。",
                "success": True,
                "session_id": session.session_id,
                "download_url": download_url,
                "outline": new_outline.dict(),
            }
            
        except Exception as e:
            # Check for missing dependency error
            if _is_missing_dependency_error(e):
                return _format_dependency_error()
            
            error_msg = f'❌ 修改PPT时出错：{str(e)}\n\n请重新描述您的修改需求，或输入"帮助"查看使用说明。'
            return {
                "content": error_msg,
                "success": False,
                "session_id": session.session_id,
            }
    
    # New PPT generation
    try:
        # Extract theme preference
        theme = "business"  # default
        for theme_key in AVAILABLE_THEMES.keys():
            if theme_key in user_msg_lower or AVAILABLE_THEMES[theme_key]["name"] in user_msg:
                theme = theme_key
                break
        
        # Extract slide count if mentioned
        slide_count = 8
        import re
        count_match = re.search(r'(\d+)\s*[页张]', user_msg)
        if count_match:
            slide_count = min(max(int(count_match.group(1)), 3), 30)
        
        # Create or reuse session
        if not session:
            session = create_session()
        
        session.theme = theme
        
        # Generate outline
        outline = await generate_outline(user_msg, theme, slide_count)
        session.outline = outline
        
        # Create PPT file
        file_path = create_ppt_file(outline, session.session_id)
        session.file_path = file_path
        
        # Add to history
        session.history.append({
            "action": "generate",
            "topic": user_msg,
            "timestamp": session.last_updated,
        })
        
        update_session(session)
        
        # Format response
        outline_display = format_outline_for_display(outline)
        safe_topic = outline.title[:50].replace("/", "_").replace("\\", "_")
        download_url = _build_download_url(file_path, f"{safe_topic}.pptx")
        
        print(f"[PPT Generator] Generation complete. Download URL: {download_url}")
        
        success_msg = f'''🎉 **PPT生成成功！**

{outline_display}

[📥 点击下载 PPT]({download_url})

💡 **提示**: 您可以继续对话来调整PPT，比如：
- "把主题换成创意风格"
- "添加一页关于...的内容"
- "删除第3页"
- "修改标题更简洁一些"

需要调整什么吗？'''
        
        return {
            "content": success_msg,
            "success": True,
            "session_id": session.session_id,
            "download_url": download_url,
            "outline": outline.dict(),
        }
        
    except Exception as e:
        # Check for missing dependency error
        if _is_missing_dependency_error(e):
            return _format_dependency_error()
        
        error_msg = f'❌ 生成PPT时出错：{str(e)}\n\n请重试或换一种描述方式。输入"帮助"查看使用说明。'
        return {
            "content": error_msg,
            "success": False,
        }


# For testing the router directly
if __name__ == "__main__":
    import asyncio
    
    async def test():
        result = await handle_chat(
            [{"role": "user", "content": "生成一个关于人工智能的PPT"}]
        )
        print(result["content"])
    
    asyncio.run(test())