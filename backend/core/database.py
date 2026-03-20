"""
Database models and helpers for the platform (app registry, configs, etc.).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, ForeignKey, create_engine, UniqueConstraint
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship

from backend.config import platform_settings


class Base(DeclarativeBase):
    pass


class User(Base):
    """User account for the platform."""
    __tablename__ = "users"

    id = Column(String(64), primary_key=True)  # UUID
    username = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(128), default="")
    password_hash = Column(String(256), nullable=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name or self.username,
            "is_admin": self.is_admin,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AppRecord(Base):
    """Stores metadata for every registered sub-app."""
    __tablename__ = "apps"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    icon = Column(String(256), default="")
    version = Column(String(32), default="1.0.0")
    author = Column(String(64), default="")
    author_id = Column(String(64), ForeignKey("users.id"), nullable=True)  # Owner user
    category = Column(String(64), default="general")
    config_json = Column(Text, default="{}")
    enabled = Column(Boolean, default=True)
    is_public = Column(Boolean, default=False)  # Published to market
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def config(self) -> dict:
        return json.loads(self.config_json) if self.config_json else {}

    @config.setter
    def config(self, value: dict):
        self.config_json = json.dumps(value, ensure_ascii=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "icon": self.icon,
            "version": self.version,
            "author": self.author,
            "author_id": self.author_id,
            "category": self.category,
            "config": self.config,
            "enabled": self.enabled,
            "is_public": self.is_public,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class UserApp(Base):
    """
    Association between users and apps they have added (from market).
    An app created by a user is implicitly in their list (via author_id).
    This table tracks apps added FROM the market.
    """
    __tablename__ = "user_apps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    app_id = Column(String(64), ForeignKey("apps.id"), nullable=False, index=True)
    added_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "app_id", name="uq_user_app"),
    )


# Async engine & session factory
engine = create_async_engine(platform_settings.db_url, echo=platform_settings.debug)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Create all tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
