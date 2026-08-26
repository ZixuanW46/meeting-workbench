from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from meeting_api.config import Settings
from meeting_api.db import init_db, make_engine, make_session_factory
from meeting_api.routes import health, meetings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        engine = make_engine(settings.resolved_database_url())
        # M0 简化：启动时直接建表。M1 起改为要求先跑 Alembic 迁移。
        init_db(engine)
        app.state.engine = engine
        app.state.session_factory = make_session_factory(engine)
        yield
        engine.dispose()

    app = FastAPI(title="meeting-workbench", lifespan=lifespan)
    app.state.settings = settings
    app.include_router(health.router)
    app.include_router(meetings.router)
    return app


app = create_app()
