from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str) -> Engine:
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _configure_sqlite(dbapi_connection, _record) -> None:
            # SQLite 默认不强制外键：模型里的 ondelete=CASCADE 与 person_id 引用
            # 只有开了 PRAGMA 才真正生效。WAL 让 worker 长写与请求读互不阻塞。
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """开发/测试用：直接建表。真实部署走 `make migrate`（Alembic）。"""
    # 确保模型都已注册到 Base.metadata
    from meeting_api import models  # noqa: F401

    Base.metadata.create_all(engine)
