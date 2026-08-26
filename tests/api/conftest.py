import pytest
from fastapi.testclient import TestClient

from meeting_api.config import Settings
from meeting_api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MW_WORKER_DISABLED", "1")
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path}/test.sqlite3",
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c
