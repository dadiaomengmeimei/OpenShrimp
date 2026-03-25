"""
AI App Store – FastAPI main entry point.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # Load .env before importing settings

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import platform_settings
from backend.api.routes import router as platform_router, register_error_handlers
from backend.core import app_registry
from backend.core.auth import router as auth_router, ensure_default_admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Path(platform_settings.data_dir).mkdir(parents=True, exist_ok=True)
    await app_registry.initialize()
    await ensure_default_admin()
    yield
    # Shutdown (nothing to do for now)


app = FastAPI(
    title=platform_settings.app_name,
    lifespan=lifespan,
)

# Register unified error handlers (normalizes HTTPException to always include 'message' field)
register_error_handlers(app)

# CORS
origins = [o.strip() for o in platform_settings.cors_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth routes (no auth required for login/register)
app.include_router(auth_router)

# Per-app routers (must be registered BEFORE platform_router so that
# specific paths like /api/apps/excel_analyzer/upload take precedence
# over the generic /api/apps/{app_id}/upload catch-all)
from backend.apps.excel_analyzer.main import router as excel_router
from backend.apps.rag_reader.main import router as rag_router
from backend.apps.db_distribution_analyzer.main import router as db_analyzer_router
from backend.apps.insight_dashboard.main import router as insight_dashboard_router
from backend.agent.code_agent import router as agent_router

app.include_router(excel_router)
app.include_router(rag_router)
app.include_router(db_analyzer_router)
app.include_router(insight_dashboard_router)
app.include_router(agent_router)

# Platform API routes (generic catch-all routes last)
app.include_router(platform_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
