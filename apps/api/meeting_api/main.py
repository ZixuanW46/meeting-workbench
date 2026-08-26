from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from meeting_api.config import Settings
from meeting_api.db import init_db, make_engine, make_session_factory
from meeting_api.events import EventStore
from meeting_api.events import router as events_router
from meeting_api.routes import export, health, meetings, minutes, review, upload
from meeting_api.routes import settings as settings_routes
from meeting_api.worker import Worker

logger = logging.getLogger(__name__)


def _run_worker_loop(worker: Worker, stop_event: threading.Event, poll_seconds: float) -> None:
    while not stop_event.is_set():
        try:
            worker.process_next()
        except Exception:
            logger.exception("worker 轮询失败")
        stop_event.wait(poll_seconds)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        engine = make_engine(settings.resolved_database_url())
        # 测试依赖 lifespan 自动建临时库；真实运行按 README 先执行 Alembic 迁移。
        init_db(engine)
        app.state.engine = engine
        app.state.session_factory = make_session_factory(engine)
        app.state.events = EventStore()
        app.state.worker = Worker(
            app.state.session_factory,
            settings,
            event_store=app.state.events,
        )
        stop_event = threading.Event()
        worker_thread: threading.Thread | None = None
        if not settings.worker_disabled:
            worker_thread = threading.Thread(
                target=_run_worker_loop,
                args=(app.state.worker, stop_event, settings.worker_poll_seconds),
                name="meeting-worker",
                daemon=True,
            )
            worker_thread.start()
        try:
            yield
        finally:
            stop_event.set()
            if worker_thread is not None:
                worker_thread.join(timeout=5)
            engine.dispose()

    app = FastAPI(title="meeting-workbench", lifespan=lifespan)
    app.state.settings = settings
    app.include_router(health.router)
    app.include_router(meetings.router)
    app.include_router(upload.router)
    app.include_router(review.router)
    app.include_router(minutes.router)
    app.include_router(export.router)
    app.include_router(settings_routes.router)
    app.include_router(events_router)
    return app


app = create_app()
