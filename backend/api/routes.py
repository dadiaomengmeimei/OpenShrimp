"""API routes for the platform (app CRUD, config, market, etc.)."""
from __future__ import annotations

import traceback

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from backend.core import app_registry
from backend.core.auth import get_current_user, get_optional_user, require_admin

router = APIRouter(prefix="/api", tags=["platform"])


# ---------- Schemas ----------

class AppCreateRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    icon: str = "🤖"
    category: str = "general"
    author: str = ""
    config: Optional[dict] = None


class AppConfigUpdate(BaseModel):
    config: dict


class ChatMessage(BaseModel):
    role: str
    content: str


class AppChatRequest(BaseModel):
    messages: list[ChatMessage]
    config: Optional[dict] = None


# ---------- App Routes (require auth) ----------

@router.get("/apps")
async def list_apps(user: dict = Depends(get_current_user)):
    """List apps visible to the current user (own + added + built-in)."""
    return await app_registry.list_apps(user_id=user["id"])


@router.get("/apps/{app_id}")
async def get_app(app_id: str, user: dict = Depends(get_current_user)):
    """Get a single app's metadata."""
    app = await app_registry.get_app(app_id)
    if not app:
        raise HTTPException(404, "App not found")
    return app


@router.post("/apps")
async def create_app(req: AppCreateRequest, user: dict = Depends(get_current_user)):
    """Register / import a new app (owned by current user)."""
    return await app_registry.register_app(
        req.id,
        name=req.name,
        description=req.description,
        icon=req.icon,
        category=req.category,
        author=req.author or user.get("display_name", user["username"]),
        author_id=user["id"],
        config=req.config,
    )


@router.delete("/apps/{app_id}")
async def delete_app(app_id: str, user: dict = Depends(get_current_user)):
    """Delete an app. Only the owner or admin can delete."""
    app = await app_registry.get_app(app_id)
    if not app:
        raise HTTPException(404, "App not found")
    # Check ownership: owner or admin
    if app.get("author_id") and app["author_id"] != user["id"] and not user.get("is_admin"):
        raise HTTPException(403, "You can only delete your own apps")
    ok = await app_registry.delete_app(app_id)
    if not ok:
        raise HTTPException(404, "App not found")
    return {"ok": True}


@router.put("/apps/{app_id}/config")
async def update_config(app_id: str, req: AppConfigUpdate, user: dict = Depends(get_current_user)):
    result = await app_registry.update_app_config(app_id, req.config)
    if not result:
        raise HTTPException(404, "App not found")
    return result


# ---------- Market Routes ----------

@router.get("/market")
async def list_market(user: Optional[dict] = Depends(get_optional_user)):
    """List all public apps in the market. Annotates which ones user has added."""
    user_id = user["id"] if user else None
    return await app_registry.list_market_apps(user_id=user_id)


@router.post("/market/{app_id}/add")
async def add_from_market(app_id: str, user: dict = Depends(get_current_user)):
    """Add a public app from the market to the user's app list."""
    ok = await app_registry.add_market_app(user["id"], app_id)
    if not ok:
        raise HTTPException(404, "App not found or not public")
    return {"ok": True, "app_id": app_id}


@router.delete("/market/{app_id}/remove")
async def remove_from_market(app_id: str, user: dict = Depends(get_current_user)):
    """Remove a market app from the user's app list (doesn't delete the app)."""
    ok = await app_registry.remove_market_app(user["id"], app_id)
    if not ok:
        raise HTTPException(404, "App not in your list")
    return {"ok": True, "app_id": app_id}


@router.post("/apps/{app_id}/publish")
async def publish_app(app_id: str, user: dict = Depends(get_current_user)):
    """Publish an app to the market. Only owner or admin."""
    app = await app_registry.get_app(app_id)
    if not app:
        raise HTTPException(404, "App not found")
    if app.get("author_id") and app["author_id"] != user["id"] and not user.get("is_admin"):
        raise HTTPException(403, "You can only publish your own apps")
    result = await app_registry.publish_app(app_id, user["id"])
    if not result:
        raise HTTPException(404, "App not found")
    return result


@router.post("/apps/{app_id}/unpublish")
async def unpublish_app(app_id: str, user: dict = Depends(get_current_user)):
    """Remove an app from the market. Only owner or admin."""
    app = await app_registry.get_app(app_id)
    if not app:
        raise HTTPException(404, "App not found")
    if app.get("author_id") and app["author_id"] != user["id"] and not user.get("is_admin"):
        raise HTTPException(403, "You can only unpublish your own apps")
    result = await app_registry.unpublish_app(app_id)
    if not result:
        raise HTTPException(404, "App not found")
    return result


# ---------- Chat Route ----------

@router.post("/apps/{app_id}/chat")
async def app_chat(app_id: str, req: AppChatRequest, user: dict = Depends(get_current_user)):
    """Forward a chat request to the sub-app's handler."""
    print(f"[api] POST /apps/{app_id}/chat | user={user.get('username')} | msgs={len(req.messages)}")
    mod = app_registry.load_app_module(app_id)
    if not mod:
        raise HTTPException(
            500,
            detail={
                "message": f"App '{app_id}' module could not be loaded (import error or missing)",
                "error_type": "ModuleNotFoundError",
                "traceback": "",
                "app_id": app_id,
                "auto_fixable": True,
            },
        )
    if not hasattr(mod, "handle_chat"):
        raise HTTPException(
            500,
            detail={
                "message": f"App '{app_id}' does not have a handle_chat function. The app needs a handle_chat(messages, config) async function.",
                "error_type": "MissingFunction",
                "traceback": "",
                "app_id": app_id,
                "auto_fixable": True,
            },
        )
    messages = [m.model_dump() for m in req.messages]
    try:
        result = await mod.handle_chat(messages, config=req.config)
        if isinstance(result, dict):
            reply = (
                result.get("content")
                or result.get("reply")
                or result.get("text")
                or result.get("response")
                or str(result)
            )
            # Return the raw structured data alongside the reply text
            # so that behavior-fix can access original details (e.g. slides)
            return {"reply": reply, "raw": result}
        elif isinstance(result, str):
            reply = result
        else:
            reply = str(result) if result is not None else ""
        return {"reply": reply}
    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(
            500,
            detail={
                "message": f"App runtime error: {type(e).__name__}: {e}",
                "error_type": type(e).__name__,
                "traceback": tb,
                "app_id": app_id,
                "auto_fixable": True,
            },
        )


@router.post("/apps/{app_id}/test")
async def test_app(app_id: str, user: dict = Depends(get_current_user)):
    """Quick-test an app by trying to import its module."""
    try:
        mod = app_registry.load_app_module(app_id)
    except Exception as e:
        tb = traceback.format_exc()
        return {
            "ok": False,
            "phase": "import",
            "error": f"{type(e).__name__}: {e}",
            "traceback": tb,
            "auto_fixable": True,
        }

    if not mod:
        return {
            "ok": False,
            "phase": "import",
            "error": f"Module not found for app '{app_id}'",
            "traceback": "",
            "auto_fixable": True,
        }

    if not hasattr(mod, "router"):
        return {
            "ok": False,
            "phase": "structure",
            "error": "Module has no 'router' attribute.",
            "traceback": "",
            "auto_fixable": True,
        }

    return {"ok": True, "phase": "ready", "error": None}


# ---------- Admin Routes ----------

@router.get("/admin/users")
async def admin_list_users(admin: dict = Depends(require_admin)):
    """List all users (admin only)."""
    from sqlalchemy import select as sa_select
    from backend.core.database import User, async_session as db_session
    async with db_session() as session:
        result = await session.execute(sa_select(User).order_by(User.created_at))
        return [u.to_dict() for u in result.scalars().all()]


@router.get("/admin/apps")
async def admin_list_all_apps(admin: dict = Depends(require_admin)):
    """List ALL apps regardless of ownership (admin only)."""
    return await app_registry.list_apps(user_id=None)
