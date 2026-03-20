"""
App registry – discover, register, and manage sub-apps.
Supports multi-user: each app has an author, users can add market apps to their list.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Optional

from sqlalchemy import select, or_

from backend.core.database import AppRecord, UserApp, async_session, init_db


# In-memory cache of loaded app modules
_loaded_apps: dict[str, object] = {}

# Built-in apps (owned by the system, visible to all users)
BUILTIN_APPS = {
    "excel_analyzer": {
        "name": "Excel Analyzer",
        "description": "Upload Excel files for AI-powered data analysis and chart generation",
        "icon": "📊",
        "category": "data",
        "author": "platform",
    },
    "rag_reader": {
        "name": "RAG Reader",
        "description": "Upload documents for AI-powered reading and question answering (RAG)",
        "icon": "📖",
        "category": "knowledge",
        "author": "platform",
    },
}


async def initialize():
    """Initialize db and register built-in apps."""
    await init_db()
    for app_id, meta in BUILTIN_APPS.items():
        await register_app(app_id, **meta, is_public=True, skip_if_exists=True)


async def register_app(
    app_id: str,
    *,
    name: str,
    description: str = "",
    icon: str = "🤖",
    category: str = "general",
    author: str = "",
    author_id: Optional[str] = None,
    is_public: bool = False,
    config: Optional[dict] = None,
    skip_if_exists: bool = False,
) -> dict:
    async with async_session() as session:
        existing = await session.get(AppRecord, app_id)
        if existing:
            if skip_if_exists:
                return existing.to_dict()
            # Update existing
            existing.name = name
            existing.description = description
            existing.icon = icon
            existing.category = category
            existing.author = author
            if author_id is not None:
                existing.author_id = author_id
            existing.is_public = is_public
            if config:
                existing.config = config
            await session.commit()
            return existing.to_dict()

        record = AppRecord(
            id=app_id,
            name=name,
            description=description,
            icon=icon,
            category=category,
            author=author,
            author_id=author_id,
            is_public=is_public,
        )
        if config:
            record.config = config
        session.add(record)
        await session.commit()
        return record.to_dict()


async def list_apps(user_id: Optional[str] = None) -> list[dict]:
    """
    List apps visible to a user:
    - Apps the user created (author_id == user_id)
    - Apps the user added from market (via UserApp)
    - Built-in apps (author_id is None, i.e. platform apps)
    If user_id is None, return all enabled apps (backward compat).
    """
    async with async_session() as session:
        if user_id is None:
            result = await session.execute(
                select(AppRecord).where(AppRecord.enabled == True).order_by(AppRecord.sort_order)
            )
            return [r.to_dict() for r in result.scalars().all()]

        # Get app IDs the user has added from market
        ua_result = await session.execute(
            select(UserApp.app_id).where(UserApp.user_id == user_id)
        )
        added_app_ids = [row[0] for row in ua_result.all()]

        # Query: user's own apps + added market apps + built-in (no author_id) apps
        result = await session.execute(
            select(AppRecord).where(
                AppRecord.enabled == True,
                or_(
                    AppRecord.author_id == user_id,          # User's own
                    AppRecord.id.in_(added_app_ids) if added_app_ids else False,  # Added from market
                    AppRecord.author_id.is_(None),           # Built-in/platform
                ),
            ).order_by(AppRecord.sort_order)
        )
        return [r.to_dict() for r in result.scalars().all()]


async def list_market_apps(user_id: Optional[str] = None) -> list[dict]:
    """
    List all public apps (the market).
    Optionally annotate which apps the user has already added.
    """
    async with async_session() as session:
        result = await session.execute(
            select(AppRecord).where(
                AppRecord.enabled == True,
                AppRecord.is_public == True,
            ).order_by(AppRecord.sort_order)
        )
        apps = [r.to_dict() for r in result.scalars().all()]

        if user_id:
            ua_result = await session.execute(
                select(UserApp.app_id).where(UserApp.user_id == user_id)
            )
            added_ids = {row[0] for row in ua_result.all()}
            for app in apps:
                app["added_by_user"] = app["id"] in added_ids or app.get("author_id") == user_id
        return apps


async def add_market_app(user_id: str, app_id: str) -> bool:
    """Add a market app to a user's app list."""
    async with async_session() as session:
        # Check app exists and is public
        app = await session.get(AppRecord, app_id)
        if not app or not app.is_public:
            return False
        # Check not already added
        existing = await session.execute(
            select(UserApp).where(UserApp.user_id == user_id, UserApp.app_id == app_id)
        )
        if existing.scalar_one_or_none():
            return True  # Already added, that's fine
        ua = UserApp(user_id=user_id, app_id=app_id)
        session.add(ua)
        await session.commit()
        return True


async def remove_market_app(user_id: str, app_id: str) -> bool:
    """Remove a market app from a user's app list."""
    async with async_session() as session:
        result = await session.execute(
            select(UserApp).where(UserApp.user_id == user_id, UserApp.app_id == app_id)
        )
        ua = result.scalar_one_or_none()
        if not ua:
            return False
        await session.delete(ua)
        await session.commit()
        return True


async def publish_app(app_id: str, user_id: str) -> Optional[dict]:
    """Publish an app to the market (set is_public=True). Only the owner or admin can do this."""
    async with async_session() as session:
        record = await session.get(AppRecord, app_id)
        if not record:
            return None
        # Ownership check is done at the route level
        record.is_public = True
        await session.commit()
        return record.to_dict()


async def unpublish_app(app_id: str) -> Optional[dict]:
    """Remove an app from the market."""
    async with async_session() as session:
        record = await session.get(AppRecord, app_id)
        if not record:
            return None
        record.is_public = False
        await session.commit()
        return record.to_dict()


async def get_app(app_id: str) -> Optional[dict]:
    async with async_session() as session:
        record = await session.get(AppRecord, app_id)
        return record.to_dict() if record else None


async def delete_app(app_id: str) -> bool:
    async with async_session() as session:
        record = await session.get(AppRecord, app_id)
        if not record:
            return False
        # Also remove all UserApp references
        ua_result = await session.execute(
            select(UserApp).where(UserApp.app_id == app_id)
        )
        for ua in ua_result.scalars().all():
            await session.delete(ua)
        await session.delete(record)
        await session.commit()
        return True


async def update_app_config(app_id: str, config: dict) -> Optional[dict]:
    async with async_session() as session:
        record = await session.get(AppRecord, app_id)
        if not record:
            return None
        record.config = config
        await session.commit()
        return record.to_dict()


def load_app_module(app_id: str):
    """Dynamically load a sub-app's Python module."""
    if app_id in _loaded_apps:
        return _loaded_apps[app_id]
    try:
        mod = importlib.import_module(f"backend.apps.{app_id}.main")
        _loaded_apps[app_id] = mod
        return mod
    except Exception:
        return None


def reload_app_module(app_id: str):
    """
    Force-reload a sub-app module (and its sub-modules).
    Call this after auto-fix modifies app source files.
    """
    _loaded_apps.pop(app_id, None)
    import sys
    prefix = f"backend.apps.{app_id}"
    stale_keys = [k for k in sys.modules if k.startswith(prefix)]
    for k in stale_keys:
        del sys.modules[k]
    return load_app_module(app_id)
