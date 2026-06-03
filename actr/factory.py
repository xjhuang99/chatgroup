"""FastAPI application factory and lifecycle hooks."""

import asyncio
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from actr.ai_service import batch_save_messages
from actr.group_chat import group_timeout_watcher
from actr.routes import register_routes
from cache_manager import cache_manager

load_dotenv()


def create_app() -> FastAPI:
    app = FastAPI(title="Hybrid AI Chat System with Session Management")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    Path("static").mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory="static"), name="static")

    register_routes(app)

    @app.on_event("startup")
    async def startup_event():
        print("🚀 Starting ACTR Application...")
        from bot_manager import log_llm_providers

        log_llm_providers()
        cache_manager.set_persist_callback(batch_save_messages)
        await cache_manager.start()
        asyncio.create_task(group_timeout_watcher())
        print("✅ Cache manager started with persist callback")

    @app.on_event("shutdown")
    async def shutdown_event():
        print("🛑 Shutting down application...")
        await cache_manager.stop()
        await cache_manager.flush_messages()
        print("✅ Cache flushed and manager stopped")

    return app


app = create_app()
