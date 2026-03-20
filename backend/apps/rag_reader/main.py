"""
RAG Reader sub-app.
Upload documents → build vector store → AI Q&A.
"""
from __future__ import annotations

import io
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from backend.core.llm_service import chat_completion

router = APIRouter(prefix="/api/apps/rag_reader", tags=["rag_reader"])

# Lightweight in-memory doc store (per session)
_sessions: dict[str, dict] = {}


class QueryRequest(BaseModel):
    session_id: str
    question: str


# ---------- Helpers ----------

def _extract_text(filename: str, content: bytes) -> str:
    """Extract plain text from PDF / DOCX / TXT."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    elif ext == ".docx":
        from docx import Document
        doc = Document(io.BytesIO(content))
        return "\n".join(p.text for p in doc.paragraphs)
    elif ext in (".txt", ".md"):
        return content.decode("utf-8", errors="ignore")
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def _chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    """Simple sliding-window chunking."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


# ---------- Routes ----------

@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload a document and build a simple in-memory index."""
    if not file.filename:
        raise HTTPException(400, "No file provided")

    content = await file.read()
    try:
        text = _extract_text(file.filename, content)
    except ValueError as e:
        raise HTTPException(400, str(e))

    chunks = _chunk_text(text)
    session_id = uuid.uuid4().hex[:12]
    _sessions[session_id] = {
        "filename": file.filename,
        "full_text": text,
        "chunks": chunks,
    }
    return {
        "session_id": session_id,
        "filename": file.filename,
        "total_chars": len(text),
        "num_chunks": len(chunks),
        "preview": text[:500],
    }


@router.post("/query")
async def query(req: QueryRequest):
    """Ask a question about the uploaded document (RAG style)."""
    session = _sessions.get(req.session_id)
    if not session:
        raise HTTPException(404, "Session not found – upload a document first")

    # Simple keyword-based retrieval (production would use vector search)
    question_lower = req.question.lower()
    scored = []
    for i, chunk in enumerate(session["chunks"]):
        score = sum(1 for word in question_lower.split() if word in chunk.lower())
        scored.append((score, i, chunk))
    scored.sort(key=lambda x: -x[0])
    top_chunks = [c for _, _, c in scored[:5]]
    context = "\n---\n".join(top_chunks)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful document reading assistant. "
                "Answer the user's question based ONLY on the provided context. "
                "If the answer is not in the context, say so. "
                "Reply in the same language the user uses."
            ),
        },
        {
            "role": "user",
            "content": f"Context from document '{session['filename']}':\n```\n{context}\n```\n\nQuestion: {req.question}",
        },
    ]
    answer = await chat_completion(messages)
    return {"answer": answer, "sources": len(top_chunks)}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return {
        "session_id": session_id,
        "filename": session["filename"],
        "total_chars": len(session["full_text"]),
        "num_chunks": len(session["chunks"]),
    }


# Chat handler (called by platform router)
async def handle_chat(messages: list[dict], *, config: Optional[dict] = None) -> str:
    system_msg = {
        "role": "system",
        "content": "You are a document reading assistant powered by RAG. Help users understand their documents. Reply in the same language the user uses.",
    }
    return await chat_completion([system_msg] + messages)
