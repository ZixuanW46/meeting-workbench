from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from meeting_api import models  # noqa: F401  确保表已注册
from meeting_api.config import Settings
from meeting_api.db import Base

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings.resolved_database_url()


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
